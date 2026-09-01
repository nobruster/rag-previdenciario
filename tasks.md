# tasks.md — ISP-RAG

Índice das tasks e suas dependências. **Leia [plan.md](plan.md) antes de qualquer
task** — as regras R1–R7 valem para todas.

> **Para executar, use [prompts/](prompts/).** Cada task tem lá um arquivo
> expandido e autocontido (contexto, prompt, validação e critério de aceite),
> pronto para copiar direto no agente. Os blocos deste arquivo são a versão
> resumida, útil para ter a visão geral.

**Escopo:** v0 completo + fatias de v1/v2 até MCP local. Sem deploy gerenciado.

## Ordem de execução

```
T01 ─┬─ T02 ── T03 ─┬─ T04 ── T05 ─┬─ T08 ── T09 ── T10 ─┬─ T12 ── T13
     │              │              │                     │
     └─ (setup)     └─ T06 ── T07 ─┘                     └─ T11
                       (paralelo com T04/T05)
```

| Task | Depende de | Paralelizável |
|---|---|---|
| T00 Memória do projeto (`CLAUDE.md`) | — | — |
| T01 Scaffold + Compose | T00 | — |
| T02 Contratos + provider | T01 | ‖ com T03 |
| T03 Coleta + manifesto | T01 | ‖ com T02 |
| T04 Ledger: schema + carga | T03 | ‖ com T06 |
| T05 Ledger: Text-to-SQL | T04 | — |
| T06 Memory: chunking | T03 | ‖ com T04 |
| T07 Memory: índice híbrido | T06 | — |
| T08 Roteador | T05, T07 | — |
| T09 Síntese + recusa | T08 | — |
| T10 FastAPI `/query` | T09 | — |
| T11 Gold set + métricas | T10 | ‖ com T12 |
| T12 Brain: ontologia | T10 | ‖ com T11 |
| T13 MCP Server | T10 | — |

---

## T01 — Scaffold e Docker Compose

```
Leia plan.md (§3 estrutura, §4 portas, §5 env) e crie o esqueleto do projeto.

Entregas:
1. pyproject.toml — Python 3.11+, deps: llama-index-core, llama-index-llms-openai,
   llama-index-embeddings-openai, llama-index-vector-stores-qdrant,
   llama-index-graph-stores-neo4j, fastapi, uvicorn, pydantic>=2, pydantic-settings,
   psycopg[binary], sqlalchemy, qdrant-client, neo4j, httpx, openpyxl, pypdf,
   pytest, ruff. Dev extra: pytest-cov.
2. docker-compose.yml com os 3 serviços, portas de §4, healthcheck em cada um
   e volumes nomeados:
     postgres:16   POSTGRES_USER/PASSWORD/DB = isp/isp/isp_rag
     qdrant/qdrant:latest
     neo4j:5       NEO4J_AUTH=neo4j/isp_local_dev, plugins APOC
3. .env.example exatamente como §5 do plan.md.
4. src/isp_rag/config.py — classe Settings(BaseSettings) lendo .env, com todos
   os campos de §5 tipados. Instância singleton `settings`.
5. Árvore de diretórios de §3 com __init__.py e .gitkeep onde couber.

Restrições:
- A API NÃO entra no compose (roda local via uvicorn para iteração rápida).
- Nenhum segredo hardcoded (R7).

Valide: `docker compose up -d` sobe os 3 serviços saudáveis;
`python -c "from isp_rag.config import settings; print(settings.llm_model)"` funciona.
```

---

## T02 — Contratos Pydantic e provider de LLM

```
Leia plan.md §6. Implemente a camada de contratos e a fronteira com o provedor.

1. src/isp_rag/contracts.py — Source, QueryRequest, QueryResponse, EngineName
   exatamente com as assinaturas de §6, incluindo o validator que implementa R2/R3.
2. src/isp_rag/llm/provider.py:
   - Protocol LLMProvider (complete, embed)
   - OpenAIProvider implementando-o, lendo settings; usa LLM_MODEL por padrão e
     aceita override por chamada (para o judge usar JUDGE_MODEL)
   - factory get_provider() -> LLMProvider
3. src/isp_rag/llm/__init__.py reexportando apenas get_provider e LLMProvider.
4. tests/test_contracts.py:
   - QueryResponse com sources=[] e refused=False → ValidationError
   - QueryResponse com sources=[] e refused=True  → válido
   - QueryResponse com 1 Source → válido

REGRA CRÍTICA (R5): `import openai` só pode aparecer em llm/provider.py.
Adicione tests/test_r5_boundary.py que varre src/ e falha se encontrar em
qualquer outro arquivo.
```

