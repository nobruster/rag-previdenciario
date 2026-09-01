"""Carga do grafo.

Princípio: schema ambicioso, carga incremental (spec §5.3). A ontologia é
completa desde o início; a v2 popula o subgrafo edição → critério → indicador,
que é o obtenível a partir do que já está no Ledger e nos documentos de
metodologia.
"""

from dataclasses import dataclass
from pathlib import Path

import psycopg
from neo4j import Driver, GraphDatabase

from isp_rag.config import settings

ONTOLOGY = Path(__file__).with_name("ontology.cypher")

# Descrição de cada dimensão (critério) do ISP. Vem do relatório oficial —
# mapeamento de estrutura por leitura do documento, não dado por cópia manual.
CRITERIOS = {
    "gestao_transparencia": (
        "Gestão e transparência do RPPS: regularidade, envio de informações e "
        "modernização da gestão."
    ),
    "financas_liquidez": (
        "Situação financeira e liquidez: suficiência, acumulação de recursos e "
        "resultado do equacionamento."
    ),
    "atuaria": (
        "Situação atuarial: cobertura previdenciária, sustentabilidade das "
        "provisões e reforma do regime."
    ),
}

NORMAS_REGULADORAS = {
    2025: ("portaria-srpc-mps-2416-2025", "Portaria SRPC/MPS nº 2.416/2025", "2.416", 2025),
}


@dataclass
class BrainReport:
    edicoes: int = 0
    criterios: int = 0
    indicadores: int = 0
    entes: int = 0
    arestas: int = 0

    def __str__(self) -> str:
        return (
            f"grafo: {self.edicoes} edições, {self.criterios} critérios, "
            f"{self.indicadores} indicadores, {self.entes} entes, "
            f"{self.arestas} arestas"
        )


def get_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def load_ontology(driver: Driver | None = None) -> None:
    """Aplica constraints e índices. Idempotente."""
    fechar = driver is None
    driver = driver or get_driver()
    try:
        comandos = [
            c.strip()
            for c in ONTOLOGY.read_text(encoding="utf-8").split(";")
            if c.strip() and not all(x.strip().startswith("//") for x in c.strip().splitlines())
        ]
        with driver.session() as s:
            for cmd in comandos:
                s.run(cmd)
    finally:
        if fechar:
            driver.close()


def load_metodologia(ano: int, driver: Driver | None = None) -> BrainReport:
    """Carrega Edicao -[:COMPOE]-> Criterio -[:COMPOE]-> Indicador.

    A estrutura vem do Ledger, que por sua vez veio da planilha oficial: a
    dimensão e o indicador de cada componente são dado publicado, não inferência.
    """
    fechar = driver is None
    driver = driver or get_driver()
    rel = BrainReport()

    try:
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute(
                "SELECT ano, regime_metodologico, url_fonte, n_entes_avaliados "
                "FROM edicao WHERE ano = %s",
                (ano,),
            )
            linha = k.fetchone()
            if not linha:
                raise ValueError(f"edição {ano} não está no Ledger — carregue-a antes")
            _, regime, url_fonte, n_entes = linha

            k.execute(
                "SELECT DISTINCT dimensao, indicador FROM isp_componente "
                "WHERE edicao_ano = %s ORDER BY dimensao, indicador",
                (ano,),
            )
            componentes = k.fetchall()

        with driver.session() as s:
            s.run(
                """MERGE (e:Edicao {ano: $ano})
                   SET e.regime_metodologico = $regime,
                       e.url_fonte = $url,
                       e.n_entes = $n_entes""",
                ano=ano, regime=regime, url=url_fonte, n_entes=n_entes,
            )
            rel.edicoes = 1

            if ano in NORMAS_REGULADORAS:
                ident, nome, numero, ano_norma = NORMAS_REGULADORAS[ano]
                s.run(
                    """MERGE (n:Norma {identificador: $ident})
                       SET n.tipo = 'portaria', n.numero = $numero,
                           n.ano = $ano_norma, n.nome = $nome
                       WITH n MATCH (e:Edicao {ano: $ano})
                       MERGE (n)-[:REGULAMENTA]->(e)""",
                    ident=ident, nome=nome, numero=numero, ano_norma=ano_norma, ano=ano,
                )
                rel.arestas += 1

            for dimensao, indicador in componentes:
                s.run(
                    """MATCH (e:Edicao {ano: $ano})
                       MERGE (c:Criterio {edicao_ano: $ano, nome: $dim})
                         ON CREATE SET c.descricao = $desc
                       MERGE (e)-[:COMPOE]->(c)
                       MERGE (i:Indicador {edicao_ano: $ano, nome: $ind})
                         ON CREATE SET i.dimensao = $dim
                       MERGE (c)-[:COMPOE]->(i)""",
                    ano=ano, dim=dimensao, ind=indicador,
                    desc=CRITERIOS.get(dimensao, ""),
                )
                rel.arestas += 2

            resumo = s.run(
                """MATCH (c:Criterio {edicao_ano: $ano}) WITH count(c) AS nc
                   MATCH (i:Indicador {edicao_ano: $ano}) RETURN nc, count(i) AS ni""",
                ano=ano,
            ).single()
            rel.criterios, rel.indicadores = resumo["nc"], resumo["ni"]
    finally:
        if fechar:
            driver.close()

    return rel


