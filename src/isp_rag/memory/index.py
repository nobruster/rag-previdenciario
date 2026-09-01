"""CLI de indexação do corpus normativo.

    python -m isp_rag.memory.index --all
    python -m isp_rag.memory.index --norma portaria_mtp_1467_2022
    python -m isp_rag.memory.index --stats
"""

import argparse
from datetime import date
from pathlib import Path

from isp_rag.config import settings
from isp_rag.ingestion.manifest import Manifest
from isp_rag.ingestion.pdf_parser import extract_text
from isp_rag.ingestion.sources import legislacao_urls
from isp_rag.memory.chunker import NormaMeta, chunk_norma
from isp_rag.memory.indexer import contar_pontos, ensure_collection, index_chunks

# Metadados de citação por norma. O texto vem sempre do arquivo coletado (R1).
NORMAS: dict[str, dict] = {
    "portaria_mtp_1467_2022": dict(
        norma="Portaria MTP nº 1.467/2022", numero="1.467",
        data_norma=date(2022, 6, 2), orgao="MTP",
    ),
    "lei_9717_1998": dict(
        norma="Lei nº 9.717/1998", numero="9.717",
        data_norma=date(1998, 11, 27), orgao="Congresso Nacional",
    ),
    "lei_10887_2004": dict(
        norma="Lei nº 10.887/2004", numero="10.887",
        data_norma=date(2004, 6, 18), orgao="Congresso Nacional",
    ),
    "ec_20_1998": dict(
        norma="Emenda Constitucional nº 20/1998", numero="20",
        data_norma=date(1998, 12, 15), orgao="Congresso Nacional",
    ),
    "ec_41_2003": dict(
        norma="Emenda Constitucional nº 41/2003", numero="41",
        data_norma=date(2003, 12, 19), orgao="Congresso Nacional",
    ),
    "ec_47_2005": dict(
        norma="Emenda Constitucional nº 47/2005", numero="47",
        data_norma=date(2005, 7, 5), orgao="Congresso Nacional",
    ),
    "ec_103_2019": dict(
        norma="Emenda Constitucional nº 103/2019", numero="103",
        data_norma=date(2019, 11, 12), orgao="Congresso Nacional",
    ),
}


def _arquivo_da_norma(chave: str) -> tuple[Path, str]:
    """Resolve pelo manifesto — nunca por caminho manual (R1)."""
    url = legislacao_urls()[chave]
    entrada = Manifest(settings.raw_dir / "manifest.json").by_url(url)
    if entrada is None:
        raise FileNotFoundError(
            f"'{chave}' não foi coletada. Rode antes:\n"
            f"  python -m isp_rag.ingestion.fetch_legislacao"
        )
    return settings.raw_dir / entrada.filename, url


def indexar(chave: str) -> int:
    caminho, url = _arquivo_da_norma(chave)
    meta = NormaMeta(**NORMAS[chave], url=url)
    chunks = chunk_norma(extract_text(caminho), meta)
    n = index_chunks(chunks)
    print(f"{meta.norma:<38} {n:>5} chunks   ({caminho.name})")
    return n


def main() -> int:
    p = argparse.ArgumentParser(description="Indexa o corpus normativo no Qdrant.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--norma", choices=sorted(NORMAS), help="uma norma específica")
    g.add_argument("--all", action="store_true", help="todo o corpus")
    g.add_argument("--stats", action="store_true", help="o que está indexado")
    p.add_argument("--recreate", action="store_true", help="recria a coleção do zero")
    args = p.parse_args()

    if args.stats:
        print(f"coleção {settings.qdrant_collection}: {contar_pontos()} pontos")
        return 0

    if args.recreate:
        ensure_collection(recreate=True)

    total = sum(indexar(c) for c in (sorted(NORMAS) if args.all else [args.norma]))
    print(f"{'total':<38} {total:>5} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