---

## T03 — Coleta com manifesto de procedência

```
Leia plan.md §1 (R1) e docs/projeto-isp-rag.md §2.4. Esta é a task mais sensível
do projeto: é ela que garante que o repositório pode ser público.

1. src/isp_rag/ingestion/manifest.py:
   - ManifestEntry(BaseModel): url, filename, fetched_at (datetime UTC),
     size_bytes, sha256, content_type
   - Manifest: load/append/save em data/raw/manifest.json, idempotente por sha256
2. src/isp_rag/ingestion/fetcher.py:
   - fetch(url: str, dest_dir: Path) -> ManifestEntry
     baixa via httpx (stream, timeout 60s, 3 retries com backoff), calcula SHA-256
     durante o stream, grava o arquivo, registra no manifesto.
     Se o sha256 já existe no manifesto, NÃO rebaixa — retorna a entrada existente.
   - fetch_all(urls: list[str], dest_dir) -> list[ManifestEntry]
3. src/isp_rag/ingestion/sources.py — constante ISP_SOURCES: list[str] com as URLs
   das páginas do ISP. Deixe TODO explícito para preencher com as URLs reais do
   gov.br/previdencia; NÃO invente URLs.
4. CLI: `python -m isp_rag.ingestion.fetch_isp --year 2025`
5. tests/test_manifest.py com httpx mockado: verifica sha256, idempotência e
   que o manifesto é escrito corretamente.

PROIBIDO: qualquer caminho de código que aceite arquivo por cópia manual (R1).
A única porta de entrada é fetch() a partir de URL pública.
```

---

## T04 — Ledger: schema e carga das planilhas

```
Leia plan.md §7. Implemente o Ledger.

1. src/isp_rag/ledger/schema.sql — DDL exatamente como §7 do plan.md.
   Índices em (edicao_ano), (uf), (cnpj, edicao_ano).
2. src/isp_rag/ledger/loader.py:
   - init_schema(dsn) — executa o DDL, idempotente
   - load_edicao(xlsx_path, ano, url_fonte) — lê a planilha com openpyxl,
     normaliza CNPJ (só dígitos, zero-padded 14), popula ente, edicao,
     isp_resultado e isp_componente numa única transação
   - Colunas da planilha variam entre edições: implemente um dict de mapeamento
     COLUMN_MAP por ano e falhe explicitamente se a edição não estiver mapeada.
     NÃO adivinhe colunas silenciosamente.
3. src/isp_rag/ledger/verify.py:
   - recalcular(cnpj, ano) -> tuple[Decimal, Decimal]  # (recalculado, publicado)
     Soma ponderada de isp_componente e compara com isp_resultado.nota_final.
     É a checagem de qualidade da spec §2.4.
   - CLI: `python -m isp_rag.ledger.verify --year 2025 --tolerance 0.001`
     imprime tabela de divergências.
4. CLI de carga: `python -m isp_rag.ledger.load --year 2025`
5. tests/test_ledger_loader.py com fixture XLSX pequena em tests/fixtures/.

R6: edicao_ano em toda tabela de fato. R4: nenhum dado inventado — se a planilha
não trouxer um campo, ele fica NULL.
```

---

## T05 — Ledger: engine Text-to-SQL

