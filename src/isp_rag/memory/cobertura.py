"""Cobertura do corpus — o que o sistema PODE responder.

Existe para separar dois casos que uma recusa não distingue sozinha:

  (a) o corpus contém a resposta e a recuperação falhou  → falha de qualidade
  (b) o corpus não contém a resposta                     → recusa correta

Sem essa distinção, o gold set da T11 mede a base em vez de medir o sistema, e
uma recusa legítima entra na métrica como erro. O caso que motivou isto: "qual
o prazo para envio do DIPR?" recusa, e a recusa está certa — o termo aparece
2 vezes em 714 chunks, e o prazo não está em nenhuma delas.
"""

import re
import unicodedata
from dataclasses import dataclass

from qdrant_client import QdrantClient

from isp_rag.config import settings
from isp_rag.memory.indexer import get_client


@dataclass
class Cobertura:
    termo: str
    n_chunks: int
    artigos: list[str]

    @property
    def coberto(self) -> bool:
        return self.n_chunks > 0

    def __str__(self) -> str:
        if not self.coberto:
            return f"{self.termo}: AUSENTE do corpus"
        arts = ", ".join(f"art. {a}" for a in self.artigos[:5])
        return f"{self.termo}: {self.n_chunks} chunk(s) — {arts}"


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def cobertura_de(termo: str, client: QdrantClient | None = None) -> Cobertura:
    """Em quantos chunks o termo aparece, e em quais artigos.

    Varredura literal sobre o payload, não busca semântica: a pergunta aqui é
    "este assunto está no corpus?", não "qual o chunk mais parecido?".
    """
    client = client or get_client()
    if not client.collection_exists(settings.qdrant_collection):
        return Cobertura(termo=termo, n_chunks=0, artigos=[])

    alvo = _normalizar(termo)
    padrao = re.compile(rf"\b{re.escape(alvo)}\b")
    artigos: list[str] = []
    proximo = None

    while True:
        pontos, proximo = client.scroll(
            settings.qdrant_collection, limit=256, offset=proximo, with_payload=True
        )
        for p in pontos:
            texto = _normalizar(p.payload.get("text_raw") or "")
            if padrao.search(texto):
                artigos.append(str(p.payload.get("artigo", "?")))
        if proximo is None:
            break

    return Cobertura(termo=termo, n_chunks=len(artigos), artigos=sorted(set(artigos)))


def diagnosticar_recusa(pergunta: str, client: QdrantClient | None = None) -> dict:
    """Classifica uma recusa: o corpus tem o assunto ou não?

    Devolve os termos significativos da pergunta e a cobertura de cada um, mais
    um veredito para a T11 usar ao interpretar a métrica.
    """
    stop = {
        "qual", "quais", "quanto", "quantos", "quando", "onde", "como", "que", "o", "a", "os",
        "as", "de", "do", "da", "dos", "das", "em", "no", "na", "para", "por", "com", "sobre",
        "um", "uma", "e", "ou", "se", "the", "of", "eh", "é",
    }
    termos = [
        t
        for t in re.findall(r"[0-9A-Za-zÀ-ÿ]{3,}", pergunta)
        if _normalizar(t) not in stop
    ]

    coberturas = [cobertura_de(t, client) for t in termos]
    ausentes = [c.termo for c in coberturas if not c.coberto]
    raros = [c.termo for c in coberturas if 0 < c.n_chunks <= 2]

    if ausentes:
        veredito = "fora_do_corpus"
    elif raros:
        veredito = "cobertura_rasa"
    else:
        veredito = "coberto"

    return {
        "pergunta": pergunta,
        "veredito": veredito,
        "termos_ausentes": ausentes,
        "termos_raros": raros,
        "cobertura": {c.termo: c.n_chunks for c in coberturas},
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Verifica se um assunto está no corpus indexado."
    )
    p.add_argument("termos", nargs="+", help="termos ou uma pergunta entre aspas")
    p.add_argument("--diagnostico", action="store_true", help="classifica uma recusa")
    args = p.parse_args()

    if args.diagnostico:
        resultado = diagnosticar_recusa(" ".join(args.termos))
        print(f"pergunta : {resultado['pergunta']}")
        print(f"veredito : {resultado['veredito']}")
        for termo, n in sorted(resultado["cobertura"].items(), key=lambda kv: kv[1]):
            marca = "AUSENTE" if n == 0 else ("raro" if n <= 2 else "ok")
            print(f"  {termo:<28} {n:>4} chunk(s)  {marca}")
        return 0

    for termo in args.termos:
        print(cobertura_de(termo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
