# plan.md — ISP-RAG

Arquitetura e regras invariantes do projeto. Este documento é a **constituição**:
`tasks.md` executa, `plan.md` decide. Nenhuma task pode violar o que está aqui.

Especificação de origem: [docs/projeto-isp-rag.md](docs/projeto-isp-rag.md)
Escopo desta versão: **Docker local até FastAPI + MCP funcionando.** Sem deploy gerenciado.

---

## 1. Regras invariantes

Estas regras não são negociáveis por conveniência de implementação. Se uma task
parecer exigir a quebra de uma delas, a task está errada — pare e reformule.

| # | Regra | Origem |
|---|---|---|
| R1 | **Procedência obrigatória.** Todo arquivo entra por download automatizado a partir da URL pública. Nenhuma cópia manual. Cada item registra URL, timestamp, tamanho e SHA-256 no manifesto. | Spec 2.4 |
| R2 | **Resposta sem fonte é erro de contrato.** `QueryResponse.sources` não pode ser vazio. Falha de validação Pydantic, não questão de estilo. | Spec 6.2 |
| R3 | **Recusar é sucesso.** Sem base no contexto recuperado, o sistema declara ausência. Nunca preenche lacuna. Um prazo inventado é pior que um "não sei". | Spec 6.3 |
| R4 | **Sem dado sintético.** Nada de Faker. Todo número vem do ISP publicado. | Spec 4.2 |
| R5 | **LLM atrás de interface trocável.** Nenhum `import openai` fora de `src/isp_rag/llm/`. | Spec 1.3 |
| R6 | **Edição é dimensão de primeira classe.** Toda tabela de fato tem `edicao_ano`. Quase toda pergunta é comparativa. | Spec 5.1 |
| R7 | **Segredos só em `.env`.** Nunca hardcoded, nunca commitado. Repositório é público. | .gitignore |

---

## 2. Stack fixada

```
LlamaIndex      orquestração: ingestão, roteamento, recuperação
Pydantic v2     contratos de entrada e saída
FastAPI         serving
PostgreSQL 16   Ledger  — notas do ISP por ente × edição
Qdrant          Memory  — corpus normativo vetorizado
Neo4j 5         Brain   — grafo de normas, critérios, indicadores
OpenAI          gpt-4o-mini (síntese) · gpt-4o (judge) · text-embedding-3-small
Docker Compose  ambiente local
MCP Server      exposição para agentes
```

**Decisão de modelos.** Provedor único (OpenAI) para reduzir superfície de
configuração. `gpt-4o-mini` na síntese porque o custo domina nas rodadas de
avaliação; `gpt-4o` apenas como judge, onde a qualidade do julgamento importa
mais que o preço. `text-embedding-3-small` (1536 dim) é suficiente para um
corpus desta ordem e mantém o custo de vetorização irrisório.

Apesar do provedor único, R5 continua valendo: a troca de provedor deve custar
um arquivo, não um refactor.

---

## 3. Estrutura de diretórios

```
rag-previdenciario/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── plan.md
├── tasks.md
├── README.md
├── docs/
│   └── projeto-isp-rag.md
├── data/
│   ├── raw/                    # ignorado; manifest.json versionado
│   │   └── manifest.json
│   └── processed/              # ignorado
├── src/isp_rag/
│   ├── config.py               # Settings (pydantic-settings)
│   ├── contracts.py            # QueryRequest, QueryResponse, Source
│   ├── llm/
│   │   ├── __init__.py         # reexporta get_provider, LLMProvider
│   │   └── provider.py         # única fronteira com OpenAI (R5)
│   ├── ingestion/
│   │   ├── fetcher.py          # download + manifesto (R1)
│   │   ├── manifest.py
│   │   ├── sources.py          # URLs públicas do ISP
│   │   ├── xlsx_parser.py      # planilhas ISP  → Ledger
│   │   └── pdf_parser.py       # relatórios/normas → Memory
│   ├── ledger/
│   │   ├── schema.sql
│   │   ├── loader.py
│   │   ├── verify.py           # recálculo × publicado (spec 2.4)
│   │   └── engine.py           # NLSQLTableQueryEngine
│   ├── memory/
│   │   ├── chunker.py          # chunk por artigo (spec 5.2)
│   │   ├── indexer.py
│   │   └── engine.py           # híbrido denso + esparso, RRF
│   ├── brain/
│   │   ├── ontology.cypher
│   │   ├── loader.py
│   │   └── engine.py           # PropertyGraphIndex
│   ├── query/
│   │   ├── router.py           # RouterQueryEngine
│   │   └── synthesizer.py      # prompt com R2 e R3
│   ├── api/
│   │   └── main.py             # FastAPI
│   └── mcp/
│       └── server.py
├── eval/
│   ├── gold_set.json           # versionado
│   ├── runners/
│   └── runs/                   # ignorado
└── tests/
```

