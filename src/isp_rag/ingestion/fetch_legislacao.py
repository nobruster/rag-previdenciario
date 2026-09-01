"""CLI de coleta da legislação dos RPPS.

    python -m isp_rag.ingestion.fetch_legislacao

Enquanto as URLs não forem levantadas, falha com instrução — nunca inventa
endereço (R1).
"""

from isp_rag.config import settings
from isp_rag.ingestion.fetcher import fetch_all
from isp_rag.ingestion.sources import legislacao_urls


def main() -> int:
    try:
        urls = legislacao_urls()
    except NotImplementedError as exc:
        print(exc)
        return 1

    entradas, erros = fetch_all(list(urls.values()), settings.raw_dir)
    for e in entradas:
        print(f"{e.filename:<60}{e.sha256[:12]}  {e.size_bytes / 1_048_576:.2f} MB")
    for url, msg in erros:
        print(f"ERRO {url}: {msg}")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
