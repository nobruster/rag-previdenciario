"""Contratos de entrada e saída do ISP-RAG.

R2 — resposta sem fonte é erro de contrato, não questão de estilo.
R3 — a única exceção é a recusa explícita.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EngineName = Literal["ledger", "memory", "brain"]


class Source(BaseModel):
    """Toda afirmação factual rastreia até uma destas."""

    engine: EngineName
    ref: str = Field(min_length=1)
    """Identificação citável: "Portaria MTP 1.467/2022, art. 241"
    ou "isp_resultado, ed. 2025"."""

    url: str | None = None
    snippet: str | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)

    reference_date: date | None = None
    """Data de referência para o filtro de vigência (spec §5.2)."""

    engines: list[EngineName] | None = None
    """Força engines específicas. None = deixa o roteador decidir."""


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    engines_used: list[EngineName]
    sub_questions: list[str] = []
    refused: bool = False

    @model_validator(mode="after")
    def _sources_required(self) -> "QueryResponse":
        """R2 + R3: ou há fonte, ou a resposta é uma recusa explícita.

        Usa `model_validator(mode="after")` em vez de `field_validator` porque
        a checagem cruza dois campos. Um field_validator em `sources` só
        enxergaria `refused` via `info.data`, que na v2 contém apenas os campos
        já validados — e `refused` é declarado depois. A validação silenciosa
        passaria a depender da ordem de declaração dos campos.
        """
        if not self.sources and not self.refused:
            raise ValueError(
                "resposta sem fonte viola R2: toda afirmação precisa citar "
                "dispositivo normativo ou tabela+edição"
            )
        return self
