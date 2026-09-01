"""Acurácia do roteador e matriz de confusão.

Determinística e barata: usa `route()`, que decide sem executar a query.
"""

from collections import Counter

from eval.common import (
    ItemResultado,
    Metrica,
    carregar_gold_set,
    edicoes_carregadas,
    engines_disponiveis,
    motivo_para_pular,
)


def rodar() -> tuple[Metrica, Counter]:
    from isp_rag.query.router import route

    engines = engines_disponiveis()
    edicoes = edicoes_carregadas()
    metrica = Metrica(nome="ROTEAMENTO")
    confusao: Counter = Counter()

    for item in carregar_gold_set():
        motivo = motivo_para_pular(item, engines, edicoes)
        if motivo:
            metrica.itens.append(ItemResultado(item["id"], "skipped", motivo=motivo))
            continue

        esperado = item.get("expected_engine")
        if esperado is None:
            # Pergunta que deve ser RECUSADA: a engine escolhida é irrelevante,
            # e medi-la seria ruído. O que importa nesses itens é should_refuse.
            metrica.itens.append(
                ItemResultado(item["id"], "skipped", motivo="item de recusa — rota não se aplica")
            )
            continue

        decisao = route(item["question"], brain_enabled="brain" in engines)
        obtido = "multi" if decisao.is_multi_domain else decisao.engine

        confusao[(esperado, obtido)] += 1
        metrica.itens.append(
            ItemResultado(
                item["id"],
                "ok" if obtido == esperado else "falha",
                esperado=esperado,
                obtido=obtido,
            )
        )

    return metrica, confusao


def imprimir_confusao(confusao: Counter) -> None:
    rotulos = sorted({r for par in confusao for r in par})
    if not rotulos:
        return
    print("\n  matriz de confusão (linha = esperado, coluna = obtido)")
    print("    " + "".join(f"{r:>10}" for r in rotulos))
    for esperado in rotulos:
        linha = "".join(f"{confusao.get((esperado, o), 0):>10}" for o in rotulos)
        print(f"    {esperado:<8}{linha}")
