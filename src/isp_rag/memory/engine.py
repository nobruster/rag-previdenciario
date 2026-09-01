"""Recuperação sobre o corpus normativo.

Três comportamentos que a busca vetorial pura não dá (spec §5.2):

1. Fusão híbrida — a densa entende a pergunta, a esparsa casa "art. 241" e
   "DIPR" literalmente.
2. Filtro de vigência por padrão — responder com dispositivo revogado é tão
   ruim quanto inventar.
3. Lookup por citação — se a pergunta cita um dispositivo, a busca vira consulta
   exata, não vetorial.
"""

import re
from datetime import date

from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from isp_rag.config import settings
from isp_rag.llm import get_provider
from isp_rag.memory.chunker import ArticleChunk
from isp_rag.memory.indexer import DENSO, ESPARSO, get_client, vetor_esparso

# "art. 241", "artigo 9º", "art. 5º-A"
CITACAO_RE = re.compile(
    r"\bart(?:igo|\.)?\s*(\d+)\s*(?:[ºo°])?\s*(-\s*[A-Z])?\b",
    re.IGNORECASE,
)
# "Portaria 1.467", "Lei 9.717/1998", "EC 103/2019"
NORMA_RE = re.compile(
    r"\b(?:portaria|lei|emenda\s+constitucional|ec)\s*(?:mtp|mps)?\s*"
    r"n?[ºo°.]?\s*([\d.]+)(?:\s*/\s*(\d{4}))?",
    re.IGNORECASE,
)


class Resultado(BaseModel):
    chunk: ArticleChunk
    score: float
    origem: str  # "citacao" | "hibrido"


def detectar_citacao(pergunta: str) -> tuple[str | None, str | None]:
    """(artigo, número da norma) citados explicitamente, se houver."""
    art = CITACAO_RE.search(pergunta)
    artigo = None
    if art:
        artigo = art.group(1) + (art.group(2) or "").replace(" ", "")
    norma = NORMA_RE.search(pergunta)
    return artigo, (norma.group(1) if norma else None)


def filtro_vigencia(
    reference_date: date | None = None,
    incluir_revogados: bool = False,
) -> qm.Filter | None:
    """Por padrão, só dispositivo vigente.

    `reference_date` responde "o que a norma exigia naquela data", filtrando
    pelas datas de vigência quando o chunk as tiver.
    """
    if incluir_revogados:
        return None

    condicoes: list[qm.Condition] = [
        qm.FieldCondition(key="situacao", match=qm.MatchAny(any=["vigente", "alterado"]))
    ]
    if reference_date:
        iso = reference_date.isoformat()
        condicoes.append(
            qm.Filter(
                should=[
                    qm.IsNullCondition(is_null=qm.PayloadField(key="data_inicio_vigencia")),
                    qm.FieldCondition(key="data_inicio_vigencia", range=qm.DatetimeRange(lte=iso)),
                ]
            )
        )
        condicoes.append(
            qm.Filter(
                should=[
                    qm.IsNullCondition(is_null=qm.PayloadField(key="data_fim_vigencia")),
                    qm.FieldCondition(key="data_fim_vigencia", range=qm.DatetimeRange(gte=iso)),
                ]
            )
        )
    return qm.Filter(must=condicoes)


def citation_lookup(
    pergunta: str,
    *,
    reference_date: date | None = None,
    incluir_revogados: bool = False,
    client: QdrantClient | None = None,
    limit: int = 5,
) -> list[Resultado] | None:
    """Consulta EXATA por payload quando a pergunta cita um dispositivo.

    Devolve None se não houver citação — aí o fluxo segue para o híbrido.
    """
    artigo, numero = detectar_citacao(pergunta)
    if not artigo:
        return None

    client = client or get_client()
    base = filtro_vigencia(reference_date, incluir_revogados)
    condicoes = list(base.must) if base else []
    condicoes.append(qm.FieldCondition(key="artigo", match=qm.MatchValue(value=artigo)))
    if numero:
        condicoes.append(qm.FieldCondition(key="numero", match=qm.MatchValue(value=numero)))

    pontos, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=qm.Filter(must=condicoes),
        limit=limit,
        with_payload=True,
    )
    if not pontos:
        return None
    return [
        Resultado(chunk=ArticleChunk(**p.payload), score=1.0, origem="citacao") for p in pontos
    ]


def buscar(
    pergunta: str,
    *,
    reference_date: date | None = None,
    incluir_revogados: bool = False,
    top_k: int = 5,
    sparse_top_k: int = 10,
    client: QdrantClient | None = None,
) -> list[Resultado]:
    """Recuperação híbrida, com lookup por citação como pré-etapa."""
    client = client or get_client()

    exatos = citation_lookup(
        pergunta,
        reference_date=reference_date,
        incluir_revogados=incluir_revogados,
        client=client,
        limit=top_k,
    )
    if exatos:
        return exatos

    denso = get_provider().embed([pergunta])[0]
    filtro = filtro_vigencia(reference_date, incluir_revogados)

    # Fusão por Reciprocal Rank Fusion, nativa do Qdrant.
    resposta = client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            qm.Prefetch(query=denso, using=DENSO, limit=top_k * 4, filter=filtro),
            qm.Prefetch(
                query=vetor_esparso(pergunta), using=ESPARSO, limit=sparse_top_k, filter=filtro
            ),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )
    return [
        Resultado(chunk=ArticleChunk(**p.payload), score=p.score or 0.0, origem="hibrido")
        for p in resposta.points
    ]
