"""T01 — o scaffold carrega e os defaults do plan.md §5 estão corretos."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from isp_rag.config import Settings, settings

REQUIRED_ENV = {
    "OPENAI_API_KEY": "sk-test",
    "POSTGRES_DSN": "postgresql://isp:isp@localhost:5432/isp_rag",
    "QDRANT_URL": "http://localhost:6333",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "isp_local_dev",
}


def _isolated(monkeypatch, **overrides):
    """Settings sem herdar o .env do projeto nem o ambiente do shell."""
    for key in list(REQUIRED_ENV) + ["LLM_MODEL", "JUDGE_MODEL", "EMBED_MODEL", "EMBED_DIM"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**REQUIRED_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_defaults_de_modelo(monkeypatch):
    """Os modelos fixados em plan.md §2 são o default — não podem derivar."""
    s = _isolated(monkeypatch)
    assert s.llm_model == "gpt-4o-mini"
    assert s.judge_model == "gpt-4o"
    assert s.embed_model == "text-embedding-3-small"
    assert s.embed_dim == 1536


def test_campo_obrigatorio_ausente_falha(monkeypatch):
    """Sem OPENAI_API_KEY, falha no import — não no meio de uma ingestão."""
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_sobrescreve_default(monkeypatch):
    s = _isolated(monkeypatch, LLM_MODEL="gpt-4o")
    assert s.llm_model == "gpt-4o"


def test_diretorios_derivados():
    """raw_dir e processed_dir saem de data_dir, sem caminho hardcoded."""
    assert settings.raw_dir == settings.data_dir / "raw"
    assert settings.processed_dir == settings.data_dir / "processed"
    assert isinstance(settings.data_dir, Path)


def test_pacotes_importaveis():
    """A árvore de plan.md §3 existe e é importável."""
    for mod in ("llm", "ingestion", "ledger", "memory", "brain", "query", "api", "mcp"):
        __import__(f"isp_rag.{mod}")
