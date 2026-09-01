# T01 — Scaffold e Docker Compose

**Depende de:** nada · **Paralelo com:** nada · **Saída:** projeto que sobe com `docker compose up`

## Contexto

Primeira task. O repositório hoje tem apenas `docs/`, `plan.md`, `tasks.md`,
`README.md` e `.gitignore`. Nenhum código Python ainda.

---

## PROMPT

````
Você vai criar o esqueleto do projeto ISP-RAG: um sistema RAG multi-fonte sobre
a previdência pública brasileira, com três camadas (PostgreSQL, Qdrant, Neo4j).
Esta task não implementa lógica — cria a fundação sobre a qual as 12 tasks
seguintes constroem.

## Entregáveis

### 1. pyproject.toml

Python >=3.11, build via setuptools, pacote em src/isp_rag.

Dependências:
  llama-index-core>=0.11
  llama-index-llms-openai
  llama-index-embeddings-openai
  llama-index-vector-stores-qdrant
  llama-index-graph-stores-neo4j
  fastapi
  uvicorn[standard]
  pydantic>=2.7
  pydantic-settings
  psycopg[binary]
  sqlalchemy>=2
  qdrant-client
  neo4j
  httpx
  openpyxl
  pypdf

[project.optional-dependencies] dev: pytest, pytest-cov, ruff

Configure ruff: line-length 100, target py311.
Configure pytest: testpaths=["tests"], pythonpath=["src"].

### 2. docker-compose.yml

Três serviços, com healthcheck em cada um e volumes nomeados:

  postgres:
    image: postgres:16
    environment: POSTGRES_USER=isp, POSTGRES_PASSWORD=isp, POSTGRES_DB=isp_rag
    ports: 5432:5432
    volume: pgdata:/var/lib/postgresql/data
    healthcheck: pg_isready -U isp -d isp_rag  (interval 5s, retries 10)

  qdrant:
    image: qdrant/qdrant:latest
    ports: 6333:6333 e 6334:6334
    volume: qdrant_storage:/qdrant/storage
    healthcheck: checagem HTTP na porta 6333

  neo4j:
    image: neo4j:5
    environment: NEO4J_AUTH=neo4j/isp_local_dev
                 NEO4J_PLUGINS=["apoc"]
    ports: 7474:7474 e 7687:7687
    volumes: neo4j_data:/data, neo4j_logs:/logs
    healthcheck: cypher-shell "RETURN 1"

IMPORTANTE: a API FastAPI NÃO entra no compose. Ela roda local via uvicorn,
para iteração rápida durante o desenvolvimento.

Os nomes de volume (pgdata, qdrant_storage, neo4j_data, neo4j_logs) importam:
o .gitignore do projeto já os ignora.

### 3. .env.example

Exatamente este conteúdo:

  OPENAI_API_KEY=sk-...

  LLM_MODEL=gpt-4o-mini
  JUDGE_MODEL=gpt-4o
  EMBED_MODEL=text-embedding-3-small
  EMBED_DIM=1536

  POSTGRES_DSN=postgresql://isp:isp@localhost:5432/isp_rag
  QDRANT_URL=http://localhost:6333
  QDRANT_COLLECTION=isp_normas
  NEO4J_URI=bolt://localhost:7687
  NEO4J_USER=neo4j
  NEO4J_PASSWORD=isp_local_dev

  API_PORT=8000
  DATA_DIR=./data
  LOG_LEVEL=INFO

### 4. src/isp_rag/config.py

  from pydantic_settings import BaseSettings, SettingsConfigDict

  class Settings(BaseSettings):
      model_config = SettingsConfigDict(
          env_file=".env", env_file_encoding="utf-8", extra="ignore"
      )
      openai_api_key: str
      llm_model: str = "gpt-4o-mini"
      judge_model: str = "gpt-4o"
      embed_model: str = "text-embedding-3-small"
      embed_dim: int = 1536
      postgres_dsn: str
      qdrant_url: str
      qdrant_collection: str = "isp_normas"
      neo4j_uri: str
      neo4j_user: str
      neo4j_password: str
      api_port: int = 8000
      data_dir: Path = Path("./data")
      log_level: str = "INFO"

  settings = Settings()

Nota: `settings` no import falha se .env não existir. Isso é intencional —
falhar cedo e com mensagem clara é melhor que falhar no meio da ingestão.

### 5. Árvore de diretórios

Crie com __init__.py nos pacotes e .gitkeep nos diretórios de dados:

  src/isp_rag/
    __init__.py, config.py
    llm/__init__.py
    ingestion/__init__.py
    ledger/__init__.py
    memory/__init__.py
    brain/__init__.py
    query/__init__.py
    api/__init__.py
    mcp/__init__.py
  data/raw/.gitkeep
  data/processed/.gitkeep
  eval/runners/.gitkeep
  tests/__init__.py
  tests/fixtures/.gitkeep

### 6. Makefile (ou tasks.ps1 no Windows)

Alvos: up, down, logs, test, lint, api

## Restrições

- NENHUM segredo hardcoded em qualquer arquivo (R7). O .env real nunca é
  commitado; apenas .env.example.
- Não crie ainda os módulos de lógica (fetcher, chunker, engines) — são das
  tasks seguintes. Apenas os __init__.py vazios.

## Validação

Ao terminar, estes comandos devem passar:

  docker compose up -d
  docker compose ps          # 3 serviços "healthy"
  pip install -e ".[dev]"
  cp .env.example .env       # e preencher OPENAI_API_KEY
  python -c "from isp_rag.config import settings; print(settings.llm_model)"
  ruff check src/

Relate qualquer serviço que não fique healthy, com o log do healthcheck.
````

---

## Validação

```bash
docker compose up -d && docker compose ps
python -c "from isp_rag.config import settings; print(settings.llm_model)"
ruff check src/
```

## Aceite

- [ ] `docker compose ps` mostra postgres, qdrant e neo4j **healthy**
- [ ] `settings` carrega do `.env` sem erro
- [ ] `.env` **não** aparece em `git status`
- [ ] Nenhum segredo em `.env.example` (apenas placeholders)
- [ ] `ruff check src/` limpo
