"""Execution match do Text-to-SQL.

Compara os RESULTSETS, nunca as strings de SQL: dois SQLs diferentes podem
estar ambos corretos, e comparar texto é a métrica errada que a spec §7.3
aponta nominalmente.
"""

from decimal import Decimal

from eval.common import (
    ItemResultado,
    Metrica,
    carregar_gold_set,
    edicoes_carregadas,
    engines_disponiveis,
    motivo_para_pular,
)


def normalizar(resultset: list[tuple]) -> list[tuple]:
    """Ordena linhas e arredonda numéricos, para a comparação não depender de
    ORDER BY nem de precisão de ponto flutuante."""

    def celula(v):
        if isinstance(v, Decimal | float):
            return round(float(v), 4)
        return v

    return sorted((tuple(celula(v) for v in linha) for linha in resultset), key=repr)


def rodar() -> Metrica:
    from isp_rag.ledger.engine import build_ledger_engine, get_sql, run_sql

    engines = engines_disponiveis()
    edicoes = edicoes_carregadas()
    metrica = Metrica(nome="TEXT-TO-SQL")

    itens = [i for i in carregar_gold_set() if i.get("reference_sql")]
    if not itens:
        return metrica

    engine = build_ledger_engine() if "ledger" in engines else None

    for item in itens:
        motivo = motivo_para_pular(item, engines, edicoes)
        if motivo:
            metrica.itens.append(ItemResultado(item["id"], "skipped", motivo=motivo))
            continue

        try:
            esperado = normalizar(run_sql(item["reference_sql"]))
        except Exception as exc:
            metrica.itens.append(
                ItemResultado(item["id"], "skipped", motivo=f"SQL de referência falhou: {exc}")
            )
            continue

        try:
            resposta = engine.query(item["question"])
            sql = get_sql(resposta)
            if not sql:
                metrica.itens.append(
                    ItemResultado(item["id"], "falha", motivo="nenhum SQL nos metadados")
                )
                continue
            obtido = normalizar(run_sql(sql))
        except Exception as exc:
            metrica.itens.append(
                ItemResultado(item["id"], "falha", motivo=f"erro de execução: {exc}")
            )
            continue

        metrica.itens.append(
            ItemResultado(
                item["id"],
                "ok" if obtido == esperado else "falha",
                esperado=str(esperado)[:200],
                obtido=str(obtido)[:200],
                motivo=None if obtido == esperado else "resultsets divergentes",
            )
        )

    return metrica
