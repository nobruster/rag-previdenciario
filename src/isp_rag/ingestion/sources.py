"""Fontes públicas do ISP-RPPS.

As URLs vivem em `data/raw/sources.json`, versionado junto do código — não são
redigitadas aqui. Foram verificadas por requisição real (status, content-type e
magic bytes) em setembro/2026.

As URLs da legislação estão `null` de propósito. Preenchê-las exige buscar no
Planalto, e a spec §9 recomenda avaliar o HTML estruturado antes de recorrer a
PDF. Uma URL fabricada viola R1 na primeira execução e é pior que um TODO
honesto.
"""

import json
from functools import lru_cache
from pathlib import Path

from isp_rag.config import settings

PAGINA_OFICIAL = (
    "https://www.gov.br/previdencia/pt-br/assuntos/rpps/indice-de-situacao-previdenciaria"
)


def _sources_file() -> Path:
    return settings.raw_dir / "sources.json"


@lru_cache(maxsize=1)
def load_sources() -> dict:
    """Lê o registro de fontes. É a fonte única das URLs (R1)."""
    path = _sources_file()
    if not path.exists():
        raise FileNotFoundError(
            f"registro de fontes ausente em {path}. Ele é versionado no git — "
            f"restaure-o em vez de recriar à mão."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def edicoes_disponiveis() -> list[int]:
    return sorted((int(ano) for ano in load_sources()["edicoes"]), reverse=True)


def isp_urls(ano: int) -> dict[str, str]:
    """URLs de uma edição, por tipo de documento (chaves com `_` são notas)."""
    edicoes = load_sources()["edicoes"]
    if str(ano) not in edicoes:
        raise KeyError(f"edição {ano} não está no registro. Disponíveis: {edicoes_disponiveis()}")
    return {k: v for k, v in edicoes[str(ano)].items() if not k.startswith("_") and v}


def legislacao_urls() -> dict[str, str]:
    """URLs da legislação. Levanta enquanto estiverem pendentes."""
    leis = {
        k: v for k, v in load_sources()["legislacao"].items() if not k.startswith("_")
    }
    pendentes = [k for k, v in leis.items() if not v]
    if pendentes:
        raise NotImplementedError(
            f"URLs de legislação ainda não levantadas: {', '.join(pendentes)}. "
            f"Preencha em {_sources_file()} — buscando no Planalto, preferindo "
            f"HTML estruturado a PDF (spec §9). Não invente URL (R1)."
        )
    return leis


def validate_sources() -> list[str]:
    """Problemas no registro, para o CLI não rodar em silêncio com lista vazia."""
    problemas: list[str] = []
    dados = load_sources()

    if not dados.get("edicoes"):
        problemas.append("nenhuma edição no registro")

    for ano, docs in dados.get("edicoes", {}).items():
        urls = {k: v for k, v in docs.items() if not k.startswith("_")}
        if not urls:
            problemas.append(f"edição {ano} sem nenhuma URL")
        for chave, url in urls.items():
            if not url:
                problemas.append(f"{ano}.{chave} está vazia")
            elif not str(url).startswith("https://"):
                problemas.append(f"{ano}.{chave} não é https: {url}")

    pendentes = [
        k for k, v in dados.get("legislacao", {}).items() if not k.startswith("_") and not v
    ]
    if pendentes:
        problemas.append(f"legislação pendente ({len(pendentes)}): {', '.join(pendentes)}")

    return problemas
