"""T02 — os contratos fazem R2 e R3 falharem em runtime, não no code review."""

from datetime import date

import pytest
from pydantic import ValidationError

from isp_rag.contracts import QueryRequest, QueryResponse, Source

ART_241 = Source(
    engine="memory",
    ref="Portaria MTP 1.467/2022, art. 241",
    url="https://www.gov.br/exemplo#art241",
)


def test_resposta_sem_fonte_e_erro_de_contrato():
    """R2: sources vazio sem recusa não passa na validação."""
    with pytest.raises(ValidationError, match="R2"):
        QueryResponse(answer="O prazo é de 30 dias.", sources=[], engines_used=["memory"])


def test_recusa_dispensa_fonte():
    """R3: recusar é sucesso — é o único caso em que sources pode ser vazio."""
    r = QueryResponse(
        answer="Não há base na documentação indexada para responder a essa pergunta.",
        sources=[],
        engines_used=["memory"],
        refused=True,
    )
    assert r.refused
    assert r.sources == []


def test_resposta_com_fonte_preserva_ref():
    r = QueryResponse(answer="O prazo é de 30 dias.", sources=[ART_241], engines_used=["memory"])
    assert not r.refused
    assert r.sources[0].ref == "Portaria MTP 1.467/2022, art. 241"
    assert r.sources[0].engine == "memory"


def test_ordem_dos_campos_nao_afeta_validacao():
    """A checagem cruza sources e refused; não pode depender da ordem em que
    os campos são passados nem da ordem de declaração no modelo."""
    payload = {
        "refused": True,
        "engines_used": ["ledger"],
        "sources": [],
        "answer": "Não há base na documentação indexada para responder a essa pergunta.",
    }
    assert QueryResponse(**payload).refused


def test_source_exige_ref_nao_vazia():
    """Fonte sem identificação citável é o mesmo que não ter fonte."""
    with pytest.raises(ValidationError):
        Source(engine="ledger", ref="")


def test_pergunta_curta_demais():
    with pytest.raises(ValidationError):
        QueryRequest(question="ab")


def test_pergunta_longa_demais():
    with pytest.raises(ValidationError):
        QueryRequest(question="x" * 2001)


def test_request_com_data_de_referencia():
    q = QueryRequest(question="Qual a nota do RPPS em 2025?", reference_date=date(2024, 1, 1))
    assert q.reference_date == date(2024, 1, 1)
    assert q.engines is None


def test_engine_invalida_rejeitada():
    with pytest.raises(ValidationError):
        QueryRequest(question="Qual a nota?", engines=["postgres"])
