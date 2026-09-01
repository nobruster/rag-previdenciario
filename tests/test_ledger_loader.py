"""T04 — carga do Ledger.

Os testes que tocam Postgres pulam se o serviço não estiver no ar, para a suíte
rodar sem docker. Os de lógica pura rodam sempre.
"""

import openpyxl
import psycopg
import pytest

from isp_rag.config import settings
from isp_rag.ledger.loader import (
    COLUMN_MAP,
    REGIME_POR_ANO,
    init_schema,
    load_edicao,
    normalizar_cnpj,
)


def _pg_disponivel() -> bool:
    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=3):
            return True
    except Exception:
        return False


precisa_pg = pytest.mark.skipif(not _pg_disponivel(), reason="Postgres não está no ar")


# --------------------------------------------------------------------------
# Lógica pura
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (1613940000119, "01613940000119"),  # a planilha traz CNPJ como int
        ("01.613.940/0001-19", "01613940000119"),
        ("1234567890123", "01234567890123"),
        (None, None),
        ("", None),
        ("abc", None),
    ],
)
def test_normalizacao_de_cnpj(entrada, esperado):
    assert normalizar_cnpj(entrada) == esperado


def test_regime_por_ano_marca_a_ruptura():
    """2017-2024 são tercil anual; 2025 inaugura o corte histórico."""
    assert REGIME_POR_ANO[2024] == "tercil-anual"
    assert REGIME_POR_ANO[2025] == "corte-historico"
    assert REGIME_POR_ANO[2024] != REGIME_POR_ANO[2025]


def test_edicao_nao_mapeada_falha_alto(tmp_path):
    """Adivinhar colunas corrompe o Ledger inteiro — melhor falhar."""
    with pytest.raises(KeyError, match="não mapeada"):
        load_edicao(tmp_path / "x.xlsx", 2019, "https://gov.br/x")


def test_column_map_2025_cobre_as_tres_dimensoes():
    from isp_rag.ledger.loader import DIMENSOES

    dims = {DIMENSOES[i] for i in COLUMN_MAP[2025].indicadores}
    assert dims == {"gestao_transparencia", "financas_liquidez", "atuaria"}


# --------------------------------------------------------------------------
# Contra o Postgres
# --------------------------------------------------------------------------
def _fixture_xlsx(path):
    """Planilha mínima no layout de 2025 (cabeçalho na linha 4).

    É fixture de teste, não dado de produção — R4 proíbe dado sintético no
    Ledger real, não em teste.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RESULTADO"
    ws.append(["Índice de Situação Previdenciária"])
    ws.append(["Resultado Final"])
    ws.append([])
    ws.append(
        ["ENTE", "CNPJ", "UF", "GRUPO", "SUBGRUPO"]
        + [f"IND{i}" for i in range(5, 17)]
        + ["ISP", "PERFIL"]
    )
    linhas = [
        ("MUNICIPIO ALFA - GO", 1613940000119, "GO", "MÉDIO PORTE", "MENOR MATURIDADE", "A", "C"),
        ("MUNICIPIO BETA - SP", 2298330000178, "SP", "PEQUENO PORTE", "MAIOR MATURIDADE", "B", "B"),
        ("SEM CNPJ - RJ", None, "RJ", "MÉDIO PORTE", "MENOR MATURIDADE", "A", "A"),
    ]
    for nome, cnpj, uf, grupo, sub, ind, isp in linhas:
        row = [nome, cnpj, uf, grupo, sub] + [ind] * 12 + [isp, "II"]
        ws.append(row)
    wb.save(path)
    return path


@precisa_pg
def test_carga_popula_as_tabelas(tmp_path):
    init_schema()
    caminho = _fixture_xlsx(tmp_path / "mini.xlsx")

    # Usa um ano fictício mapeado sobre o layout de 2025.
    COLUMN_MAP[2099] = COLUMN_MAP[2025]
    REGIME_POR_ANO[2099] = "corte-historico"
    try:
        rel = load_edicao(caminho, 2099, "https://gov.br/fixture.xlsx")

        assert rel.entes == 2  # a linha sem CNPJ é ignorada
        assert rel.resultados == 2
        assert rel.componentes > 0
        assert any("CNPJ" in m for m in rel.linhas_ignoradas)

        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute("SELECT cnpj FROM ente WHERE cnpj = '01613940000119'")
            assert k.fetchone() is not None, "CNPJ deve ficar zero-padded"

            k.execute("SELECT regime_metodologico FROM edicao WHERE ano = 2099")
            assert k.fetchone()[0] == "corte-historico"

            # Recarga não duplica (upsert)
            load_edicao(caminho, 2099, "https://gov.br/fixture.xlsx")
            k.execute("SELECT count(*) FROM isp_resultado WHERE edicao_ano = 2099")
            assert k.fetchone()[0] == 2
    finally:
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute("DELETE FROM isp_componente WHERE edicao_ano = 2099")
            k.execute("DELETE FROM ente_grupo WHERE edicao_ano = 2099")
            k.execute("DELETE FROM isp_resultado WHERE edicao_ano = 2099")
            k.execute("DELETE FROM edicao WHERE ano = 2099")
            c.commit()
        COLUMN_MAP.pop(2099, None)
        REGIME_POR_ANO.pop(2099, None)


@precisa_pg
def test_view_expoe_o_regime():
    """Defesa estrutural: impossível ler a nota sem enxergar o regime."""
    with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
        k.execute("SELECT column_name FROM information_schema.columns "
                  "WHERE table_name = 'isp_resultado_v'")
        colunas = {r[0] for r in k.fetchall()}
    assert "regime_metodologico" in colunas
    assert {"conceito", "grupo", "subgrupo", "uf"} <= colunas


@precisa_pg
def test_regimes_carregados_com_ressalva():
    with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
        k.execute("SELECT id, texto_ressalva FROM regime ORDER BY id")
        regimes = dict(k.fetchall())
    assert set(regimes) == {"corte-historico", "tercil-anual"}
    assert "não são comparáveis" in regimes["corte-historico"]
