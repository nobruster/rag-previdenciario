"""CLI de carga do Ledger.

    python -m isp_rag.ledger.load --year 2025
    python -m isp_rag.ledger.load --all
"""

import argparse

from isp_rag.ledger.loader import COLUMN_MAP, init_schema, load_edicao, resolver_planilha


def main() -> int:
    p = argparse.ArgumentParser(description="Carrega edições do ISP no Ledger.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--year", type=int, help="edição a carregar")
    g.add_argument("--all", action="store_true", help="todas as edições mapeadas")
    args = p.parse_args()

    init_schema()
    anos = sorted(COLUMN_MAP) if args.all else [args.year]

    falhas = 0
    for ano in anos:
        try:
            caminho, url = resolver_planilha(ano)
            print(load_edicao(caminho, ano, url))
        except Exception as exc:
            falhas += 1
            print(f"edição {ano}: ERRO — {exc}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
