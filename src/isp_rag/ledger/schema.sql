-- Ledger do ISP-RAG — a verdade numérica.
-- Chave temporal (edicao_ano) em toda tabela de fato (R6).
-- Ver plan.md §7 e §7.1.

CREATE EXTENSION IF NOT EXISTS unaccent;

-- ---------------------------------------------------------------------------
-- Regime metodológico
-- ---------------------------------------------------------------------------
-- Entidade, não array denormalizado: a comparabilidade é DERIVADA (mesmo
-- regime = comparável) e um terceiro regime entra como linha, sem migração.
CREATE TABLE IF NOT EXISTS regime (
    id              TEXT PRIMARY KEY,
    descricao       TEXT NOT NULL,
    texto_ressalva  TEXT NOT NULL,
    escala_conceito TEXT[] NOT NULL
);

COMMENT ON TABLE regime IS
    'Regime metodológico de uma edição do ISP. Edições de regimes diferentes '
    'NÃO são comparáveis entre si.';
COMMENT ON COLUMN regime.texto_ressalva IS
    'Ressalva servida ao usuário quando uma resposta cruza regimes.';

-- ---------------------------------------------------------------------------
-- Dimensões
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ente (
    cnpj      VARCHAR(14) PRIMARY KEY,
    nome      TEXT NOT NULL,
    uf        CHAR(2) NOT NULL,
    municipio TEXT
);

COMMENT ON TABLE ente IS 'Ente federativo com RPPS avaliado pelo ISP.';
COMMENT ON COLUMN ente.cnpj IS 'CNPJ da unidade gestora, 14 dígitos, sem pontuação.';

CREATE TABLE IF NOT EXISTS edicao (
    ano                 SMALLINT PRIMARY KEY,
    metodologia_ref     TEXT,
    url_fonte           TEXT NOT NULL,
    regime_metodologico TEXT NOT NULL REFERENCES regime(id),
    n_entes_avaliados   INTEGER
);

COMMENT ON TABLE edicao IS 'Edição anual do ISP-RPPS, de 2017 a 2025.';
COMMENT ON COLUMN edicao.ano IS
    'Ano da edição. Chave temporal — use para comparar entre edições.';
COMMENT ON COLUMN edicao.regime_metodologico IS
    'tercil-anual (2017-2024) ou corte-historico (2025+). Conceitos de regimes '
    'diferentes não são comparáveis: a régua mudou, não só o desempenho.';
COMMENT ON COLUMN edicao.n_entes_avaliados IS
    'Universo da edição. O tercil é relativo a ele.';

-- Grupo e subgrupo são POR EDIÇÃO: o ente migra de porte conforme o número de
-- segurados, e a classificação é atribuída dentro do grupo, não na população
-- global.
CREATE TABLE IF NOT EXISTS ente_grupo (
    cnpj       VARCHAR(14) NOT NULL REFERENCES ente,
    edicao_ano SMALLINT NOT NULL REFERENCES edicao,
    grupo      TEXT NOT NULL,
    subgrupo   TEXT,
    PRIMARY KEY (cnpj, edicao_ano)
);

COMMENT ON TABLE ente_grupo IS
    'Porte e maturidade do ente naquela edição. A classificação do ISP é '
    'atribuída DENTRO do grupo/subgrupo — média nacional de conceito costuma '
    'ser a pergunta errada.';

-- ---------------------------------------------------------------------------
-- Fatos
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS isp_resultado (
    cnpj           VARCHAR(14) NOT NULL REFERENCES ente,
    edicao_ano     SMALLINT NOT NULL REFERENCES edicao,
    conceito       CHAR(1) NOT NULL,
    perfil_atuarial TEXT,
    PRIMARY KEY (cnpj, edicao_ano)
);

COMMENT ON TABLE isp_resultado IS 'Classificação final do ente por edição.';
COMMENT ON COLUMN isp_resultado.conceito IS
    'Classificação final: A (melhor) a D (pior). NÃO existe conceito E. '
    'Escala diferente da do indicador parcial, que usa A/B/C.';
COMMENT ON COLUMN isp_resultado.perfil_atuarial IS
    'Perfil da Portaria SPREV 14.762/2020: I=conceito D, II=C, III=B, IV=A.';

