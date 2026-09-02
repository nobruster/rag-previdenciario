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

## Estado conhecido

O que está carregado hoje, para não confundir lacuna de dado com bug:

- **Ledger**: só a edição **2025** (2.133 entes, regime `corte-historico`).
  Pergunta sobre 2017–2024 não tem resposta — a tool devolve
  `ente_nao_encontrado`, e isso é R3 funcionando.
- **Memory**: só o corpus **normativo** — Portaria MTP 1.467/2022, Leis
  9.717/1998 e 10.887/2004, Emendas. Os relatórios técnicos do ISP
  (`rt_diaq_002_2025`, `rt_diaq_013_2025`, relatório 2025) estão baixados em
  `data/raw/` mas **não indexados**.

A consequência é uma lacuna estrutural: o sistema tem a **norma** e tem o
**resultado**, e não tem a **metodologia** que liga um ao outro. Perguntas do
tipo "o que mede o indicador X" ou "quais os cortes de cada letra" não têm base
no corpus. A Portaria art. 238 delega a metodologia à SPREV, que a publica à
parte. Indexar aqueles três PDFs fecha isso — mas chunk por artigo (spec §5.2)
não serve para relatório técnico, que não tem artigos; precisa de estratégia
por seção.

## Falhas conhecidas

Achadas exercitando o sistema pelo MCP. Todas reproduzidas. Candidatas ao gold
set em `eval/` — nenhuma corrigida ainda.

| # | Falha |
|---|---|
| **F1** | **Text-to-SQL fabrica recorte para casar com a pergunta.** "Quais os 3 indicadores novos do ISP-2025" → gera `SELECT DISTINCT indicador ... ORDER BY indicador LIMIT 3` e apresenta as 3 primeiras em ordem alfabética como se fossem as novas. `refused: false`. O Ledger não tem coluna que marque indicador novo, e sem 2024 carregado não há diff possível — a pergunta é irrespondível e deveria ser recusada. É a falha mais perigosa do componente: o SQL executa sem erro e o resultado parece plausível. |
| **F2** | **Roteamento manda pergunta de metodologia para o Ledger.** A mesma pergunta de F1 é sobre metodologia (Memory), não sobre fato numérico. O roteador escolheu `ledger` e o sintetizador aceitou. |
| **F3** | **`verificar_cobertura` falha com sinônimo e nome por extenso.** `"ISP"` → coberto, 12 chunks. `"Indicador de Situação Previdenciária"` → ausente, 0. `"suficiencia financeira"` → ausente, 0, mesmo com o conceito presente nos arts. 7º e 61. Busca literal, sem expansão de sigla nem normalização. Um agente conclui "não coberto" e desiste de pergunta respondível. |
| **F4** | **Sinal de fabricação existe mas não bloqueia.** O sintetizador loga `WARNING: resposta sem citação no corpo` exatamente nos casos de F1 — e devolve a resposta assim mesmo. O gancho para transformar F1 em recusa já está lá. |

Ao mexer nesses pontos: R3 é o critério. Recusa é resposta correta, não
degradação de qualidade.

## Registro MCP

`.mcp.json` está no repo com caminhos **absolutos da máquina do Bruno** —
`command` (python.exe), `cwd` e `PYTHONPATH`. Em outra máquina, ajuste os três.
`claude mcp add` não tem flag `--cwd`, e sem `cwd` absoluto o servidor sobe do
diretório errado e não acha o pacote. Servidor de escopo project exige aprovação
interativa (`claude`) antes de as tools ficarem chamáveis.
