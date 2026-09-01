"""Indexação do corpus normativo no Qdrant.

Dois vetores por chunk: denso (semântico) e esparso (termo literal). A densa
resolve "qual o prazo para enviar o demonstrativo"; a esparsa resolve "art. 241"
e "DIPR", que a busca semântica erra com frequência.
"""

import re
from collections import Counter
from hashlib import blake2b

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from isp_rag.config import settings
from isp_rag.llm import get_provider
from isp_rag.memory.chunker import ArticleChunk

DENSO = "denso"
ESPARSO = "esparso"

# Campos que sustentam o filtro de vigência e o lookup por citação.
CAMPOS_INDEXADOS = {
    "norma": qm.PayloadSchemaType.KEYWORD,
    "numero": qm.PayloadSchemaType.KEYWORD,
    "artigo": qm.PayloadSchemaType.KEYWORD,
    "situacao": qm.PayloadSchemaType.KEYWORD,
    "capitulo": qm.PayloadSchemaType.KEYWORD,
    "secao": qm.PayloadSchemaType.KEYWORD,
}

_TOKEN_RE = re.compile(r"[0-9a-zà-ÿ]+(?:-[0-9a-zà-ÿ]+)*", re.IGNORECASE)


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def tokenizar(texto: str) -> list[str]:
    """Tokens para o vetor esparso. Preserva "art", "241" e "5º-a" separados."""
    return _TOKEN_RE.findall(texto.lower())


def vetor_esparso(texto: str) -> qm.SparseVector:
    """Bag-of-words com frequência.

    Implementação própria em vez de um modelo BM25 externo: o corpus é pequeno,
    e isto evita mais uma dependência de rede na ingestão. O que importa aqui é
    casar o termo literal, e para isso a frequência basta.
    """
    contagem = Counter(tokenizar(texto))
    indices, valores = [], []
    for termo, n in contagem.items():
        # blake2b de 4 bytes: determinístico entre execuções, ao contrário de hash().
        indices.append(int.from_bytes(blake2b(termo.encode(), digest_size=4).digest(), "big"))
        valores.append(float(n))
    return qm.SparseVector(indices=indices, values=valores)


def ponto_id(chunk: ArticleChunk) -> int:
    """Id estável: reindexar não duplica, mas artigos distintos não colidem.

    A hierarquia entra na chave porque o número do artigo NÃO é único dentro de
    uma norma: a Portaria 1.467 tem 17 "Art. 1º" — um por Anexo. Sem isso, 222
    dos 532 chunks se sobrescreviam silenciosamente.
    """
    chave = "|".join(
        [
            chunk.norma,
            chunk.titulo or "",
            chunk.capitulo or "",
            chunk.secao or "",
            chunk.subsecao or "",
            chunk.artigo,
            str(chunk.subchunk_idx),
            blake2b(chunk.text_raw.encode(), digest_size=8).hexdigest(),
        ]
    )
    return int.from_bytes(blake2b(chave.encode(), digest_size=8).digest(), "big") >> 1


def ensure_collection(client: QdrantClient | None = None, *, recreate: bool = False) -> None:
    client = client or get_client()
    nome = settings.qdrant_collection

    if recreate and client.collection_exists(nome):
        client.delete_collection(nome)

    if not client.collection_exists(nome):
        client.create_collection(
            collection_name=nome,
            vectors_config={
                DENSO: qm.VectorParams(size=settings.embed_dim, distance=qm.Distance.COSINE)
            },
            sparse_vectors_config={ESPARSO: qm.SparseVectorParams(index=qm.SparseIndexParams())},
        )

    for campo, tipo in CAMPOS_INDEXADOS.items():
        try:
            client.create_payload_index(nome, field_name=campo, field_schema=tipo)
        except Exception:
            pass  # já existe


def index_chunks(
    chunks: list[ArticleChunk],
    client: QdrantClient | None = None,
    *,
    batch_size: int = 64,
) -> int:
    """Indexa em lote. Retorna quantos pontos foram gravados."""
    if not chunks:
        return 0

    client = client or get_client()
    ensure_collection(client)
    provider = get_provider()
    total = 0

    for inicio in range(0, len(chunks), batch_size):
        lote = chunks[inicio : inicio + batch_size]
        # O embedding usa chunk.text — COM o prefixo de hierarquia. Embeddar
        # text_raw perderia exatamente o ganho da T06.
        densos = provider.embed([c.text for c in lote])

        client.upsert(
            collection_name=settings.qdrant_collection,
            points=[
                qm.PointStruct(
                    id=ponto_id(c),
                    vector={DENSO: denso, ESPARSO: vetor_esparso(c.text)},
                    payload=c.model_dump(mode="json"),
                )
                for c, denso in zip(lote, densos, strict=True)
            ],
        )
        total += len(lote)

    return total


def contar_pontos(client: QdrantClient | None = None) -> int:
    client = client or get_client()
    if not client.collection_exists(settings.qdrant_collection):
        return 0
    return client.count(settings.qdrant_collection, exact=True).count