-- Memória de cálculo: um registro por (ente, edição, dimensão, indicador).
-- A fonte publica LETRA (A/B/C), não valor numérico — daí `letra` e não `nota`.
CREATE TABLE IF NOT EXISTS isp_componente (
    cnpj       VARCHAR(14) NOT NULL,
    edicao_ano SMALLINT NOT NULL,
    dimensao   TEXT NOT NULL,
    indicador  TEXT NOT NULL,
    letra      CHAR(1),
    valor      NUMERIC,
    PRIMARY KEY (cnpj, edicao_ano, dimensao, indicador),
    FOREIGN KEY (cnpj, edicao_ano) REFERENCES isp_resultado
);

COMMENT ON TABLE isp_componente IS
    'Memória de cálculo do ISP: a classificação de cada indicador parcial que '
    'compõe o resultado do ente.';
COMMENT ON COLUMN isp_componente.letra IS
    'Classificação do indicador parcial: A, B ou C. Três níveis — não confundir '
    'com o conceito final do ente, que vai de A a D.';
COMMENT ON COLUMN isp_componente.dimensao IS
    'gestao_transparencia, financas_liquidez ou atuaria.';
COMMENT ON COLUMN isp_componente.valor IS
    'Valor numérico do indicador, quando a fonte publica. Frequentemente NULL: '
    'a planilha traz a letra, não o valor bruto (R4 — não preencher).';

-- SICONFI, fase v1.5
CREATE TABLE IF NOT EXISTS siconfi_fiscal (
    cnpj          VARCHAR(14) NOT NULL,
    exercicio     SMALLINT NOT NULL,
    rcl           NUMERIC,
    payload_bruto JSONB NOT NULL,
    PRIMARY KEY (cnpj, exercicio)
);

-- ---------------------------------------------------------------------------
-- Índices
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_resultado_edicao   ON isp_resultado (edicao_ano);
CREATE INDEX IF NOT EXISTS ix_resultado_conceito ON isp_resultado (conceito);
CREATE INDEX IF NOT EXISTS ix_ente_uf            ON ente (uf);
CREATE INDEX IF NOT EXISTS ix_componente_edicao  ON isp_componente (edicao_ano, dimensao);
CREATE INDEX IF NOT EXISTS ix_grupo_edicao       ON ente_grupo (edicao_ano, grupo);

-- ---------------------------------------------------------------------------
-- VIEW exposta ao Text-to-SQL (defesa estrutural, plan.md §7.1)
-- ---------------------------------------------------------------------------
-- O modelo enxerga esta view, não a tabela crua: torna impossível ler a nota
-- sem que o regime metodológico esteja disponível.
CREATE OR REPLACE VIEW isp_resultado_v AS
SELECT r.cnpj,
       r.edicao_ano,
       r.conceito,
       r.perfil_atuarial,
       e.nome  AS ente_nome,
       e.uf,
       g.grupo,
       g.subgrupo,
       ed.regime_metodologico,
       ed.n_entes_avaliados,
       ed.url_fonte
FROM isp_resultado r
JOIN ente   e  ON e.cnpj = r.cnpj
JOIN edicao ed ON ed.ano = r.edicao_ano
LEFT JOIN ente_grupo g ON g.cnpj = r.cnpj AND g.edicao_ano = r.edicao_ano;

-- Este comentário é o ÚNICO contexto que chega ao Text-to-SQL sobre a view:
-- o custom_table_info do LlamaIndex é ignorado para views. Os formatos literais
-- abaixo evitam os erros observados na avaliação (T11).
COMMENT ON VIEW isp_resultado_v IS
    'Resultado do ISP por ente e edição. Use esta view, nunca isp_resultado direto. '
    'FORMATOS LITERAIS (a comparação é sensível a caixa): '
    'ente_nome é MAIÚSCULO e termina com a UF, ex.: ''CAMPINAS - SP'' — NUNCA use '
    'ente_nome = ''Campinas''; para município use unaccent(ente_nome) ILIKE unaccent(''%CAMPINAS%''). '
    'grupo é um de ''ESTADO/DF'', ''GRANDE PORTE'', ''MÉDIO PORTE'', ''PEQUENO PORTE'', '
    '''NÃO CLASSIFICADO'' — nunca ''Grande Porte''. '
    'subgrupo é ''MENOR MATURIDADE'', ''MAIOR MATURIDADE'', ''ESTADO/DF'' ou ''NÃO CLASSIFICADO''. '
    'conceito vai de A (melhor) a D (pior); não existe E. '
    'Para contar entes, conte nesta view — nunca junte com isp_componente, que tem '
    '~9 linhas por ente e multiplicaria a contagem.';
