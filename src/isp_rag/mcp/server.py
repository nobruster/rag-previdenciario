"""Servidor MCP — o ISP-RAG como ferramenta de agente.

R2 vale aqui igual à API: toda tool retorna as fontes citadas. Um agente que
recebe afirmação sem fonte propaga o problema adiante, com menos supervisão
humana que um usuário lendo a resposta na tela.

As tools reusam as MESMAS funções da API (T10) — divergência entre o que a API
responde e o que o MCP responde seria um bug difícil de perceber.
"""

import logging
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from isp_rag.config import settings

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("isp_rag.mcp")

mcp = FastMCP("isp-rag")

_estado: dict[str, Any] = {}


def _engines() -> dict[str, Any]:
    """Constrói as engines uma vez, tolerando serviço ausente (como a T10)."""
    if _estado:
        return _estado

    def tentar(nome, construtor):
        try:
            return construtor()
        except Exception as exc:
            log.warning("engine '%s' indisponível: %s", nome, exc)
            return None

    from isp_rag.api.main import brain_disponivel
    from isp_rag.ledger.engine import build_ledger_engine
    from isp_rag.query.router import _memory_query_engine

    _estado["brain_enabled"] = brain_disponivel()
    _estado["ledger"] = tentar("ledger", build_ledger_engine)
    _estado["memory"] = tentar("memory", _memory_query_engine)
    return _estado


def _erro(codigo: str, detalhe: str, **extra) -> dict:
    """Erro estruturado. Um agente lida melhor com isso do que com stack trace."""
    return {"error": codigo, "detail": detalhe, **extra}


@mcp.tool()
def consultar_isp(pergunta: str, data_referencia: str | None = None) -> dict:
    """Responde perguntas sobre a previdência pública brasileira (RPPS).

    Cruza três fontes: as notas do Índice de Situação Previdenciária (ISP) por
    ente e edição, o texto das normas que regulamentam os RPPS (Portaria MTP
    1.467/2022, Leis 9.717/1998 e 10.887/2004, Emendas Constitucionais), e o
    grafo de relações entre edições, critérios e indicadores.

    Use para qualquer pergunta sobre RPPS: notas do ISP, exigências normativas,
    prazos, requisitos ou evolução entre edições. Toda resposta cita as fontes.

    Se não houver base na documentação indexada, a ferramenta RECUSA
    explicitamente em vez de inventar — uma recusa aqui é resposta válida, não
    falha. Antes de insistir numa reformulação, consulte `verificar_cobertura`
    para saber se o assunto está no corpus.

    Args:
        pergunta: a pergunta em português.
        data_referencia: data ISO (AAAA-MM-DD) para filtrar dispositivos
            vigentes naquela data. Opcional.
    """
    from fastapi.testclient import TestClient

    from isp_rag.api.main import app

    corpo: dict[str, Any] = {"question": pergunta}
    if data_referencia:
        try:
            corpo["reference_date"] = str(date.fromisoformat(data_referencia))
        except ValueError:
            return _erro("data_invalida", f"use o formato AAAA-MM-DD: {data_referencia!r}")

    try:
        with TestClient(app) as client:
            r = client.post("/query", json=corpo)
    except Exception as exc:
        return _erro("falha_interna", str(exc)[:300])

    if r.status_code == 422:
        return _erro("pergunta_invalida", "a pergunta precisa ter entre 3 e 2000 caracteres")
    if r.status_code == 503:
        return _erro("servico_indisponivel", "nenhuma engine disponível no momento")
    if r.status_code != 200:
        return _erro("falha_interna", f"HTTP {r.status_code}", corpo=r.text[:300])

    return r.json()


