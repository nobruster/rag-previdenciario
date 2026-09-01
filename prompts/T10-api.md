# T10 — FastAPI /query

**Depende de:** T09 · **Saída:** v0 fechada — sistema consultável de ponta a ponta

## Contexto

Todas as peças existem. Esta task as expõe como serviço e **fecha a v0**: a
partir daqui o sistema responde perguntas de fato numérico e de exigência
normativa, com fonte citada.

T11, T12 e T13 dependem desta task, e T11/T12 podem rodar em paralelo depois.

---

## PROMPT

````
Você vai expor o ISP-RAG como API HTTP validada por contratos Pydantic.

## Regras aplicáveis

R2 — QueryResponse sem fonte é erro de contrato. Se a validação falhar em
     runtime, isso é BUG DO SISTEMA (HTTP 500), não erro do cliente (4xx).
     Essa distinção importa: um 4xx faria o cliente achar que a pergunta dele
     estava errada.

## Entregáveis

### 1. src/isp_rag/api/main.py

  Lifespan: construa as engines UMA VEZ no startup e guarde no app.state.
  Construir por request custa segundos e várias chamadas de embedding.

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      app.state.router = build_router(brain_enabled=BRAIN_ENABLED)
      app.state.subq   = build_subquestion_engine(brain_enabled=BRAIN_ENABLED)
      yield

### 2. POST /query

  Body: QueryRequest → Response: QueryResponse

  Fluxo:
    1. Se request.engines vier explícito → usa só essas engines
    2. Senão, needs_decomposition(question)?
         sim → SubQuestionQueryEngine (popula sub_questions na resposta)
         não → RouterQueryEngine
    3. synthesize() → QueryResponse
    4. Retorna

  reference_date do request é propagado até o filtro de vigência do Memory.

### 3. GET /health

  Checa os três serviços de verdade (não só "app up"):
    postgres → SELECT 1
    qdrant   → GET /collections
    neo4j    → RETURN 1   (se brain habilitado; senão reporta "disabled")

  {"status": "ok" | "degraded",
   "services": {"postgres": "ok", "qdrant": "ok", "neo4j": "disabled"}}

  HTTP 200 mesmo em degraded — o corpo carrega o detalhe. 503 só se nenhum
  serviço essencial responder.

### 4. GET /sources/{engine}

  O que está indexado, por engine:
    ledger → edições carregadas, nº de entes por edição, data da última carga
    memory → normas indexadas, nº de chunks, situação (vigentes/revogados)
    brain  → nº de nós por label e arestas por tipo

  Serve para o usuário saber o que o sistema PODE responder antes de perguntar.

### 5. Tratamento de erro

  - ValidationError em QueryResponse → HTTP 500, corpo:
      {"error": "contract_violation",
       "detail": "a resposta gerada violou o contrato (R2): ...",
       "question": "..."}
    Loga em ERROR. É bug, e precisa ser visível.
  - SQLSafetyError → HTTP 500 com detalhe (tentativa de escrita bloqueada)
  - Timeout de LLM → HTTP 504
  - QueryRequest inválido → 422 (padrão do FastAPI, não intercepte)

### 6. Logging estruturado

  Uma linha JSON por request: timestamp, question (truncada em 200),
  engines_used, is_multi_domain, n_sources, refused, latency_ms, error?

  Não logue a resposta inteira — polui e pode ficar grande.

### 7. tests/test_api.py

  Com TestClient e as engines mockadas onde fizer sentido:

  - POST /query pergunta de nota → 200, sources não-vazio, engines_used=["ledger"]
  - POST /query pergunta normativa → 200, engines_used=["memory"]
  - POST /query pergunta fora do escopo ("qual a capital da Mongólia")
      → 200 com refused=True (NÃO é erro HTTP — recusar é sucesso, R3)
  - POST /query question="" → 422
  - POST /query question com 3000 chars → 422
  - POST /query com engines=["ledger"] força a engine
  - GET /health → 200, três serviços reportados
  - GET /sources/ledger → 200 com as edições
  - engine devolvendo resposta sem fonte (mock) → 500 com contract_violation

## Validação

  uvicorn isp_rag.api.main:app --reload --port 8000

  curl -s localhost:8000/health | jq
  curl -s -X POST localhost:8000/query \
    -H 'content-type: application/json' \
    -d '{"question":"Qual a nota do RPPS de <município> em 2025?"}' | jq
  curl -s -X POST localhost:8000/query \
    -H 'content-type: application/json' \
    -d '{"question":"Qual a capital da Mongólia?"}' | jq '.refused'

Ao fim desta task a v0 está fechada: ingestão com procedência, Ledger, Memory,
roteamento, síntese com citação e API validada.
````

---

## Validação

```bash
uvicorn isp_rag.api.main:app --port 8000 &
curl -s localhost:8000/health | jq
pytest tests/test_api.py -v
```

## Aceite

- [ ] Engines construídas no lifespan, não por request
- [ ] Pergunta fora do escopo → **200 com `refused=true`**, não erro HTTP
- [ ] Violação de R2 em runtime → **500** (bug do sistema), não 4xx
- [ ] `/health` checa os três serviços de verdade
- [ ] `/sources/{engine}` mostra o que está indexado
- [ ] Log estruturado com latência e nº de fontes
- [ ] **v0 fechada** — sistema responde de ponta a ponta com fonte citada
