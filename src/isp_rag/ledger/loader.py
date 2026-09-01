"""Carga do Ledger a partir das planilhas do ISP.

O mapeamento de colunas é EXPLÍCITO por edição. As planilhas mudam de formato
entre anos (spec §9): cabeçalho na linha 1 em 2022 e na linha 4 em 2024+,
"ÍNDICE" virando "INDICADOR", CNPJ ausente antes de 2024, e 6 → 7 → 10
indicadores. Uma edição não mapeada falha alto, em vez de carregar lixo.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import psycopg

from isp_rag.config import settings
from isp_rag.ingestion.manifest import Manifest

SCHEMA_SQL = Path(__file__).with_name("schema.sql")

# ---------------------------------------------------------------------------
# Regimes metodológicos (seed — não vem de planilha)
# ---------------------------------------------------------------------------
RESSALVA_2025 = (
    "O ISP-2025 foi reformulado: até 2024 o conceito vinha de tercil anual "
    "(nota relativa à distribuição daquele ano); de 2025 em diante vem de "
    "cortes fixos sobre a distribuição histórica (nota absoluta), com três "
    "indicadores novos. O Ministério declara que os resultados não são "
    "comparáveis. Uma variação de conceito entre esses períodos NÃO significa, "
    "por si só, mudança de desempenho — a régua mudou."
)

REGIMES = [
    (
        "tercil-anual",
        "Conceito por tercil anual — a nota é relativa à distribuição do ano.",
        RESSALVA_2025,
        ["A", "B", "C", "D"],
    ),
    (
        "corte-historico",
        "Conceito por cortes fixos da distribuição histórica — nota absoluta; "
        "três indicadores novos.",
        RESSALVA_2025,
        ["A", "B", "C", "D"],
    ),
]

REGIME_POR_ANO = {ano: "tercil-anual" for ano in range(2017, 2025)} | {2025: "corte-historico"}

DIMENSOES = {
    "regularidade": "gestao_transparencia",
    "envio_informacoes": "gestao_transparencia",
    "gestao": "gestao_transparencia",
    "suficiencia_financeira": "financas_liquidez",
    "acumulacao_recursos": "financas_liquidez",
    "resultado_financeiro_equacionamento": "financas_liquidez",
    "cobertura_previdenciaria": "atuaria",
    "sustentabilidade_provisoes_rcl": "atuaria",
    "reforma_rpps_rpc": "atuaria",
}


@dataclass
class ColumnMap:
    """Onde cada campo está na planilha de uma edição."""

    sheet: str
    header_row: int  # 1-indexado
    ente: int
    uf: int
    conceito: int
    cnpj: int | None = None
    grupo: int | None = None
    subgrupo: int | None = None
    perfil: int | None = None
    indicadores: dict[str, int] = field(default_factory=dict)


# Verificado na planilha real de 2025 (aba RESULTADO, cabeçalho na linha 4).
COLUMN_MAP: dict[int, ColumnMap] = {
    2025: ColumnMap(
        sheet="RESULTADO",
        header_row=4,
        ente=0,
        cnpj=1,
        uf=2,
        grupo=3,
        subgrupo=4,
        conceito=17,
        perfil=18,
        indicadores={
            "regularidade": 5,
            "envio_informacoes": 6,
            "gestao": 7,
            "suficiencia_financeira": 9,
            "acumulacao_recursos": 10,
            "resultado_financeiro_equacionamento": 11,
            "cobertura_previdenciaria": 13,
            "sustentabilidade_provisoes_rcl": 14,
            "reforma_rpps_rpc": 15,
        },
    ),
}


@dataclass
class LoadReport:
    ano: int
    entes: int = 0
    resultados: int = 0
    componentes: int = 0
    linhas_ignoradas: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        linhas = [
            f"edição {self.ano}: {self.entes} entes, {self.resultados} resultados, "
            f"{self.componentes} componentes"
        ]
        if self.linhas_ignoradas:
            linhas.append(f"  ignoradas: {len(self.linhas_ignoradas)}")
            linhas += [f"    - {m}" for m in self.linhas_ignoradas[:5]]
            if len(self.linhas_ignoradas) > 5:
                linhas.append(f"    ... e mais {len(self.linhas_ignoradas) - 5}")
        return "\n".join(linhas)


def normalizar_cnpj(valor) -> str | None:
    """Só dígitos, zero-padded para 14. A planilha traz CNPJ como int."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    return digitos.zfill(14) if 1 <= len(digitos) <= 14 else None


