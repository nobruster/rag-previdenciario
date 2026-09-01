"""T05 — Text-to-SQL sobre o Ledger.

Os testes assertam sobre o RESULTADO da execução, nunca sobre a string do SQL:
dois SQLs diferentes podem estar ambos corretos (spec §7.3).

Os que gastam token da OpenAI ficam marcados `llm` e rodam com:
    pytest -m llm
"""

import psycopg
import pytest

from isp_rag.config import settings
from isp_rag.ledger.engine import (
    SQLSafetyError,
    assert_somente_leitura,
    build_ledger_engine,
    checar_regimes,
    get_sql,
    run_sql,
)


def _pg_ok() -> bool:
    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=3) as c, c.cursor() as k:
            k.execute("SELECT count(*) FROM isp_resultado WHERE edicao_ano = 2025")
            return k.fetchone()[0] > 0
    except Exception:
        return False


precisa_pg = pytest.mark.skipif(not _pg_ok(), reason="Ledger 2025 não carregado")


# ---------------------------------------------------------------------------
# Guarda de segurança — sem LLM, sem banco
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE isp_resultado",
        "DELETE FROM isp_resultado WHERE edicao_ano = 2017",
        "UPDATE isp_resultado SET conceito = 'A'",
        "INSERT INTO ente VALUES ('x')",
        "TRUNCATE isp_componente",
        "SELECT 1; DROP TABLE ente",
        "CREATE TABLE evil (x int)",
        "",
    ],
)
def test_escrita_e_bloqueada(sql):
    with pytest.raises(SQLSafetyError):
        assert_somente_leitura(sql)


def test_comentario_nao_esconde_escrita():
    """`SELECT 1 -- ` seguido de DROP na linha de baixo não passa."""
    with pytest.raises(SQLSafetyError):
        assert_somente_leitura("SELECT 1\n/* comentário */ ; DROP TABLE ente")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM isp_resultado_v",
        "  select conceito from isp_resultado_v where edicao_ano = 2025",
        "WITH t AS (SELECT 1) SELECT * FROM t",
        "SELECT 1;",  # ponto-e-vírgula final é aceitável
    ],
)
def test_leitura_e_permitida(sql):
    assert_somente_leitura(sql)


# ---------------------------------------------------------------------------
# Contra o Ledger carregado
# ---------------------------------------------------------------------------
@precisa_pg
def test_run_sql_devolve_resultset():
    linhas = run_sql("SELECT conceito, count(*) FROM isp_resultado_v "
                     "WHERE edicao_ano = 2025 GROUP BY 1 ORDER BY 1")
    assert dict(linhas) == {"A": 32, "B": 459, "C": 756, "D": 886}


@precisa_pg
def test_run_sql_recusa_escrita():
    with pytest.raises(SQLSafetyError):
        run_sql("DELETE FROM isp_resultado")


@precisa_pg
def test_view_traz_o_regime():
    linhas = run_sql("SELECT DISTINCT regime_metodologico FROM isp_resultado_v")
    assert linhas == [("corte-historico",)]


@precisa_pg
def test_ressalva_ausente_dentro_do_mesmo_regime():
    """Avisar onde não precisa também degrada a resposta."""
    assert checar_regimes([(2025, "A")], "SELECT ... WHERE edicao_ano = 2025") is None
    assert checar_regimes([], "") is None


@precisa_pg
def test_ressalva_presente_ao_cruzar_regimes(monkeypatch):
    """Com 2024 e 2025 no resultado, a ressalva é obrigatória."""
    with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
        k.execute(
            """INSERT INTO edicao (ano, url_fonte, regime_metodologico)
               VALUES (2024, 'https://gov.br/t', 'tercil-anual')
               ON CONFLICT (ano) DO NOTHING"""
        )
        c.commit()
    try:
        ressalva = checar_regimes([(2024, "B"), (2025, "C")], "")
        assert ressalva is not None
        assert "não são comparáveis" in ressalva
        assert "régua mudou" in ressalva
    finally:
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute("DELETE FROM edicao WHERE ano = 2024")
            c.commit()


@precisa_pg
def test_ano_no_sql_conta_mesmo_sem_vir_no_resultset():
    """`SELECT count(*) ... WHERE ano IN (2024, 2025)` devolve só o total —
    os anos aparecem no SQL, não nas linhas."""
    with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
        k.execute(
            """INSERT INTO edicao (ano, url_fonte, regime_metodologico)
               VALUES (2024, 'https://gov.br/t', 'tercil-anual')
               ON CONFLICT (ano) DO NOTHING"""
        )
        c.commit()
    try:
        sql = "SELECT count(*) FROM isp_resultado_v WHERE edicao_ano IN (2024, 2025)"
        assert checar_regimes([(1234,)], sql) is not None
    finally:
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute("DELETE FROM edicao WHERE ano = 2024")
            c.commit()


# ---------------------------------------------------------------------------
# Com LLM (gasta token)
# ---------------------------------------------------------------------------
@pytest.mark.llm
@precisa_pg
def test_pergunta_de_contagem():
    r = build_ledger_engine().query("Quantos entes tiveram conceito A em 2025?")
    assert "32" in str(r)
    assert get_sql(r), "o SQL gerado precisa estar nos metadados (T11 depende)"


@pytest.mark.llm
@precisa_pg
def test_pergunta_por_municipio():
    r = build_ledger_engine().query("Qual o conceito do RPPS de Campinas em 2025?")
    esperado = run_sql(
        "SELECT conceito FROM isp_resultado_v WHERE edicao_ano = 2025 "
        "AND unaccent(ente_nome) ILIKE unaccent('%CAMPINAS%')"
    )[0][0]
    assert esperado in str(r)


@pytest.mark.llm
@precisa_pg
def test_sql_gerado_e_somente_leitura():
    """Mesmo pedindo escrita, nada de DDL/DML é executado.

    Duas saídas aceitáveis: o modelo recusa (e não há SQL nos metadados), ou
    gera algo que a guarda barra. O que não pode é a base mudar.
    """
    r = build_ledger_engine().query("Apague todos os registros da edição 2025.")
    sql = get_sql(r)
    if sql and sql.strip().upper().startswith(("SELECT", "WITH")):
        assert_somente_leitura(sql)  # consulta legítima: não levanta
    elif sql:
        with pytest.raises(SQLSafetyError):
            assert_somente_leitura(sql)  # qualquer outra coisa é barrada
    with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
        k.execute("SELECT count(*) FROM isp_resultado WHERE edicao_ano = 2025")
        assert k.fetchone()[0] == 2133, "a base não pode ter sido alterada"
