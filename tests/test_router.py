"""T08 — roteamento entre as engines.

A spec §6.1: o acerto do roteador é medido, não presumido. `route()` decide sem
executar, que é o que a T11 mede.
"""

import pytest

from isp_rag.query.router import RouteDecision, needs_decomposition, route

PERGUNTA_DEMO = (
    "O RPPS de determinado município caiu de B para C entre 2023 e 2025. "
    "Foi o desempenho dele que piorou ou a metodologia que mudou? "
    "E qual norma alterou isso?"
)

LEDGER = [
    "qual o conceito do RPPS de Campinas em 2025",
    "quantos entes tiveram conceito A em 2025",
    "qual a distribuição de conceitos por UF",
]
MEMORY = [
    "qual o prazo para envio do DIPR",
    "o que exige o art. 241 da Portaria 1.467",
    "quais os requisitos para emissão do CRP",
]
BRAIN = [
    "que critério do ISP mudou entre 2023 e 2025",
    "qual norma alterou o cálculo do indicador de cobertura",
    "quais indicadores compõem a dimensão atuária",
]


# ---------------------------------------------------------------------------
# Detecção de multi-domínio — heurística barata, sem LLM
# ---------------------------------------------------------------------------
def test_pergunta_de_demonstracao_e_multi_dominio():
    """Spec §3.4: pede o delta numérico E a norma que o explica."""
    assert needs_decomposition(PERGUNTA_DEMO)


@pytest.mark.parametrize("pergunta", LEDGER + MEMORY)
def test_pergunta_de_dominio_unico_nao_decompoe(pergunta):
    assert not needs_decomposition(pergunta)


def test_numero_mais_norma_decompoe():
    assert needs_decomposition("o conceito caiu porque a portaria mudou?")


def test_numero_mais_mudanca_decompoe():
    assert needs_decomposition("como evoluiu o conceito entre 2023 e 2025?")


# ---------------------------------------------------------------------------
# route() não executa
# ---------------------------------------------------------------------------
def test_route_multi_dominio_nao_chama_llm():
    """A heurística resolve antes de gastar chamada."""
    d = route(PERGUNTA_DEMO)
    assert d.is_multi_domain
    assert d.engine is None
    assert isinstance(d, RouteDecision)


# ---------------------------------------------------------------------------
# Acerto do roteador (gasta token)
# ---------------------------------------------------------------------------
@pytest.mark.llm
@pytest.mark.parametrize("pergunta", LEDGER)
def test_roteia_para_ledger(pergunta):
    assert route(pergunta).engine == "ledger"


@pytest.mark.llm
@pytest.mark.parametrize("pergunta", MEMORY)
def test_roteia_para_memory(pergunta):
    assert route(pergunta).engine == "memory"


@pytest.mark.llm
@pytest.mark.parametrize("pergunta", BRAIN)
def test_roteia_para_brain(pergunta):
    """Sem xfail: `route()` decide pela DESCRIÇÃO da tool, sem construir a
    engine, então o roteamento para brain já funciona antes da T12. O que
    depende da T12 é executar a consulta, não escolher a rota."""
    assert route(pergunta, brain_enabled=True).engine == "brain"


@pytest.mark.llm
def test_brain_desligado_nao_e_escolhido():
    """Com a flag desligada, a tool nem entra na lista de escolhas."""
    assert route("quais indicadores compõem a dimensão atuária").engine in ("ledger", "memory")


@pytest.mark.llm
def test_decisao_traz_justificativa():
    d = route("qual o prazo para envio do DIPR")
    assert d.reason, "a justificativa ajuda a diagnosticar erro de roteamento"
