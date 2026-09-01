"""Text-to-SQL sobre o Ledger.

Duas defesas estruturais, não confiadas ao LLM (plan.md §7.1):

1. O modelo enxerga a VIEW `isp_resultado_v`, não a tabela crua — é impossível
   ler uma nota sem que o regime metodológico esteja disponível.
2. `checar_regimes()` roda depois da execução e antes da síntese, sem LLM: se o
   resultado abrange mais de um regime, devolve a ressalva para a T09 injetar
   no contexto.
"""

import re
from typing import Any

import psycopg
from llama_index.core import SQLDatabase
from llama_index.core.query_engine import NLSQLTableQueryEngine
from sqlalchemy import create_engine

from isp_rag.config import settings
from isp_rag.llm import llama_embedding, llama_llm

TABELAS = ["isp_resultado_v", "isp_componente", "ente_grupo", "edicao", "regime"]

# SQL de escrita nunca deve sair de um Text-to-SQL, nem por acidente nem por
# prompt injection vinda do texto de uma pergunta.
PROIBIDO = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|COPY|CREATE|MERGE)\b",
    re.IGNORECASE,
)
COMECO_VALIDO = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
ANO_RE = re.compile(r"\b(20[1-9]\d)\b")


class SQLSafetyError(RuntimeError):
    """SQL gerado que não é somente leitura."""


CONTEXTO = {
    "isp_resultado_v": (
        "Resultado do ISP por ente e edição, já com ente, UF, grupo/subgrupo e "
        "regime metodológico. USE ESTA VIEW, nunca isp_resultado direto.\n"
        "- conceito: classificação final, CHAR(1) de 'A' (melhor) a 'D' (pior). "
        "NÃO existe conceito 'E'.\n"
        "- perfil_atuarial: I=conceito D, II=C, III=B, IV=A.\n"
        "- edicao_ano: chave temporal. Comparar edições = filtrar ou agrupar por ela.\n"
        "- regime_metodologico: 'tercil-anual' (2017-2024) ou 'corte-historico' "
        "(2025+). Conceitos de regimes diferentes NÃO são comparáveis — a régua "
        "mudou, não só o desempenho. Em consulta que cruze edições, traga esta "
        "coluna no SELECT.\n"
        "- grupo: MAIÚSCULAS, um de exatamente: 'ESTADO/DF', 'GRANDE PORTE', "
        "'MÉDIO PORTE', 'PEQUENO PORTE', 'NÃO CLASSIFICADO'. Nunca escreva "
        "'Grande Porte' — a comparação é sensível a caixa e não casaria.\n"
        "- subgrupo: 'MENOR MATURIDADE', 'MAIOR MATURIDADE', 'ESTADO/DF' ou "
        "'NÃO CLASSIFICADO'. A classificação é atribuída DENTRO do "
        "grupo/subgrupo, então média nacional de conceito costuma ser a "
        "pergunta errada.\n"
        "- ente_nome: MAIÚSCULAS e com a UF no fim, no formato 'CAMPINAS - SP'. "
        "NUNCA use igualdade com o nome puro ('Campinas') — não casa. Para "
        "buscar por município, use SEMPRE:\n"
        "    unaccent(ente_nome) ILIKE unaccent('%CAMPINAS%')\n"
        "- cnpj: 14 dígitos, sem pontuação."
    ),
    "isp_componente": (
        "Memória de cálculo: a classificação de cada indicador parcial que compõe "
        "o resultado do ente.\n"
        "- letra: 'A', 'B' ou 'C' — TRÊS níveis. Escala DIFERENTE do conceito "
        "final (A-D). Nunca compare as duas.\n"
        "- dimensao: 'gestao_transparencia', 'financas_liquidez' ou 'atuaria'.\n"
        "- indicador: nome do indicador parcial (ex.: 'cobertura_previdenciaria').\n"
        "- valor: numérico, frequentemente NULL — a fonte publica a letra, não o "
        "valor bruto."
    ),
    "ente_grupo": "Porte e maturidade do ente naquela edição (o ente pode migrar de grupo).",
    "edicao": (
        "Edição anual do ISP (2017-2025), com url_fonte, regime_metodologico e "
        "n_entes_avaliados (universo do ano — o tercil é relativo a ele).\n"
        "Para 'quantos entes por edição', leia n_entes_avaliados direto desta "
        "tabela ou conte em isp_resultado_v. NÃO faça JOIN de edicao com "
        "isp_componente para contar entes: há ~9 componentes por ente e a "
        "contagem sai multiplicada."
    ),
    "regime": (
        "Regime metodológico. texto_ressalva é o aviso a servir quando uma "
        "resposta cruza regimes diferentes."
    ),
}


