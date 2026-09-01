"""Rodada completa de avaliação.

    python -m eval.run_all                      # tudo
    python -m eval.run_all --deterministic-only # sem o judge (grátis)
    python -m eval.run_all --sample 10          # amostra do judge
"""

import argparse
import json
import logging
from datetime import UTC, datetime

from eval.common import RUNS_DIR, edicoes_carregadas, engines_disponiveis


def main() -> int:
    p = argparse.ArgumentParser(description="Avalia o ISP-RAG contra o gold set.")
    p.add_argument("--deterministic-only", action="store_true", help="pula o judge")
    p.add_argument("--sample", type=int, help="quantos itens no judge")
    p.add_argument("--limiar-roteamento", type=float, default=0.85, help="mínimo para CI")
    args = p.parse_args()

    # O retriever do LlamaIndex despeja o schema inteiro a cada consulta.
    for ruidoso in ("llama_index", "httpx", "openai", "isp_rag.api"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    engines = engines_disponiveis()
    edicoes = sorted(edicoes_carregadas())
    print(f"engines disponíveis: {sorted(engines) or '(nenhuma)'}")
    print(f"edições carregadas : {edicoes or '(nenhuma)'}\n")

    from eval.runners import retrieval, routing, sql_match

    resultado: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "engines": sorted(engines),
        "edicoes": edicoes,
    }

    metrica_rot, confusao = routing.rodar()
    print(metrica_rot.resumo())
    routing.imprimir_confusao(confusao)
    resultado["roteamento"] = metrica_rot.to_dict()

    metrica_sql = sql_match.rodar()
    print("\n" + metrica_sql.resumo())
    resultado["text_to_sql"] = metrica_sql.to_dict()

    metrica_rec, detalhes = retrieval.rodar()
    linha = metrica_rec.resumo()
    if detalhes.get("mrr") is not None:
        linha += f"   MRR {detalhes['mrr']:.2f}"
    if detalhes.get("sem_cobertura"):
        linha += f"   [{detalhes['sem_cobertura']} fora do denominador: sem cobertura]"
    print("\n" + linha)
    resultado["recuperacao"] = {**metrica_rec.to_dict(), **detalhes}

    if not args.deterministic_only:
        from eval.runners import generation

        print("\nrodando o judge (custo real)...")
        judge = generation.rodar(sample=args.sample)
        print(f"{'GERAÇÃO':<14} " + "  ".join(
            f"{k.split('_')[0]} {v}" for k, v in judge["medias"].items() if v is not None
        ) + f"   [amostra: {judge['avaliados']}]")
        resultado["geracao"] = judge

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    destino = RUNS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ngravado em {destino}")

    taxa = metrica_rot.taxa
    if taxa is not None and taxa < args.limiar_roteamento:
        print(f"FALHA: roteamento {taxa:.2f} abaixo do limiar {args.limiar_roteamento}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