---

## 4. Portas e serviços

| Serviço | Porta host | Variável |
|---|---|---|
| PostgreSQL | 5432 | `POSTGRES_DSN` |
| Qdrant HTTP | 6333 | `QDRANT_URL` |
| Qdrant gRPC | 6334 | — |
| Neo4j Bolt | 7687 | `NEO4J_URI` |
| Neo4j Browser | 7474 | — |
| FastAPI | 8000 | `API_PORT` |
| MCP (stdio) | — | — |

## 5. Variáveis de ambiente

```bash
# .env.example — copie para .env e preencha
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
```

---

## 6. Contratos centrais

Assinaturas que as tasks devem respeitar. Implementação detalhada fica nas tasks.

```python
# src/isp_rag/contracts.py
from typing import Literal
from datetime import date
from pydantic import BaseModel, Field, field_validator

EngineName = Literal["ledger", "memory", "brain"]

class Source(BaseModel):
    """Toda afirmação rastreia até uma destas (R2)."""
    engine: EngineName
    ref: str            # "Portaria MTP 1.467/2022, art. 241" | "isp_resultado, ed. 2025"
    url: str | None = None
    snippet: str | None = None

class QueryRequest(BaseModel):
    question: str = Field(min_length=3)
    reference_date: date | None = None   # filtro de vigência (spec 5.2)
    engines: list[EngineName] | None = None

class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    engines_used: list[EngineName]
    sub_questions: list[str] = []
    refused: bool = False

    @field_validator("sources")
    @classmethod
    def _sources_required(cls, v, info):
        # R2 + R3: ou há fonte, ou a resposta é uma recusa explícita.
        if not v and not info.data.get("refused"):
            raise ValueError("resposta sem fonte viola R2")
        return v
```

```python
# src/isp_rag/llm/provider.py — única fronteira com o provedor (R5)
class LLMProvider(Protocol):
    def complete(self, prompt: str, *, model: str | None = None) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

---

## 7. Modelo do Ledger

Chave temporal em toda tabela de fato (R6). Memória de cálculo em tabela própria,
para que o recálculo de verificação seja uma consulta, não um script (spec 2.4/5.1).

```sql
CREATE TABLE ente (
    cnpj            VARCHAR(14) PRIMARY KEY,
    nome            TEXT NOT NULL,
    uf              CHAR(2) NOT NULL,
    municipio       TEXT
);

CREATE TABLE edicao (
    ano                SMALLINT PRIMARY KEY,
    metodologia_ref    TEXT,
    url_fonte          TEXT NOT NULL,
    -- Ruptura metodológica: edições com regimes diferentes não são comparáveis
    -- entre si. O ISP-2025 foi reformulado e o Ministério declara isso
    -- explicitamente. Ver §7.1.
    regime_metodologico TEXT NOT NULL,      -- 'tercil-anual' | 'corte-historico'
    comparavel_com      SMALLINT[] NOT NULL -- anos comparáveis a este
);

CREATE TABLE isp_resultado (
    cnpj            VARCHAR(14) REFERENCES ente,
    edicao_ano      SMALLINT REFERENCES edicao,
    nota_final      NUMERIC(5,4),
    conceito        CHAR(1),           -- A..E
    PRIMARY KEY (cnpj, edicao_ano)
);