@mcp.tool()
def nota_do_ente(identificador: str, ano: int) -> dict:
    """Consulta direta do conceito de um RPPS no ISP, com a memória de cálculo.

    Mais rápido e preciso que `consultar_isp` quando você já sabe exatamente
    qual ente e qual ano quer.

    O conceito final vai de A (melhor) a D (pior) — não existe E. A memória de
    cálculo traz a letra de cada indicador parcial, que usa escala A/B/C, de
    três níveis: são escalas DIFERENTES e não devem ser comparadas entre si.

    Se o nome casar com vários entes, devolve a lista de candidatos em vez de
    escolher um — a desambiguação é sua.

    Args:
        identificador: CNPJ (só dígitos) ou nome do município, ex.: "Campinas".
        ano: edição do ISP, ex.: 2025.
    """
    import re

    from isp_rag.ledger.engine import run_sql

    digitos = re.sub(r"\D", "", identificador)
    try:
        if len(digitos) >= 8:
            linhas = run_sql(
                "SELECT cnpj, ente_nome, uf, conceito, perfil_atuarial, grupo, subgrupo, "
                "regime_metodologico, url_fonte FROM isp_resultado_v "
                f"WHERE edicao_ano = {ano} AND cnpj = '{digitos.zfill(14)}'"
            )
        else:
            termo = identificador.replace("'", "''")
            linhas = run_sql(
                "SELECT cnpj, ente_nome, uf, conceito, perfil_atuarial, grupo, subgrupo, "
                "regime_metodologico, url_fonte FROM isp_resultado_v "
                f"WHERE edicao_ano = {ano} "
                f"AND unaccent(ente_nome) ILIKE unaccent('%{termo}%') ORDER BY ente_nome"
            )
    except Exception as exc:
        return _erro("falha_na_consulta", str(exc)[:300])

    if not linhas:
        return _erro(
            "ente_nao_encontrado",
            f"nenhum ente casa com {identificador!r} na edição {ano}",
            sugestoes=["confira o ano com listar_edicoes", "tente parte do nome do município"],
        )

    if len(linhas) > 1:
        return {
            "ambiguo": True,
            "detail": f"{len(linhas)} entes casam com {identificador!r} — escolha um",
            "candidatos": [
                {"cnpj": c, "nome": n, "uf": uf, "conceito": co} for c, n, uf, co, *_ in linhas
            ],
        }

    cnpj, nome, uf, conceito, perfil, grupo, subgrupo, regime, url = linhas[0]
    componentes = run_sql(
        "SELECT dimensao, indicador, letra FROM isp_componente "
        f"WHERE edicao_ano = {ano} AND cnpj = '{cnpj}' ORDER BY dimensao, indicador"
    )

    return {
        "cnpj": cnpj,
        "ente": nome,
        "uf": uf,
        "edicao": ano,
        "conceito": conceito,
        "escala_conceito": "A (melhor) a D (pior); não existe E",
        "perfil_atuarial": perfil,
        "grupo": grupo,
        "subgrupo": subgrupo,
        "regime_metodologico": regime,
        "memoria_de_calculo": [
            {"dimensao": d, "indicador": i, "letra": ltr, "escala": "A/B/C"}
            for d, i, ltr in componentes
        ],
        "sources": [
            {"engine": "ledger", "ref": f"isp_resultado, ed. {ano}", "url": url}
        ],
    }


@mcp.tool()
def buscar_norma(
    termo: str,
    data_referencia: str | None = None,
    incluir_revogados: bool = False,
) -> dict:
    """Busca no corpus normativo dos RPPS.

    Retorna os dispositivos (artigos) mais relevantes, com hierarquia, situação
    de vigência e URL da fonte.

    Por padrão devolve apenas dispositivos VIGENTES: responder com norma
    revogada é tão ruim quanto inventar. Se a busca citar um artigo específico
    (ex.: "art. 241"), faz consulta EXATA em vez de semântica.

    ATENÇÃO: a busca vetorial sempre devolve os dispositivos mais próximos,
    mesmo quando o termo não existe no corpus — "os 5 mais parecidos" não
    significa "5 relevantes". Para saber se o assunto está de fato coberto, use
    `verificar_cobertura`. Quem decide entre responder e recusar é
    `consultar_isp`, na síntese, não esta busca.

    Args:
        termo: o que buscar, ex.: "requisitos do CRP" ou "art. 241".
        data_referencia: data ISO (AAAA-MM-DD) para vigência naquela data.
        incluir_revogados: inclui dispositivos revogados. Use só para pergunta
            explicitamente histórica.
    """
    from isp_rag.memory.engine import buscar

    ref: date | None = None
    if data_referencia:
        try:
            ref = date.fromisoformat(data_referencia)
        except ValueError:
            return _erro("data_invalida", f"use o formato AAAA-MM-DD: {data_referencia!r}")

    try:
        resultados = buscar(termo, reference_date=ref, incluir_revogados=incluir_revogados)
    except Exception as exc:
        return _erro("falha_na_busca", str(exc)[:300])

    if not resultados:
        return _erro(
            "sem_resultados",
            f"nenhum dispositivo vigente encontrado para {termo!r}",
            sugestoes=["use verificar_cobertura para saber se o assunto está no corpus"],
        )

    return {
        "termo": termo,
        "origem": resultados[0].origem,
        "dispositivos": [
            {
                "norma": r.chunk.norma,
                "artigo": r.chunk.artigo,
                "hierarquia": r.chunk.hierarquia,
                "situacao": r.chunk.situacao,
                "texto": r.chunk.text_raw[:1500],
                "url": r.chunk.url,
            }
            for r in resultados
        ],
        "sources": [
            {
                "engine": "memory",
                "ref": f"{r.chunk.norma}, art. {r.chunk.artigo}",
                "url": r.chunk.url,
            }
            for r in resultados
        ],
    }


