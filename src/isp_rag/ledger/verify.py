"""Verificação do Ledger contra a fonte publicada (spec §2.4).

O que é honestamente verificável está delimitado em plan.md §7.2. Aqui a
verificação é de CONSISTÊNCIA INTERNA: a carga preservou o que a planilha diz,
e o resultado do ente é coerente com os indicadores que o compõem.

O recálculo do conceito final a partir dos indicadores exige a tabela de
combinação publicada (aba `Combinação de Resultados`), ainda não carregada —
esses casos retornam `nao_reproduzivel`, não um palpite.
"""

from dataclasses import dataclass
from typing import Literal

import psycopg

from isp_rag.config import settings

Status = Literal["ok", "divergente", "nao_reproduzivel"]

# Perfil atuarial ↔ conceito (Portaria SPREV 14.762/2020).
PERFIL_POR_CONCEITO = {"D": "I", "C": "II", "B": "III", "A": "IV"}


@dataclass
class Verificacao:
    cnpj: str
    edicao_ano: int
    nivel: str
    alvo: str
    publicado: str | None
    recalculado: str | None
    status: Status
    motivo: str | None = None


def verificar_perfil_atuarial(ano: int, dsn: str | None = None) -> list[Verificacao]:
    """O perfil atuarial é função direta do conceito. Divergência aqui indica
    erro de carga ou inconsistência na própria planilha."""
    achados: list[Verificacao] = []
    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cnpj, conceito, perfil_atuarial FROM isp_resultado WHERE edicao_ano = %s",
            (ano,),
        )
        for cnpj, conceito, perfil in cur.fetchall():
            esperado = PERFIL_POR_CONCEITO.get(conceito)
            if perfil is None or perfil == "None":
                achados.append(
                    Verificacao(cnpj, ano, "final", "PERFIL", None, esperado, "nao_reproduzivel",
                                "perfil não publicado nesta edição")
                )
            elif perfil != esperado:
                achados.append(
                    Verificacao(cnpj, ano, "final", "PERFIL", perfil, esperado, "divergente",
                                f"conceito {conceito} implica perfil {esperado}")
                )
    return achados


def verificar_cobertura_indicadores(ano: int, dsn: str | None = None) -> list[Verificacao]:
    """Todo ente com resultado deve ter os indicadores da edição.

    Falta de indicador é lacuna de dado, não erro — a fonte às vezes não publica
    um componente para determinado ente.
    """
    achados: list[Verificacao] = []
    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT r.cnpj, count(c.indicador) AS n
                 FROM isp_resultado r
                 LEFT JOIN isp_componente c
                        ON c.cnpj = r.cnpj AND c.edicao_ano = r.edicao_ano
                WHERE r.edicao_ano = %s
                GROUP BY r.cnpj""",
            (ano,),
        )
        linhas = cur.fetchall()

    if not linhas:
        return achados

    esperado = max(n for _, n in linhas)
    for cnpj, n in linhas:
        if n < esperado:
            achados.append(
                Verificacao(cnpj, ano, "indicador", "COBERTURA", str(n), str(esperado),
                            "nao_reproduzivel", f"{esperado - n} indicador(es) sem publicação")
            )
    return achados


def verificar_escala(ano: int, dsn: str | None = None) -> list[Verificacao]:
    """As duas escalas não podem se misturar: indicador parcial é A/B/C, o
    conceito final vai de A a D."""
    achados: list[Verificacao] = []
    with psycopg.connect(dsn or settings.postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT letra FROM isp_componente WHERE edicao_ano=%s AND letra IS NOT NULL",
            (ano,),
        )
        for (letra,) in cur.fetchall():
            if letra not in ("A", "B", "C"):
                achados.append(
                    Verificacao("-", ano, "indicador", "ESCALA", letra, "A|B|C", "divergente",
                                "indicador parcial fora da escala de três níveis")
                )

        cur.execute("SELECT DISTINCT conceito FROM isp_resultado WHERE edicao_ano = %s", (ano,))
        for (conceito,) in cur.fetchall():
            if conceito not in ("A", "B", "C", "D"):
                achados.append(
                    Verificacao("-", ano, "final", "ESCALA", conceito, "A|B|C|D", "divergente",
                                "conceito final fora da escala de quatro níveis")
                )
    return achados


def verificar_edicao(ano: int, dsn: str | None = None) -> list[Verificacao]:
    return (
        verificar_escala(ano, dsn)
        + verificar_perfil_atuarial(ano, dsn)
        + verificar_cobertura_indicadores(ano, dsn)
    )


def main() -> int:
    import argparse
    from collections import Counter

    p = argparse.ArgumentParser(description="Verifica o Ledger contra a fonte publicada.")
    p.add_argument("--year", type=int, required=True)
    args = p.parse_args()

    achados = verificar_edicao(args.year)
    contagem = Counter(a.status for a in achados)

    print(f"verificação da edição {args.year}")
    print(f"  divergentes      : {contagem['divergente']}")
    print(f"  não reproduzíveis: {contagem['nao_reproduzivel']}")

    for a in achados[:10]:
        print(f"    [{a.status}] {a.cnpj} {a.alvo}: publicado={a.publicado} "
              f"esperado={a.recalculado} — {a.motivo}")
    if len(achados) > 10:
        print(f"    ... e mais {len(achados) - 10}")

    # Divergência é material de análise, não falha de execução (spec §2.4).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
