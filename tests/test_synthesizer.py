"""T09 — síntese com citação obrigatória e recusa.

R2 e R3 deixam de ser validação de schema e viram comportamento observável.
"""

from unittest.mock import patch

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from isp_rag.query.synthesizer import (
    REFUSAL_PHRASE,
    SYNTHESIS_PROMPT,
    build_context,
    extract_sources,
    has_citation,
    is_refusal,
    synthesize,
)


def _node(texto: str, **meta) -> NodeWithScore:
    return NodeWithScore(node=TextNode(text=texto, metadata=meta), score=0.9)


NODE_ART241 = _node(
    "Art. 241. O ente federativo deverá encaminhar o DIPR até o último dia do mês.",
    norma="Portaria MTP nº 1.467/2022",
    artigo="241",
    situacao="vigente",
    url="https://gov.br/portaria#art241",
    text_raw="Art. 241. O ente federativo deverá encaminhar o DIPR...",
)
NODE_LEDGER = _node("conceito: C", ref="isp_resultado, ed. 2025")


# ---------------------------------------------------------------------------
# R3 — recusa
# ---------------------------------------------------------------------------
def test_contexto_vazio_recusa_sem_chamar_llm():
    """Sem contexto não há o que sintetizar — não gasta chamada."""
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        r = synthesize("qual a capital da Mongólia?", [], ["memory"])
        assert mock.return_value.complete.call_count == 0

    assert r.refused is True
    assert r.answer == REFUSAL_PHRASE
    assert r.sources == []


def test_recusa_do_modelo_e_detectada():
    """A frase de recusa vinda do LLM produz refused=True e sources=[] —
    prova que R2 e R3 convivem: o contrato aceita fonte vazia só aqui."""
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        mock.return_value.complete.return_value = REFUSAL_PHRASE
        r = synthesize("pergunta fora do escopo", [NODE_ART241], ["memory"])

    assert r.refused is True
    assert r.sources == []


@pytest.mark.parametrize(
    "variante",
    [
        REFUSAL_PHRASE,
        "Nao ha base na documentacao indexada para responder a essa pergunta",
        "  não há base na documentação indexada para responder a essa pergunta.  ",
        "Resposta: Não há base na documentação indexada para responder a essa pergunta.",
    ],
)
def test_is_refusal_tolera_variacoes(variante):
    assert is_refusal(variante)


def test_is_refusal_nao_confunde_resposta_real():
    assert not is_refusal("O prazo é o último dia do mês (Portaria 1.467/2022, art. 241).")


# ---------------------------------------------------------------------------
# R2 — fonte obrigatória
# ---------------------------------------------------------------------------
def test_resposta_com_contexto_tem_fonte():
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        mock.return_value.complete.return_value = (
            "O prazo é o último dia do mês (Portaria MTP 1.467/2022, art. 241)."
        )
        r = synthesize("qual o prazo do DIPR?", [NODE_ART241], ["memory"])

    assert r.refused is False
    assert r.sources
    assert "241" in r.sources[0].ref
    assert r.sources[0].engine == "memory"


def test_sem_fonte_extraivel_vira_recusa():
    """Bug do sistema não pode virar resposta sem fonte (R2)."""
    node_sem_meta = NodeWithScore(node=TextNode(text="texto solto"), score=0.5)
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        mock.return_value.complete.return_value = "Uma resposta qualquer."
        with patch("isp_rag.query.synthesizer.extract_sources", return_value=[]):
            r = synthesize("pergunta", [node_sem_meta], ["memory"])

    assert r.refused is True
    assert r.sources == []


def test_fontes_nao_duplicam():
    fontes = extract_sources([NODE_ART241, NODE_ART241, NODE_LEDGER], ["memory", "ledger"])
    assert len(fontes) == 2


@pytest.mark.parametrize(
    "resposta,esperado",
    [
        ("O prazo é 30 dias (Portaria 1.467/2022, art. 241).", True),
        ("O conceito é C (isp_resultado, ed. 2025).", True),
        ("O prazo é de 30 dias.", False),
    ],
)
def test_deteccao_de_citacao_no_corpo(resposta, esperado):
    assert has_citation(resposta) is esperado


# ---------------------------------------------------------------------------
# Contexto e ressalva
# ---------------------------------------------------------------------------
def test_contexto_identifica_as_fontes():
    ctx = build_context([NODE_ART241, NODE_LEDGER])
    assert "[FONTE 1 | Portaria MTP nº 1.467/2022, art. 241 | vigente]" in ctx
    assert "[FONTE 2 | isp_resultado, ed. 2025]" in ctx


def test_ressalva_entra_como_fonte_zero():
    """Injetada por código, não confiada ao LLM (plan.md §7.1)."""
    ctx = build_context([NODE_LEDGER], ressalva="Os resultados não são comparáveis.")
    assert ctx.startswith("[FONTE 0")
    assert "RESSALVA OBRIGATÓRIA" in ctx
    assert "não são comparáveis" in ctx


def test_sem_ressalva_nao_ha_fonte_zero():
    """Avisar onde não precisa também degrada a resposta."""
    assert "FONTE 0" not in build_context([NODE_LEDGER])


def test_ressalva_chega_ao_prompt():
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        mock.return_value.complete.return_value = "Resposta (isp_resultado, ed. 2025)."
        synthesize(
            "o conceito melhorou entre 2024 e 2025?",
            [NODE_LEDGER],
            ["ledger"],
            ressalva="A régua mudou entre as edições.",
        )
        prompt = mock.return_value.complete.call_args[0][0]

    assert "A régua mudou entre as edições." in prompt
    assert "RESSALVA OBRIGATÓRIA" in prompt


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def test_prompt_preserva_as_cinco_regras():
    for regra in ("FUNDAMENTAÇÃO", "CITAÇÃO", "PREMISSA FALSA", "VIGÊNCIA", "COMPARABILIDADE"):
        assert regra in SYNTHESIS_PROMPT, f"regra ausente: {regra}"


def test_sub_questions_preservadas():
    with patch("isp_rag.query.synthesizer.get_provider") as mock:
        mock.return_value.complete.return_value = "Resposta (Portaria 1.467/2022, art. 241)."
        r = synthesize("pergunta", [NODE_ART241], ["memory"], sub_questions=["a?", "b?"])
    assert r.sub_questions == ["a?", "b?"]


# ---------------------------------------------------------------------------
# Contra o corpus real (gasta token)
# ---------------------------------------------------------------------------
def _nodes_reais(pergunta: str, k: int = 4):
    from isp_rag.memory.engine import buscar

    return [
        NodeWithScore(
            node=TextNode(text=r.chunk.text, metadata=r.chunk.model_dump(mode="json")),
            score=r.score,
        )
        for r in buscar(pergunta, top_k=k)
    ]


@pytest.mark.llm
def test_pergunta_respondivel_cita_no_corpo():
    q = "o que estabelece o art. 241?"
    r = synthesize(q, _nodes_reais(q), ["memory"])
    assert r.refused is False
    assert r.sources and "241" in r.sources[0].ref
    assert has_citation(r.answer), "R2: a citação precisa aparecer no corpo da resposta"


@pytest.mark.llm
def test_pergunta_fora_do_escopo_recusa():
    """R3: recusar é sucesso. Melhor 'não sei' que um prazo inventado."""
    q = "Qual a capital da Mongólia?"
    r = synthesize(q, _nodes_reais(q), ["memory"])
    assert r.refused is True
    assert r.sources == []
