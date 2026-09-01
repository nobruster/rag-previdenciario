"""T11 — a camada de avaliação.

Testes sobre a estrutura do gold set e a lógica dos runners. Rodar a avaliação
inteira gasta token e fica fora da suíte.
"""

import pytest

from eval.common import carregar_gold_set, motivo_para_pular, tem_cobertura
from eval.runners.sql_match import normalizar

CATEGORIAS = {
    "fato_numerico",
    "exigencia_normativa",
    "comparacao_edicoes",
    "capciosa",
    "sem_resposta",
}


@pytest.fixture(scope="module")
def gold():
    return carregar_gold_set()


# ---------------------------------------------------------------------------
# Estrutura do gold set
# ---------------------------------------------------------------------------
def test_quarenta_perguntas_oito_por_categoria(gold):
    assert len(gold) == 40
    from collections import Counter

    contagem = Counter(i["category"] for i in gold)
    assert set(contagem) == CATEGORIAS
    assert all(n == 8 for n in contagem.values()), dict(contagem)


def test_ids_unicos(gold):
    ids = [i["id"] for i in gold]
    assert len(set(ids)) == len(ids)


def test_todo_item_declara_cobertura(gold):
    """Sem isso o recall mede a base, não o sistema."""
    validos = {"coberto", "cobertura_rasa", "fora_do_corpus"}
    for item in gold:
        assert item.get("cobertura") in validos, item["id"]


def test_resposta_esperada_exige_cobertura(gold):
    """should_refuse=false só onde o corpus cobre o assunto."""
    for item in gold:
        if not item.get("should_refuse") and item["category"] != "capciosa":
            assert tem_cobertura(item), f"{item['id']}: responde mas não tem cobertura"


def test_sem_resposta_nao_tem_cobertura(gold):
    for item in gold:
        if item["category"] == "sem_resposta":
            assert item["cobertura"] in ("fora_do_corpus", "cobertura_rasa"), item["id"]


def test_itens_de_recusa_nao_medem_rota(gold):
    """Para pergunta que deve ser recusada, a engine escolhida é irrelevante."""
    for item in gold:
        if item["category"] == "sem_resposta":
            assert item.get("expected_engine") is None, item["id"]
            assert item.get("should_refuse") is True, item["id"]


def test_comparacao_cobre_a_ruptura(gold):
    """Pelo menos 3 itens cruzam 2024↔2025, e ao menos 2 ficam dentro do mesmo
    regime — para pegar também o falso positivo."""
    comp = [i for i in gold if i["category"] == "comparacao_edicoes"]
    com_ressalva = [i for i in comp if i.get("requires_ressalva") is True]
    sem_ressalva = [i for i in comp if i.get("requires_ressalva") is False]
    assert len(com_ressalva) >= 3, "faltam itens que cruzam a ruptura metodológica"
    assert len(sem_ressalva) >= 2, "faltam itens do mesmo regime (falso positivo)"


def test_fato_numerico_tem_sql_de_referencia(gold):
    for item in gold:
        if item["category"] == "fato_numerico":
            assert item.get("reference_sql"), item["id"]


# ---------------------------------------------------------------------------
# Lógica dos runners
# ---------------------------------------------------------------------------
def test_pular_por_engine_indisponivel():
    item = {"requires": {"engines": ["brain"]}, "expected_engine": "brain"}
    assert "brain" in motivo_para_pular(item, {"ledger", "memory"}, {2025})


def test_pular_por_edicao_ausente():
    item = {"requires": {"engines": ["ledger"], "edicoes": [2024]}, "expected_engine": "ledger"}
    motivo = motivo_para_pular(item, {"ledger"}, {2025})
    assert motivo and "2024" in motivo


def test_nao_pular_quando_tudo_disponivel():
    item = {"requires": {"engines": ["ledger"], "edicoes": [2025]}, "expected_engine": "ledger"}
    assert motivo_para_pular(item, {"ledger"}, {2025}) is None


def test_normalizacao_ignora_ordem_das_linhas():
    """Dois SQLs corretos podem devolver a mesma coisa em ordem diferente."""
    assert normalizar([("B", 2), ("A", 1)]) == normalizar([("A", 1), ("B", 2)])


def test_normalizacao_arredonda_numerico():
    from decimal import Decimal

    assert normalizar([(Decimal("1.000000001"),)]) == normalizar([(1.0,)])


def test_normalizacao_distingue_resultados_diferentes():
    assert normalizar([(159,)]) != normalizar([(0,)])