@mcp.tool()
def listar_edicoes() -> dict:
    """Lista as edições do ISP disponíveis no sistema.

    Use ANTES de perguntar sobre um ano específico, para saber o que está
    carregado e evitar pergunta sobre edição ausente.

    Atenção ao `regime_metodologico`: edições de regimes diferentes NÃO são
    comparáveis. Até 2024 o conceito vinha de tercil anual (nota relativa à
    distribuição do ano); de 2025 em diante vem de cortes fixos sobre a
    distribuição histórica (nota absoluta), com três indicadores novos. Uma
    variação de conceito entre esses períodos não significa, por si só,
    mudança de desempenho — a régua mudou.
    """
    from isp_rag.ledger.engine import run_sql

    try:
        linhas = run_sql(
            "SELECT e.ano, e.regime_metodologico, count(r.cnpj), e.url_fonte "
            "FROM edicao e LEFT JOIN isp_resultado r ON r.edicao_ano = e.ano "
            "GROUP BY e.ano, e.regime_metodologico, e.url_fonte ORDER BY e.ano DESC"
        )
    except Exception as exc:
        return _erro("falha_na_consulta", str(exc)[:300])

    if not linhas:
        return _erro("sem_edicoes", "nenhuma edição carregada no Ledger")

    return {
        "edicoes": [
            {"ano": a, "regime_metodologico": rg, "n_entes": n, "url_fonte": u}
            for a, rg, n, u in linhas
        ],
        "nota_comparabilidade": (
            "Edições de regimes metodológicos diferentes não são comparáveis."
        ),
        "sources": [
            {"engine": "ledger", "ref": f"isp_resultado, ed. {a}", "url": u}
            for a, _, _, u in linhas
        ],
    }


@mcp.tool()
def verificar_cobertura(termo: str) -> dict:
    """O corpus indexado cobre este assunto?

    Serve para distinguir, ANTES de perguntar, o que o sistema pode responder
    do que ele vai recusar por ausência de base. Uma recusa de `consultar_isp`
    sobre termo não coberto é comportamento correto, não defeito — reformular
    a pergunta não vai ajudar.

    Args:
        termo: palavra ou sigla, ex.: "DIPR", "CRP", "compensação".
    """
    from isp_rag.memory.cobertura import cobertura_de

    try:
        c = cobertura_de(termo)
    except Exception as exc:
        return _erro("falha_na_consulta", str(exc)[:300])

    if not c.coberto:
        veredito = "ausente"
    elif c.n_chunks <= 2:
        veredito = "raso"
    else:
        veredito = "coberto"

    return {
        "termo": c.termo,
        "veredito": veredito,
        "n_chunks": c.n_chunks,
        "artigos": c.artigos[:20],
        "sources": [{"engine": "memory", "ref": "corpus normativo indexado"}],
    }


def main() -> None:
    _engines()
    mcp.run()


if __name__ == "__main__":
    main()
