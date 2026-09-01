# CLAUDE.md — ISP-RAG

Contrato do projeto. Leia antes de qualquer task.

Documentos que este arquivo NÃO repete — consulte-os direto:
[plan.md](plan.md) (arquitetura, schema, contratos) · [prompts/](prompts/) (as
13 tasks) · [docs/projeto-isp-rag.md](docs/projeto-isp-rag.md) (especificação).

## O que é

RAG multi-fonte sobre a previdência pública brasileira. Ingere os resultados
públicos do ISP-RPPS (Ministério da Previdência Social) mais as portarias e
notas técnicas que os regulamentam.

Três camadas, porque a natureza da pergunta decide a fonte do contexto:

| Camada | Tech | Responde |
|---|---|---|
| **Ledger** | PostgreSQL + Text-to-SQL | "qual a nota do RPPS de X em 2025" |
| **Memory** | Qdrant, denso + esparso | "o que a norma exige" |
| **Brain** | Neo4j | "o que mudou entre edições e por quê" |

Serving em FastAPI, consumo por agentes via MCP.

## Regras invariantes

Justificativa completa em [plan.md](plan.md) §1. Se uma task parecer exigir a
quebra de uma delas, **a task está errada** — pare e reformule.

| # | Regra |
|---|---|
| **R1** | Arquivo entra por download de URL pública, com manifesto (URL, timestamp, tamanho, SHA-256). Nenhuma cópia manual. |
| **R2** | `QueryResponse.sources` vazio é erro de contrato, exceto em recusa. |
| **R3** | Sem base no contexto, o sistema recusa. Nunca preenche lacuna. |
| **R4** | Sem dado sintético. Nada de Faker. |
| **R5** | `import openai` só em `src/isp_rag/llm/provider.py`. |
| **R6** | `edicao_ano` em toda tabela de fato. |
| **R7** | Segredos só em `.env`. O repositório é público. |

## Padrões

- Python 3.11+, layout `src/`, `pyproject.toml` (nunca `requirements.txt`)
- Type hints obrigatórios; docstring em função e classe pública
- `ruff`, line-length 100
- `temperature=0` em toda chamada de LLM — este sistema não é criativo
- Toda saída de LLM passa por modelo Pydantic; nunca string crua
- Text-to-SQL e text-to-Cypher são **somente leitura**, com guarda explícita
- Domínio em português (`ente`, `edicao`, `nota_final`, `criterio`) — são termos
  da fonte oficial, traduzir cria ambiguidade na hora de citar a norma.
  Infraestrutura em inglês.

## Testes

- `pytest`. Mock de serviços externos — nunca faça rede em teste
- Text-to-SQL: asserte sobre o **resultado da execução**, nunca sobre a string
  do SQL. Dois SQLs diferentes podem estar ambos corretos
- `tests/test_r5_boundary.py` varre `src/` e falha se R5 for violada
- Avaliação é outra coisa: gold set e métricas vivem em `eval/` e medem
  qualidade (roteamento, recuperação, geração), não corretude de código

## Fluxo

- Uma task por vez, do arquivo correspondente em [prompts/](prompts/)
- Ao concluir: rode a **Validação** e confira o **Aceite** do arquivo da task
- **Não avance sem confirmação explícita**
- Relate desvios do prompt e o motivo

## Proibido

- LangChain (é LlamaIndex), ChromaDB ou FAISS (é Qdrant)
- **Chunking por N tokens** sobre texto normativo — quebra a âncora citável.
  É chunk por artigo (spec §5.2)
- Nome de modelo hardcoded — vem de `.env`
- URL de fonte inventada. Sem a URL real, deixe `TODO` explícito
- MongoDB e data lake S3/MinIO — cortados deliberadamente (spec §4.2)
- Frontend nesta fase; API e MCP são a interface

## Escopo

Docker local até FastAPI + MCP (T01–T13). Fora: SICONFI (v1.5), cadeia
normativa completa no grafo (v2+), UI TypeScript (v3), deploy gerenciado.