def _letra(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip().upper()
    return texto if len(texto) == 1 and texto in "ABCDE" else None


def init_schema(dsn: str | None = None) -> None:
    """Aplica schema.sql e popula os regimes. Idempotente."""
    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        cur.executemany(
            """INSERT INTO regime (id, descricao, texto_ressalva, escala_conceito)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                 descricao = EXCLUDED.descricao,
                 texto_ressalva = EXCLUDED.texto_ressalva,
                 escala_conceito = EXCLUDED.escala_conceito""",
            REGIMES,
        )
        conn.commit()


def load_edicao(xlsx_path: Path, ano: int, url_fonte: str, dsn: str | None = None) -> LoadReport:
    """Carrega uma edição inteira em uma transação."""
    if ano not in COLUMN_MAP:
        raise KeyError(
            f"edição {ano} não mapeada. Mapeadas: {sorted(COLUMN_MAP)}. "
            f"As planilhas mudam de formato entre edições — adicione uma entrada "
            f"em COLUMN_MAP após inspecionar a aba, sem adivinhar colunas."
        )

    cm = COLUMN_MAP[ano]
    rel = LoadReport(ano=ano)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    linhas = list(wb[cm.sheet].iter_rows(min_row=cm.header_row + 1, values_only=True))
    wb.close()

    entes, resultados, grupos, componentes = [], [], [], []
    for i, row in enumerate(linhas, start=cm.header_row + 1):
        nome = row[cm.ente] if cm.ente < len(row) else None
        if not nome or not str(nome).strip():
            continue

        cnpj = normalizar_cnpj(row[cm.cnpj]) if cm.cnpj is not None else None
        if not cnpj:
            rel.linhas_ignoradas.append(f"linha {i}: CNPJ ausente ou inválido ({nome})")
            continue

        conceito = _letra(row[cm.conceito])
        if not conceito:
            rel.linhas_ignoradas.append(f"linha {i}: conceito ausente ({nome})")
            continue

        uf = str(row[cm.uf]).strip().upper()[:2] if cm.uf < len(row) and row[cm.uf] else "??"
        entes.append((cnpj, str(nome).strip(), uf, str(nome).strip()))
        resultados.append(
            (cnpj, ano, conceito, str(row[cm.perfil]).strip() if cm.perfil is not None else None)
        )

        if cm.grupo is not None:
            grupos.append(
                (
                    cnpj,
                    ano,
                    str(row[cm.grupo]).strip() if row[cm.grupo] else "NÃO CLASSIFICADO",
                    str(row[cm.subgrupo]).strip() if cm.subgrupo is not None else None,
                )
            )

        for indicador, col in cm.indicadores.items():
            letra = _letra(row[col]) if col < len(row) else None
            if letra:
                # R4: valor fica NULL — a planilha publica a letra, não o valor.
                componentes.append((cnpj, ano, DIMENSOES[indicador], indicador, letra, None))

    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO edicao (ano, url_fonte, regime_metodologico, n_entes_avaliados)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (ano) DO UPDATE SET
                 url_fonte = EXCLUDED.url_fonte,
                 regime_metodologico = EXCLUDED.regime_metodologico,
                 n_entes_avaliados = EXCLUDED.n_entes_avaliados""",
            (ano, url_fonte, REGIME_POR_ANO[ano], len(resultados)),
        )
        cur.executemany(
            """INSERT INTO ente (cnpj, nome, uf, municipio) VALUES (%s, %s, %s, %s)
               ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome, uf = EXCLUDED.uf""",
            entes,
        )
        cur.executemany(
            """INSERT INTO isp_resultado (cnpj, edicao_ano, conceito, perfil_atuarial)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (cnpj, edicao_ano) DO UPDATE SET
                 conceito = EXCLUDED.conceito, perfil_atuarial = EXCLUDED.perfil_atuarial""",
            resultados,
        )
        if grupos:
            cur.executemany(
                """INSERT INTO ente_grupo (cnpj, edicao_ano, grupo, subgrupo)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (cnpj, edicao_ano) DO UPDATE SET
                     grupo = EXCLUDED.grupo, subgrupo = EXCLUDED.subgrupo""",
                grupos,
            )
        cur.executemany(
            """INSERT INTO isp_componente
                 (cnpj, edicao_ano, dimensao, indicador, letra, valor)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (cnpj, edicao_ano, dimensao, indicador) DO UPDATE SET
                 letra = EXCLUDED.letra, valor = EXCLUDED.valor""",
            componentes,
        )
        conn.commit()

    rel.entes = len(entes)
    rel.resultados = len(resultados)
    rel.componentes = len(componentes)
    return rel


def resolver_planilha(ano: int) -> tuple[Path, str]:
    """Localiza a planilha da edição pelo manifesto — nunca por caminho manual (R1)."""
    from isp_rag.ingestion.sources import isp_urls

    url = isp_urls(ano).get("resultado_final")
    if not url:
        raise KeyError(f"edição {ano} não tem 'resultado_final' no registro de fontes")

    entrada = Manifest(settings.raw_dir / "manifest.json").by_url(url)
    if entrada is None:
        raise FileNotFoundError(
            f"planilha da edição {ano} não foi coletada. Rode antes:\n"
            f"  python -m isp_rag.ingestion.fetch_isp --year {ano}"
        )
    return settings.raw_dir / entrada.filename, entrada.url
