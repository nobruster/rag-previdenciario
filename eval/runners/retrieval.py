"""Recall@k e MRR da recuperação.

Itens sem cobertura no corpus ficam FORA do denominador: não se mede
recuperação de algo que não está indexado. Misturar os dois produz uma métrica
que piora quando o corpus cresce com lacunas, e não distingue "o retriever
errou" de "o documento não existe".
"""

import re

from eval.common import (
    ItemResultado,
    Metrica,
    carregar_gold_set,
    edicoes_carregadas,
    engines_disponiveis,
    motivo_para_pular,
    tem_cobertura,
)

TOP_K = 5


def _artigo_esperado(ref: str) -> str | None:
    m = re.search(r"art\.?\s*(\d+(?:-[A-Z])?)", ref, re.IGNORECASE)
    return m.group(1) if m else None


def rodar() -> tuple[Metrica, dict]:
    from isp_rag.memory.engine import buscar

    engines = engines_disponiveis()
    edicoes = edicoes_carregadas()
    metrica = Metrica(nome="RECUPERAÇÃO")
    posicoes: list[int] = []
    sem_cobertura = 0

    for item in carregar_gold_set():
        if not item.get("expected_source_ref"):
            continue

        motivo = motivo_para_pular(item, engines, edicoes)
        if motivo:
            metrica.itens.append(ItemResultado(item["id"], "skipped", motivo=motivo))
            continue

        if not tem_cobertura(item):
            sem_cobertura += 1
            metrica.itens.append(
                ItemResultado(item["id"], "skipped", motivo="sem cobertura no corpus")
            )
            continue

        alvo = _artigo_esperado(item["expected_source_ref"])
        resultados = buscar(item["question"], top_k=TOP_K)
        artigos = [r.chunk.artigo for r in resultados]

        posicao = artigos.index(alvo) + 1 if alvo in artigos else 0
        if posicao:
            posicoes.append(posicao)

        metrica.itens.append(
            ItemResultado(
                item["id"],
                "ok" if posicao else "falha",
                esperado=alvo,
                obtido=artigos,
                motivo=None if posicao else f"art. {alvo} fora do top-{TOP_K}",
            )
        )

    avaliados = len(metrica.avaliados)
    detalhes = {
        f"recall@{TOP_K}": (len(posicoes) / avaliados) if avaliados else None,
        "recall@1": (sum(1 for p in posicoes if p == 1) / avaliados) if avaliados else None,
        "mrr": (sum(1 / p for p in posicoes) / avaliados) if avaliados else None,
        "sem_cobertura": sem_cobertura,
    }
    return metrica, detalhes
