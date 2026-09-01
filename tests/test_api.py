"""T10 — camada de serving. Fecha a v0."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from isp_rag.api.main import app
from isp_rag.query.router import RouteDecision


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Validação de entrada — erro do cliente é 422
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("body", [{"question": ""}, {"question": "ab"}, {"question": "x" * 2001}])
def test_pergunta_invalida_e_422(client, body):
    assert client.post("/query", json=body).status_code == 422


def test_engine_inexistente_e_422(client):
    r = client.post("/query", json={"question": "qual a nota?", "engines": ["postgres"]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Health e sources
# ---------------------------------------------------------------------------
def test_health_checa_os_tres_servicos(client):
    r = client.get("/health")
    assert r.status_code == 200
    servicos = r.json()["services"]
    assert set(servicos) == {"postgres", "qdrant", "neo4j"}


def test_health_reporta_neo4j(client):
    """Depois da T12 o Brain está ativo; antes dela, 'disabled' — nunca 'erro'."""
    estado = client.get("/health").json()["services"]["neo4j"]
    assert estado in ("ok", "disabled"), estado


def test_sources_ledger_lista_edicoes_com_regime(client):
    dados = client.get("/sources/ledger").json()
    assert dados["engine"] == "ledger"
    assert dados["edicoes"], "nenhuma edição carregada"
    e = dados["edicoes"][0]
    assert {"ano", "regime", "n_entes", "url_fonte"} <= set(e)
    assert e["regime"] in ("tercil-anual", "corte-historico")


def test_sources_memory_reporta_situacao(client):
    dados = client.get("/sources/memory").json()
    assert dados["total_chunks"] > 600
    assert "vigente" in dados["situacao"]


def test_sources_brain(client):
    dados = client.get("/sources/brain").json()
    assert dados["status"] in ("ok", "disabled")
    if dados["status"] == "ok":
        assert dados["nos"]["Criterio"] == 3
        assert dados["nos"]["Indicador"] == 9


# ---------------------------------------------------------------------------
# R2 — violação de contrato é 500, não 4xx
# ---------------------------------------------------------------------------
def _violacao_real() -> ValidationError:
    """A ValidationError que o próprio contrato levanta — não uma fabricada."""
    from isp_rag.contracts import QueryResponse

    try:
        QueryResponse(answer="resposta sem fonte", sources=[], engines_used=["memory"])
    except ValidationError as exc:
        return exc
    raise AssertionError("R2 deveria ter falhado")


def test_violacao_de_contrato_e_erro_do_sistema(client):
    """Um 4xx faria o cliente achar que a pergunta dele estava errada.

    A recuperação também é mockada: o alvo aqui é o handler de erro, e deixar
    a busca real rodar faria o teste depender de chave de LLM válida — ele
    quebrava em CI por um motivo que não é o que ele mede.
    """
    with (
        patch("isp_rag.api.main.synthesize", side_effect=_violacao_real()),
        patch("isp_rag.api.main._nodes_do_memory", return_value=[]),
        patch("isp_rag.api.main.route", return_value=RouteDecision(engine="memory")),
    ):
        r = client.post("/query", json={"question": "qual o prazo do DIPR?"})
    assert r.status_code == 500
    assert r.json()["error"] == "contract_violation"


# ---------------------------------------------------------------------------
# Fluxo completo (gasta token)
# ---------------------------------------------------------------------------
@pytest.mark.llm
def test_pergunta_numerica_usa_ledger(client):
    d = client.post("/query", json={"question": "Quantos entes tiveram conceito A em 2025?"}).json()
    assert d["engines_used"] == ["ledger"]
    assert d["sources"] and not d["refused"]
    assert "32" in d["answer"]


@pytest.mark.llm
def test_pergunta_normativa_usa_memory(client):
    d = client.post("/query", json={"question": "o que estabelece o art. 241?"}).json()
    assert d["engines_used"] == ["memory"]
    assert d["sources"] and "241" in d["sources"][0]["ref"]


@pytest.mark.llm
def test_fora_do_escopo_recusa_com_200(client):
    """R3: recusar é sucesso, não erro HTTP."""
    r = client.post("/query", json={"question": "Qual a capital da Mongólia?"})
    assert r.status_code == 200
    d = r.json()
    assert d["refused"] is True
    assert d["sources"] == []


@pytest.mark.llm
def test_engines_forcadas_sao_respeitadas(client):
    d = client.post(
        "/query", json={"question": "conceito de Campinas em 2025", "engines": ["ledger"]}
    ).json()
    assert d["engines_used"] == ["ledger"]


@pytest.mark.llm
def test_toda_resposta_nao_recusada_tem_fonte(client):
    """R2 no nível da API: o contrato não deixa passar resposta sem fonte."""
    for q in ["Quantos entes tiveram conceito A em 2025?", "o que estabelece o art. 241?"]:
        d = client.post("/query", json={"question": q}).json()
        assert d["refused"] or d["sources"], f"resposta sem fonte para: {q}"


# ---------------------------------------------------------------------------
# Cobertura — o que o sistema pode responder
# ---------------------------------------------------------------------------
def test_cobertura_termo_ausente(client):
    d = client.get("/cobertura", params={"termo": "Mongólia"}).json()
    assert d["coberto"] is False and d["n_chunks"] == 0


def test_cobertura_termo_presente(client):
    d = client.get("/cobertura", params={"termo": "CRP"}).json()
    assert d["coberto"] is True and d["artigos"]