```
Depende de T04. Leia plan.md §9.

1. src/isp_rag/ledger/engine.py:
   - build_ledger_engine() -> NLSQLTableQueryEngine do LlamaIndex
   - SQLDatabase sobre as 4 tabelas, com include_tables explícito
   - Descrições de tabela ricas no prompt de contexto (o modelo precisa saber que
     conceito é A..E, que edicao_ano é a chave temporal, que CNPJ tem 14 dígitos)
   - LLM vindo de get_provider() (R5), temperature=0
2. Exponha get_sql(response) para extrair o SQL gerado dos metadados — T11 vai
   precisar disso para medir execution match.
3. tests/test_ledger_engine.py contra o Postgres do compose, com 3 perguntas:
   - "Qual a nota do RPPS de <município> em 2025?"
   - "Quantos entes tiveram conceito A em 2025?"
   - "Qual a média das notas por UF em 2025?"
   Asserte sobre o RESULTADO da execução, nunca sobre a string do SQL.
```

---

## T06 — Memory: chunking por artigo

```
Leia docs/projeto-isp-rag.md §5.2 na íntegra. É a decisão que mais impacta
qualidade final — não simplifique para chunk de N tokens.

1. src/isp_rag/memory/chunker.py:
   - ArticleChunk(BaseModel): text, norma, numero, data_norma, orgao,
     titulo, capitulo, secao, artigo, situacao (vigente|revogado|alterado),
     data_inicio_vigencia, data_fim_vigencia, url, ancora
   - chunk_norma(texto: str, meta: dict) -> list[ArticleChunk]
     Um chunk por artigo: caput + parágrafos + incisos + alíneas juntos.
     Regex para "Art. N" tolerante a "Art. 1º", "Art. 1o", "Artigo 1".
   - O campo `text` indexado DEVE ser prefixado com a hierarquia:
     "TÍTULO II > CAPÍTULO III > Seção I > Art. 241\n\n<texto do artigo>"
     Isso resolve o artigo que diz "o prazo de que trata o caput" sem nomear
     o assunto.
   - Artigo > 1500 tokens vira sub-chunks que REPETEM o caput como contexto.
2. src/isp_rag/ingestion/pdf_parser.py — extração com pypdf, preservando
   quebras de seção. Documentos técnicos do ISP usam a mesma lógica por seção.
3. tests/test_chunker.py com um trecho real da Portaria 1.467 em
   tests/fixtures/portaria_trecho.txt:
   - nenhum chunk parte um artigo ao meio
   - todo chunk tem hierarquia prefixada
   - artigo com 5 incisos permanece íntegro em 1 chunk
```

---

## T07 — Memory: índice híbrido no Qdrant

```
Depende de T06. Leia docs/projeto-isp-rag.md §5.2 (recuperação híbrida).

1. src/isp_rag/memory/indexer.py:
   - Coleção Qdrant `isp_normas` com vetor denso (text-embedding-3-small, 1536,
     cosine) E vetor esparso nativo do Qdrant. enable_hybrid=True.
   - index_chunks(chunks: list[ArticleChunk]) — payload com TODOS os campos do
     ArticleChunk (são eles que permitem os filtros).
2. src/isp_rag/memory/engine.py:
   - build_memory_engine(reference_date: date | None) -> QueryEngine
   - Fusão por Reciprocal Rank Fusion, similarity_top_k=5, sparse_top_k=10
   - FILTRO DE VIGÊNCIA: se reference_date vier, filtra situacao == "vigente"
     na data. É o padrão, não opção.
   - LOOKUP POR CITAÇÃO: se a pergunta casar com r"art\.?\s*(\d+)" ou citar
     norma explicitamente, faz consulta EXATA por payload em vez de vetorial.
     Implemente como pré-etapa antes de acionar o retriever.
3. tests/test_memory_engine.py:
   - "qual o prazo para enviar o demonstrativo" → recupera por semântica
   - "art. 241" → aciona lookup exato, e o art. 241 é o top-1
   - pergunta com reference_date antiga → não retorna dispositivo revogado
```

---

## T08 — Roteador