CREATE TABLE isp_componente (
    cnpj            VARCHAR(14),
    edicao_ano      SMALLINT,
    criterio        TEXT NOT NULL,
    indicador       TEXT NOT NULL,
    valor           NUMERIC,
    peso            NUMERIC,
    nota_componente NUMERIC(5,4),
    PRIMARY KEY (cnpj, edicao_ano, criterio, indicador),
    FOREIGN KEY (cnpj, edicao_ano) REFERENCES isp_resultado
);

CREATE TABLE siconfi_fiscal (      -- v1.5
    cnpj            VARCHAR(14),
    exercicio       SMALLINT,
    rcl             NUMERIC,
    payload_bruto   JSONB NOT NULL,  -- spec 2.3: sem banco de documentos
    PRIMARY KEY (cnpj, exercicio)
);
```

---

### 7.1 Ruptura metodológica de 2025 — comparabilidade

O ISP-2025 foi reformulado. O Ministério declara: *"devido às alterações na
metodologia e na composição do ISP-2025, os resultados não são comparáveis com
os obtidos nos índices dos anos anteriores"*.

O que mudou, e por que importa para o RAG:

| | Até 2024 | A partir de 2025 |
|---|---|---|
| Atribuição de conceito | **Tercil anual** — ordena os RPPS do ano e divide em três | **Cortes fixos** derivados da distribuição histórica |
| Natureza da nota | **Relativa** — depende de quem mais foi avaliado naquele ano | **Absoluta** — depende só do próprio desempenho |
| Indicadores | conjunto anterior | +3 novos (resultado financeiro da equalização do déficit atuarial; sustentabilidade atuarial sobre RCL; comprometimento atuarial da RCL) |
| Dimensões | — | 3 dimensões × 3 indicadores, pesos equilibrados |
| Porte e maturidade | medianas e percentis | agrupamentos reais na distribuição |

**A armadilha.** A letra do conceito é a mesma (A, B, C) e o tipo da coluna é o
mesmo. Nada no dado sinaliza a ruptura. Um `SELECT` que compara 2024 com 2025
roda sem erro e devolve um delta — que **não significa mudança de desempenho**.

Um ente pode "cair" de B para C sem ter piorado em nada: mudou a régua. E o
inverso também. Essa é exatamente a pergunta de demonstração da spec §3.4 — só
que agora sabemos que ela é real, não hipotética.

**Regra derivada (vale para T04, T05, T08, T11):**

> Toda resposta que compare edições de regimes metodológicos diferentes **deve
> declarar a ruptura**. Apresentar o delta sem a ressalva é um erro de fidelidade
> tão grave quanto inventar um prazo — e mais perigoso, porque parece correto.

Implementação: `edicao.regime_metodologico` e `edicao.comparavel_com` carregam a
informação; o prompt de síntese (T09) checa se as edições citadas pertencem ao
mesmo regime e, se não, antepõe a ressalva.

---

## 8. Ontologia do Brain

Schema completo desde o início, carga incremental (spec 5.3).

```
Nós:     Norma · Dispositivo · Edicao · Criterio · Indicador · Ente
Arestas: REVOGA · ALTERA · REGULAMENTA · FUNDAMENTA · COMPOE · CONSOME_CAMPO
```

Carga v2 cobre `Edicao → COMPOE → Criterio → COMPOE → Indicador`.
Cadeia normativa e linhagem `Dispositivo → CONSOME_CAMPO → Indicador` vêm depois.

---

## 9. Roteamento

| Pergunta | Engine |
|---|---|
| "Qual a nota do RPPS de X em 2025?" | ledger |
| "O que a Portaria 1.467 exige sobre DIPR?" | memory |
| "Que critério mudou entre 2023 e 2025?" | brain |
| Cruzada (spec 3.4) | SubQuestion → todas |

`RouterQueryEngine` para domínio único; `SubQuestionQueryEngine` quando a
pergunta cruza domínios. O acerto do roteador é **medido**, não presumido.

---

## 10. Definition of Done

Uma task só está concluída quando:

1. Roda com `docker compose up` limpo, a partir de `.env.example`.
2. Não viola nenhuma regra de §1.
3. Tem teste que cobre o caminho feliz e o caminho de recusa quando aplicável.
4. Não introduz `import openai` fora de `src/isp_rag/llm/`.
5. Nenhum dado baixado foi commitado — apenas o manifesto.