def _sql_database() -> SQLDatabase:
    engine = create_engine(settings.postgres_dsn)
    return SQLDatabase(
        engine,
        include_tables=TABELAS,
        view_support=True,  # isp_resultado_v é view
        custom_table_info=CONTEXTO,
    )


def build_ledger_engine() -> NLSQLTableQueryEngine:
    """Engine de consulta em linguagem natural sobre o Ledger.

    O embed_model é passado explicitamente porque o LlamaIndex, se não receber,
    resolve um default global que lê OPENAI_API_KEY do ambiente — e a chave
    deste projeto vive no .env, lido apenas por `settings` (R7). Sem isto a
    construção falha mesmo com a chave configurada.
    """
    return NLSQLTableQueryEngine(
        sql_database=_sql_database(),
        tables=TABELAS,
        llm=llama_llm(),
        embed_model=llama_embedding(),
    )


def get_sql(response: Any) -> str | None:
    """SQL gerado, extraído dos metadados. T11 mede execution match com isto."""
    meta = getattr(response, "metadata", None) or {}
    return meta.get("sql_query") or meta.get("sql")


def assert_somente_leitura(sql: str) -> None:
    """Barra qualquer coisa que não seja consulta."""
    if not sql or not sql.strip():
        raise SQLSafetyError("SQL vazio")
    limpo = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL)
    if not COMECO_VALIDO.match(limpo):
        raise SQLSafetyError(f"SQL não começa com SELECT/WITH: {sql[:120]}")
    if PROIBIDO.search(limpo):
        raise SQLSafetyError(f"SQL contém comando de escrita: {sql[:120]}")
    if ";" in limpo.strip().rstrip(";"):
        raise SQLSafetyError(f"múltiplos statements não são permitidos: {sql[:120]}")


def run_sql(sql: str, dsn: str | None = None) -> list[tuple]:
    """Executa SQL de leitura e devolve o resultset.

    Usado pelo runner de avaliação (T11) para comparar resultado do SQL gerado
    com o de referência — nunca comparar as strings.
    """
    assert_somente_leitura(sql)
    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql)
        return cur.fetchall()


def checar_regimes(resultset: list[tuple], sql: str = "", dsn: str | None = None) -> str | None:
    """Devolve a ressalva se a resposta cruza regimes metodológicos.

    Determinística, sem LLM. Olha os DADOS que voltaram, não a categoria da
    pergunta: o modo de falha mais provável não é "compare 2024 e 2025" — essa
    está protegida — mas "a situação do RPPS de X melhorou?", em que o SQL puxa
    a série inteira e a régua muda no meio sem ninguém pedir comparação.
    """
    anos: set[int] = set()
    for linha in resultset or []:
        for valor in linha:
            if isinstance(valor, int) and not isinstance(valor, bool) and 2017 <= valor <= 2099:
                anos.add(valor)
    anos |= {int(a) for a in ANO_RE.findall(sql or "")}
    if len(anos) < 2:
        return None

    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT r.id, r.texto_ressalva
                 FROM edicao e JOIN regime r ON r.id = e.regime_metodologico
                WHERE e.ano = ANY(%s)""",
            (sorted(anos),),
        )
        regimes = cur.fetchall()

    if len(regimes) < 2:
        return None
    return regimes[0][1]
