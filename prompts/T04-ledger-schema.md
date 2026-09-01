# T04 — Ledger: schema e carga das planilhas

**Depende de:** T03 · **Paralelo com:** T06 · **Saída:** Postgres populado + recálculo de verificação

## Contexto

T03 entregou as planilhas do ISP em `data/raw/`, com procedência registrada.
Esta task as transforma no Ledger — a camada da verdade numérica.

Aqui aparece a checagem de qualidade que a spec §2.4 destaca: com a memória de
cálculo no banco, dá para recalcular o indicador e comparar com o valor publicado.
Divergências viram material de análise.

---

## PROMPT

````
Você vai implementar o Ledger do ISP-RAG: o modelo relacional das notas do ISP
e a carga a partir das planilhas já coletadas em data/raw/.

## Regras aplicáveis

R4 — Sem dado sintético. Se a planilha não traz um campo, ele fica NULL. Não
     preencha com média, zero ou valor plausível.
R6 — edicao_ano é dimensão de primeira classe em toda tabela de fato. Quase toda
     pergunta interessante neste domínio é comparativa.

## Entregáveis

### 1. src/isp_rag/ledger/schema.sql

  CREATE TABLE IF NOT EXISTS ente (
      cnpj            VARCHAR(14) PRIMARY KEY,
      nome            TEXT NOT NULL,
      uf              CHAR(2) NOT NULL,
      municipio       TEXT
  );

  CREATE TABLE IF NOT EXISTS edicao (
      ano                 SMALLINT PRIMARY KEY,
      metodologia_ref     TEXT,
      url_fonte           TEXT NOT NULL,
      -- Regime metodológico. Edições de regimes diferentes NÃO são
      -- comparáveis: até 2024 o conceito vinha de tercil anual (relativo),
      -- de 2025 em diante de cortes fixos históricos (absoluto).
      -- Ver plan.md §7.1.
      regime_metodologico TEXT NOT NULL REFERENCES regime(id),
      n_entes_avaliados   INTEGER
  );

  CREATE TABLE IF NOT EXISTS regime (
      id              TEXT PRIMARY KEY,   -- 'tercil-anual' | 'corte-historico'
      descricao       TEXT NOT NULL,
      texto_ressalva  TEXT NOT NULL,      -- a ressalva servida ao usuário
      escala_conceito TEXT[] NOT NULL     -- conceitos válidos NESTE regime
  );

  CREATE TABLE IF NOT EXISTS isp_resultado (
      cnpj            VARCHAR(14) REFERENCES ente,
      edicao_ano      SMALLINT REFERENCES edicao,
      nota_final      NUMERIC(5,4),
      conceito        CHAR(1),
      PRIMARY KEY (cnpj, edicao_ano)
  );

  CREATE TABLE IF NOT EXISTS isp_componente (
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

  CREATE TABLE IF NOT EXISTS siconfi_fiscal (
      cnpj            VARCHAR(14),
      exercicio       SMALLINT,
      rcl             NUMERIC,
      payload_bruto   JSONB NOT NULL,
      PRIMARY KEY (cnpj, exercicio)
  );

  Índices: isp_resultado(edicao_ano), isp_resultado(conceito),
           ente(uf), isp_componente(edicao_ano, criterio)

  Adicione COMMENT ON em cada tabela e nas colunas não óbvias. O Text-to-SQL da
  T05 lê esses comentários como contexto — é a diferença entre o modelo acertar
  e chutar. Exemplos:
    COMMENT ON COLUMN isp_resultado.conceito IS
      'Conceito do ente na edição: A (melhor) a E (pior)';
    COMMENT ON COLUMN isp_resultado.edicao_ano IS
      'Ano da edição do ISP. Chave temporal — use para comparar entre edições';

### 2. src/isp_rag/ledger/loader.py

  def init_schema(dsn: str) -> None:
      """Executa schema.sql. Idempotente (IF NOT EXISTS)."""

  COLUMN_MAP: dict[int, dict[str, str]] = {
      2025: {"cnpj": "CNPJ", "nome": "Ente", ...},
      # uma entrada por edição
  }

  def load_edicao(xlsx_path: Path, ano: int, url_fonte: str) -> LoadReport:
      """
      Lê a planilha com openpyxl (read_only=True, data_only=True) e popula
      ente, edicao, isp_resultado e isp_componente em UMA transação.

      - CNPJ normalizado: só dígitos, zero-padded para 14
      - Se `ano` não está em COLUMN_MAP: levante KeyError com mensagem clara
        listando os anos mapeados. NÃO tente adivinhar colunas por heurística —
        errar silenciosamente o mapeamento corrompe o Ledger inteiro.
      - Linhas com CNPJ inválido: pule e registre no relatório, não aborte
      - upsert (ON CONFLICT DO UPDATE) para permitir recarga
      """

  class LoadReport(BaseModel):
      ano: int
      entes: int
      resultados: int
      componentes: int
      linhas_ignoradas: list[str]   # com o motivo

As planilhas mudam de formato entre edições (risco conhecido, spec §9). Por isso
o COLUMN_MAP explícito por ano: adicionar uma edição é adicionar uma entrada, e
uma edição não mapeada falha alto em vez de carregar lixo.

⚠️ RUPTURA METODOLÓGICA EM 2025 — leia plan.md §7.1 antes de continuar.

Até 2024 o conceito vinha de TERCIL ANUAL: ordenava-se os RPPS do ano e dividia
em três. A nota era RELATIVA — dependia de quem mais foi avaliado naquele ano.
A partir de 2025 são CORTES FIXOS derivados da distribuição histórica: a nota é
ABSOLUTA. Além disso entraram 3 indicadores novos.

O perigo é que nada no dado sinaliza isso. A letra é a mesma, a coluna é a
mesma, o SELECT roda liso. Um ente pode "cair" de B para C sem ter piorado:
mudou a régua.

Portanto, a tabela `edicao` tem duas colunas a mais (já no schema acima):

  regime_metodologico  TEXT REFERENCES regime(id)
  n_entes_avaliados    INTEGER   -- o tercil é relativo a este universo

  A comparabilidade é DERIVADA, não armazenada: duas edições são comparáveis
  se e somente se `regime_metodologico` é igual. Não guarde lista de anos
  comparáveis — seria dado derivado, que diverge do regime e exige UPDATE
  retroativo a cada edição nova.

  Popule a tabela `regime` primeiro (seed, não vem de planilha):

    ('tercil-anual', 'Conceito por tercil anual — nota relativa à distribuição
      do ano', '<texto da ressalva>', '{A,B,C,D,E}')
    ('corte-historico', 'Conceito por cortes fixos de densidade — nota
      absoluta; +3 indicadores', '<texto da ressalva>', '{A,B,C,D,E}')

  Depois, na carga de cada edição:
    2017..2024 → regime_metodologico = 'tercil-anual'
    2025       → regime_metodologico = 'corte-historico'

  Uma edição futura só precisa apontar para o regime certo; se for um regime
  novo, insere-se uma linha em `regime` — sem migração.

E um helper que o resto do sistema consome:

  def edicoes_comparaveis(a: int, b: int) -> bool:
      """True se as duas edições pertencem ao mesmo regime metodológico."""

  def ressalva_comparacao(anos: list[int]) -> str | None:
      """Texto da ressalva quando os anos cruzam regimes; None se comparáveis.
      Ex.: 'ISP-2025 foi reformulado (cortes fixos por distribuição histórica,
      3 indicadores novos); seus resultados não são comparáveis aos de 2024 e
      anteriores, que usavam tercil anual.'"""

Não force COLUMN_MAP comum entre 2025 e os anos anteriores — são estruturas
diferentes por decisão da fonte.

Isso não é defeito do dado: é a "metodologia versionada" que a spec §1.2 aponta
como uma das três propriedades que justificam o domínio, e é o que torna a
pergunta de demonstração (§3.4) real em vez de hipotética.

### 3. src/isp_rag/ledger/verify.py

Esta é a checagem de qualidade da spec §2.4 — quase nenhum projeto de portfólio
pensa em fazer isso.

  def recalcular(cnpj: str, ano: int) -> Divergencia:
      """
      Soma ponderada de isp_componente (Σ valor×peso ou Σ nota_componente×peso,
      conforme a metodologia da edição) e compara com isp_resultado.nota_final.
      """

  class Divergencia(BaseModel):
      cnpj: str
      ano: int
      publicado: Decimal
      recalculado: Decimal
      delta: Decimal
      dentro_tolerancia: bool

  def verificar_edicao(ano: int, tolerancia: Decimal) -> list[Divergencia]

  CLI: python -m isp_rag.ledger.verify --year 2025 --tolerance 0.001
  Imprime tabela das divergências e um resumo (N entes, M divergentes, delta
  máximo). Exit code 0 mesmo com divergência — é material de análise, não erro.

### 4. CLI de carga

  python -m isp_rag.ledger.load --year 2025
  python -m isp_rag.ledger.load --all

Resolve o arquivo pelo manifesto (data/raw/manifest.json), não por caminho
passado à mão — respeita R1.

Use a API já pronta da T03:

  from isp_rag.ingestion.manifest import Manifest, ManifestEntry

  entry: ManifestEntry | None = Manifest(path).by_url(url)
  # entry.filename, entry.sha256, entry.url  → url_fonte da tabela edicao

O url_fonte gravado em `edicao` vem de entry.url — assim a procedência do
número no Ledger é rastreável até o download que o originou.
Se o arquivo da edição não estiver no manifesto, falhe com mensagem dizendo
para rodar `python -m isp_rag.ingestion.fetch_isp --year <ano>` antes.

### 5. tests/test_ledger_loader.py

Fixture: tests/fixtures/isp_mini.xlsx com 5 entes e 3 componentes cada,
construída no próprio teste com openpyxl (não é dado sintético de produção —
é fixture de teste, o que R4 permite).

  - carga popula as 4 tabelas com as contagens esperadas
  - CNPJ "1234567890123" vira "01234567890123"
  - ano não mapeado → KeyError com os anos disponíveis na mensagem
  - recarga da mesma edição não duplica (upsert)
  - linha com CNPJ vazio é ignorada e aparece em linhas_ignoradas
  - recalcular() detecta divergência plantada de propósito

## Validação

  docker compose up -d postgres
  python -m isp_rag.ledger.load --year 2025
  python -m isp_rag.ledger.verify --year 2025
  psql "$POSTGRES_DSN" -c "SELECT edicao_ano, count(*), avg(nota_final) FROM isp_resultado GROUP BY 1"
````

---

## Validação

```bash
python -m isp_rag.ledger.load --year 2025
python -m isp_rag.ledger.verify --year 2025 --tolerance 0.001
pytest tests/test_ledger_loader.py -v
```

## Aceite

- [ ] As 4 tabelas existem com `COMMENT ON` preenchidos (T05 depende disso)
- [ ] `edicao_ano` presente em toda tabela de fato (R6)
- [ ] Edição não mapeada falha alto, sem adivinhar colunas
- [ ] Campo ausente na planilha fica NULL, não preenchido (R4)
- [ ] `verify` roda e reporta divergências sem tratá-las como erro fatal
- [ ] Arquivo resolvido pelo manifesto, não por caminho manual
