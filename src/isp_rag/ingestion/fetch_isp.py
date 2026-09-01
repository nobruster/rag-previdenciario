"""CLI de coleta do ISP.

    python -m isp_rag.ingestion.fetch_isp --year 2025
    python -m isp_rag.ingestion.fetch_isp --all
    python -m isp_rag.ingestion.fetch_isp --check
"""

import argparse
import sys

from isp_rag.config import settings
from isp_rag.ingestion.fetcher import fetch
from isp_rag.ingestion.manifest import Manifest
from isp_rag.ingestion.sources import edicoes_disponiveis, isp_urls, validate_sources


def _coletar(anos: list[int]) -> int:
    dest = settings.raw_dir
    manifesto = Manifest(dest / "manifest.json")
    falhas = 0

    print(f"{'ano':<6}{'documento':<24}{'arquivo':<52}{'sha256':<14}{'MB':>7}  status")
    print("-" * 112)

    for ano in anos:
        for chave, url in isp_urls(ano).items():
            ja_tinha = manifesto.by_url(url) is not None
            try:
                e = fetch(url, dest)
                status = "já existia" if ja_tinha else "baixado"
                mb = e.size_bytes / 1_048_576
                print(
                    f"{ano:<6}{chave:<24}{e.filename[:50]:<52}"
                    f"{e.sha256[:12]:<14}{mb:>7.2f}  {status}"
                )
            except Exception as exc:
                falhas += 1
                print(f"{ano:<6}{chave:<24}{'—':<52}{'—':<14}{'—':>7}  ERRO: {exc}")

    print("-" * 112)
    print(f"manifesto: {dest / 'manifest.json'}")
    return falhas


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta os arquivos públicos do ISP-RPPS.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--year", type=int, help="edição a coletar")
    g.add_argument("--all", action="store_true", help="todas as edições")
    g.add_argument("--check", action="store_true", help="valida o registro sem baixar nada")
    args = p.parse_args()

    problemas = validate_sources()
    if args.check:
        if problemas:
            print("problemas no registro de fontes:")
            for item in problemas:
                print(f"  - {item}")
        else:
            print("registro de fontes íntegro.")
        print(f"edições disponíveis: {edicoes_disponiveis()}")
        return 0

    # Legislação pendente não impede a coleta do ISP; só é reportada.
    for item in problemas:
        print(f"aviso: {item}", file=sys.stderr)

    anos = edicoes_disponiveis() if args.all else [args.year]
    return 1 if _coletar(anos) else 0


if __name__ == "__main__":
    raise SystemExit(main())