def load_entes(ano: int, limite: int | None = None, driver: Driver | None = None) -> int:
    """Entes avaliados na edição, para o grafo poder falar de um município.

    `limite` existe para desenvolvimento: 2133 nós é carga rápida, mas em teste
    convém menos.
    """
    fechar = driver is None
    driver = driver or get_driver()
    try:
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute(
                "SELECT cnpj, ente_nome, uf FROM isp_resultado_v WHERE edicao_ano = %s"
                + (" LIMIT %s" if limite else ""),
                (ano, limite) if limite else (ano,),
            )
            entes = k.fetchall()

        with driver.session() as s:
            s.run(
                """UNWIND $entes AS e
                   MERGE (n:Ente {cnpj: e[0]})
                   SET n.nome = e[1], n.uf = e[2]""",
                entes=[list(e) for e in entes],
            )
        return len(entes)
    finally:
        if fechar:
            driver.close()


# ---------------------------------------------------------------------------
# Stubs documentados — v2+
# ---------------------------------------------------------------------------
def load_cadeia_normativa(driver: Driver | None = None) -> None:
    """TODO v2+: arestas REVOGA e ALTERA entre normas.

    Fonte: cláusulas de revogação no texto ("Revoga-se a Portaria X") e as
    marcações de alteração já detectadas pelo chunker — 99 chunks da Portaria
    1.467 estão marcados como `alterado`, com a norma alteradora no próprio
    texto ("Redação dada pela Portaria MPS nº 1.180, de 2024").

    Requer parsing das disposições finais e das notas de alteração.
    """
    raise NotImplementedError("cadeia normativa entra na v2+ (spec §5.3)")


def load_linhagem(driver: Driver | None = None) -> None:
    """TODO v2+: Dispositivo -[:CONSOME_CAMPO]-> Indicador.

    É a rastreabilidade normativa do sistema de indicadores — governança de
    dados expressa em grafo (spec §5.3). Liga o dispositivo que institui uma
    obrigação ao indicador que a mede.

    Requer mapear cada indicador ao artigo que o fundamenta, o que hoje só
    existe em prosa no relatório técnico.
    """
    raise NotImplementedError("linhagem dispositivo↔indicador entra na v2+ (spec §5.3)")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Carrega o grafo do Brain.")
    p.add_argument("--ontology", action="store_true", help="aplica constraints e índices")
    p.add_argument(
        "--metodologia", type=int, metavar="ANO", help="carrega edição→critério→indicador"
    )
    p.add_argument("--entes", type=int, metavar="ANO", help="carrega os entes da edição")
    args = p.parse_args()

    if not any([args.ontology, args.metodologia, args.entes]):
        p.error("escolha ao menos uma ação")

    with get_driver() as driver:
        if args.ontology:
            load_ontology(driver)
            print("ontologia aplicada")
        if args.metodologia:
            print(load_metodologia(args.metodologia, driver))
        if args.entes:
            print(f"entes carregados: {load_entes(args.entes, driver=driver)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