```
Depende de T05 e T07. Leia plan.md §9.

1. src/isp_rag/query/router.py:
   - build_router() -> RouterQueryEngine com QueryEngineTool para ledger e memory
     (brain entra em T12 — deixe o ponto de extensão pronto)
   - Descrições das tools decisivas para o acerto: diga explicitamente que
     ledger responde número/nota/ranking/comparação numérica e memory responde
     texto normativo/exigência/prazo/definição.
   - LLMSingleSelector com temperature=0
2. build_subquestion_engine() — SubQuestionQueryEngine sobre as mesmas tools,
   para perguntas que cruzam domínios (spec §3.4).
3. route(question) -> tuple[str, QueryEngine] — expõe qual engine foi escolhida,
   sem executar. T11 mede acurácia com isso.
4. tests/test_router.py — 9 perguntas rotuladas (3 por engine), assertando a
   escolha. Marque xfail nas de brain até T12.
```

---

## T09 — Síntese com citação obrigatória e recusa

```
Depende de T08. Leia docs/projeto-isp-rag.md §6.3 e plan.md R2/R3.

1. src/isp_rag/query/synthesizer.py — prompt de síntese com as três regras duras:
   a) responder EXCLUSIVAMENTE com base no contexto recuperado
   b) citar norma+dispositivo, ou tabela+edição, em CADA afirmação
   c) declarar ausência de base quando não houver — nunca preencher a lacuna

   Prompt (ajuste a redação, mantenha a substância):
   ---
   Você responde sobre a previdência pública brasileira (RPPS) usando APENAS o
   contexto abaixo.

   REGRAS:
   1. Se o contexto não contém a resposta, diga exatamente: "Não há base na
      documentação indexada para responder a essa pergunta." Não infira, não
      complete com conhecimento geral.
   2. Cada afirmação factual cita a fonte: norma e dispositivo (ex.: "Portaria
      MTP 1.467/2022, art. 241") ou tabela e edição (ex.: "isp_resultado, ed. 2025").
   3. Se a pergunta parte de premissa falsa — cita norma revogada ou critério de
      edição em que ele não existia — CORRIJA a premissa antes de responder.

   CONTEXTO:
   {context}

   PERGUNTA: {question}
   ---
2. synthesize(question, nodes, engines_used) -> QueryResponse
   Popula sources a partir dos metadados dos nodes. Detecta a frase de recusa e
   marca refused=True (permitindo sources=[] sem violar R2).
3. tests/test_synthesizer.py:
   - contexto vazio → refused=True, e a resposta contém a frase de recusa
   - contexto com art. 241 → sources não-vazio, ref contém "art. 241"
   - pergunta com premissa falsa → a resposta menciona a correção
```

---

## T10 — FastAPI /query

```
Depende de T09. Leia plan.md §4 e §6.

1. src/isp_rag/api/main.py:
   - POST /query — body QueryRequest, resposta QueryResponse
     Se request.engines vier, força as engines; senão roteia.
     Pergunta cruzando domínios → SubQuestionQueryEngine.
   - GET /health — checa Postgres, Qdrant e Neo4j, retorna status por serviço
   - GET /sources/{engine} — o que está indexado (contagem, edições, normas)
   - Lifespan: constrói as engines uma vez no startup, não por request.
   - Handler de ValidationError → HTTP 500 com corpo explicando que a resposta
     violou o contrato. Falha de R2 é bug do sistema, não erro do cliente.
2. Logging estruturado: pergunta, engines acionadas, latência, nº de fontes.
3. tests/test_api.py com TestClient:
   - /query com pergunta de nota → 200, sources não-vazio
   - /query com pergunta fora do escopo → 200, refused=True
   - /query com question="" → 422
   - /health → 200 com os 3 serviços

Rodar: `uvicorn isp_rag.api.main:app --reload --port 8000`
```

---

## T11 — Gold set e métricas

