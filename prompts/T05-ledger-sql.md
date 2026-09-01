# T05 — Ledger: engine Text-to-SQL

**Depende de:** T04 · **Saída:** perguntas em português viram SQL sobre o Ledger

## Contexto

O Ledger está populado e com `COMMENT ON` nas tabelas. Esta task põe o
`NLSQLTableQueryEngine` em cima dele.

Ponto que a spec §7.3 faz questão: o acerto aqui será medido por **execution
match** em T11 — dois SQLs diferentes podem estar ambos corretos, então comparar
strings é métrica errada. Por isso esta task precisa expor o SQL gerado.

---

## PROMPT

````
Você vai implementar a engine Text-to-SQL do Ledger, usando LlamaIndex sobre o
PostgreSQL já populado.

## Regras aplicáveis

R5 — O LLM vem de isp_rag.llm (llama_llm()). Nenhum import de openai aqui.
R6 — edicao_ano é a chave temporal. O prompt de contexto precisa deixar isso
     explícito para o modelo.

## Entregáveis

### 1. src/isp_rag/ledger/engine.py

  def build_ledger_engine() -> NLSQLTableQueryEngine:
      """
      SQLDatabase sobre as 4 tabelas do Ledger, com include_tables EXPLÍCITO:
        ["ente", "edicao", "isp_resultado", "isp_componente"]
      (siconfi_fiscal fica de fora até a v1.5)

      LLM: llama_llm() com temperature=0.
      """

  O contexto de tabela é o que decide o acerto. Passe table_context por tabela,
  complementando os COMMENT ON do banco. O modelo precisa saber:

    - conceito é CHAR(1) de 'A' a 'E', onde A é o melhor
    - edicao_ano é a chave temporal; comparar edições = filtrar/agrupar por ela
    - ATENÇÃO: edicao.regime_metodologico separa 'tercil-anual' (2017–2024) de
      'corte-historico' (2025+). Conceitos de regimes diferentes NÃO são
      comparáveis — a régua mudou, não só o desempenho. Em query que cruze
      edições, TRAGA edicao.regime_metodologico no SELECT, para a síntese poder
      declarar a ressalva. Ver plan.md §7.1.
    - cnpj tem 14 dígitos, sem pontuação
    - nota_final é NUMERIC(5,4), escala 0 a 1
    - isp_componente guarda a memória de cálculo: um registro por
      (ente, edição, critério, indicador)
    - para "qual a nota do município X", junte ente por nome/município,
      usando ILIKE com unaccent — os nomes vêm com acento e caixa variável

  Habilite unaccent no Postgres se necessário (CREATE EXTENSION IF NOT EXISTS
  unaccent) e diga isso no contexto de tabela.

### 2. Exposição do SQL gerado

  def get_sql(response) -> str | None:
      """Extrai o SQL dos metadados da resposta do LlamaIndex.
      T11 precisa disto para medir execution match."""

  def run_sql(sql: str) -> list[tuple]:
      """Executa SQL cru e devolve o resultset. Usado pelo runner de avaliação
      para comparar resultado do SQL gerado × SQL de referência."""

  Ambas públicas — são a interface que a camada de avaliação consome.

### 3. Guarda de segurança

  O Text-to-SQL só pode LER. Antes de executar, valide que o SQL gerado:
    - começa com SELECT ou WITH
    - não contém INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, GRANT, COPY
    - não tem ';' seguido de outro statement

  Se violar, levante SQLSafetyError com o SQL ofensivo. Um LLM não deveria
  conseguir escrever no Ledger nem por acidente nem por prompt injection vinda
  do texto de uma pergunta.

  Adicionalmente: use um usuário Postgres somente-leitura para esta engine, se
  for simples de configurar no compose. Documente se não for.

### 4. tests/test_ledger_engine.py

Contra o Postgres do compose, com a edição 2025 carregada.

Asserte sobre o RESULTADO da execução, NUNCA sobre a string do SQL:

  - "Qual a nota do RPPS de <município real do banco> em 2025?"
      → retorna 1 linha, nota bate com a do banco
  - "Quantos entes tiveram conceito A em 2025?"
      → bate com SELECT count(*) ... WHERE conceito='A'
  - "Qual a média das notas por UF em 2025?"
      → 27 linhas (ou o número real de UFs presentes)
  - "Quais os 5 entes com maior nota em 2025?"
      → 5 linhas, ordenadas desc

  E testes de segurança:
  - SQL com DROP → SQLSafetyError
  - pergunta cuja resposta esperada seria escrita ("apague os dados de 2017")
    → não executa DDL/DML

Se um teste depender de dado específico do banco, calcule o esperado com uma
query direta no próprio teste, em vez de hardcodar número.

## Validação

  pytest tests/test_ledger_engine.py -v
  python -c "
  from isp_rag.ledger.engine import build_ledger_engine, get_sql
  e = build_ledger_engine()
  r = e.query('Quantos entes tiveram conceito A em 2025?')
  print(r); print('SQL:', get_sql(r))
  "
````

---

## Validação

```bash
pytest tests/test_ledger_engine.py -v
```

## Aceite

- [ ] Perguntas em português retornam resultado correto do banco
- [ ] `get_sql()` devolve o SQL gerado (T11 depende disso)
- [ ] Testes assertam sobre **resultado**, nunca sobre string de SQL
- [ ] `SQLSafetyError` bloqueia qualquer coisa que não seja leitura
- [ ] Contexto de tabela explica conceito A–E e `edicao_ano` como chave temporal
- [ ] Nenhum `import openai` (R5)
