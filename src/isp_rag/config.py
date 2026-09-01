"""Configuração do ISP-RAG, lida do `.env` (R7: segredos nunca no código)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação.

    Instanciar sem um `.env` (ou sem OPENAI_API_KEY) levanta ValidationError.
    Isso é intencional: falhar no import, com mensagem clara, é melhor do que
    falhar no meio de uma ingestão de 3,5 MB.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM e embeddings — consumidos apenas por src/isp_rag/llm/ (R5)
    openai_api_key: str
    llm_model: str = "gpt-4o-mini"
    judge_model: str = "gpt-4o"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536

    # Ledger / Memory / Brain
    postgres_dsn: str
    qdrant_url: str
    qdrant_collection: str = "isp_normas"
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # Serving e ambiente
    api_port: int = 8000
    data_dir: Path = Path("./data")
    log_level: str = "INFO"

    @property
    def raw_dir(self) -> Path:
        """Onde a ingestão grava os arquivos baixados e o manifesto (R1)."""
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


settings = Settings()