```
Depende de T10. Leia docs/projeto-isp-rag.md §7 inteiro. Esta camada é o que
separa "funciona no demo" de "sabe-se que funciona" — não a trate como opcional.

1. eval/gold_set.json — 40 perguntas, 8 por categoria:
   fato_numerico | exigencia_normativa | comparacao_edicoes |
   capciosa | sem_resposta
   Schema por item:
     {"id","question","category","expected_engine","reference_sql"?,
      "expected_source_ref"?,"should_refuse":bool,"notes"?}
   Escreva as perguntas MANUALMENTE a partir dos dados reais já carregados.
   NÃO gere sinteticamente (R4).

2. eval/runners/routing.py — acurácia + matriz de confusão do roteador.
   Determinístico, sem custo de LLM além da seleção. Roda em segundos.

3. eval/runners/sql_match.py — EXECUTION MATCH: executa o SQL gerado e o
   reference_sql, compara os RESULTSETS (ordenados, normalizados).
   Comparar strings de SQL é métrica errada — dois SQLs distintos podem
   estar ambos corretos.

4. eval/runners/retrieval.py — Recall@k, MRR, e "o dispositivo correto
   apareceu no top-5?". Determinístico, sem LLM.

5. eval/runners/generation.py — LLM-as-judge com JUDGE_MODEL e rubrica
   explícita (0-2 por eixo): fidelidade ao contexto, precisão da citação,
   recusa correta. É o custo dominante — suporte --sample N.

6. eval/run_all.py — roda tudo, grava eval/runs/<timestamp>.json e imprime
   tabela. Flag --deterministic-only pula o judge.

7. .github/workflows/eval.yml — CI: sobe os serviços, roda os runners
   determinísticos a cada push. Judge só em tag de versão.
```

---

## T12 — Brain: ontologia e carga

```
Depende de T10. Paralelizável com T11. Leia plan.md §8 e spec §5.3.
Princípio: schema ambicioso, carga incremental.

1. src/isp_rag/brain/ontology.cypher — constraints de unicidade para os 6 nós
   (Norma, Dispositivo, Edicao, Criterio, Indicador, Ente) e índices.
   Modele a ontologia COMPLETA agora — migrar grafo depois é caro.
2. src/isp_rag/brain/loader.py:
   - load_ontology() — aplica constraints
   - load_metodologia(ano) — carrega o subgrafo Edicao -[:COMPOE]-> Criterio
     -[:COMPOE]-> Indicador a partir dos documentos de metodologia do ISP
   - Deixe stubs documentados para load_cadeia_normativa() (REVOGA/ALTERA) e
     load_linhagem() (Dispositivo -[:CONSOME_CAMPO]-> Indicador) — v2+
3. src/isp_rag/brain/engine.py — PropertyGraphIndex sobre Neo4j,
   build_brain_engine().
4. Registre a tool de brain no router de T08 e remova os xfail de T08/T11.
5. tests/test_brain.py:
   - "que critérios compõem a edição 2025?" → traversal correto
   - a pergunta de demonstração de spec §3.4 aciona as TRÊS engines via
     SubQuestionQueryEngine e retorna sources dos três tipos

Esta é a task que fecha a tese do projeto (§3.4). Se ela funciona, a arquitetura
de três camadas está justificada.
```

---

## T13 — MCP Server

```
Depende de T10. Última task do escopo local.

1. src/isp_rag/mcp/server.py — servidor MCP (stdio) expondo 4 tools:
   - consultar_isp(pergunta, data_referencia?) -> QueryResponse serializada
   - nota_do_ente(cnpj|nome_municipio, ano) -> acesso direto ao Ledger
   - buscar_norma(termo, data_referencia?) -> acesso direto ao Memory
   - listar_edicoes() -> edições disponíveis com contagem de entes
   Descrições das tools escritas para um agente decidir sozinho qual usar.
2. Toda tool retorna as fontes citadas (R2 vale no MCP também).
3. Documente em README.md o bloco de configuração para registrar o servidor
   em um cliente MCP, usando caminho absoluto do projeto e o .env local.
4. tests/test_mcp.py — invoca cada tool via cliente MCP em processo e valida
   o shape da resposta.

Ao fim desta task o escopo local está completo: ingestão com procedência,
três camadas, API validada, avaliação medida e consumo por agentes.
```

---

## Fora do escopo desta versão

Registrado para não virar escopo por acidente:

- Deploy gerenciado (Railway ou equivalente) — spec §7.3 do workshop
- SICONFI / fase v1.5 — a tabela já existe em plan.md §7, o loader não
- Interface de consulta em TypeScript — fase v3
- Cadeia normativa completa e linhagem no grafo — v2+, stubs em T12
