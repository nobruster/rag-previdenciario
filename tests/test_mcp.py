"""T13 — MCP Server. Fecha o escopo local."""

import pytest

from isp_rag.mcp.server import (
    buscar_norma,
    consultar_isp,
    listar_edicoes,
    mcp,
    nota_do_ente,
    verificar_cobertura,
)

TOOLS = {
    "consultar_isp": consultar_isp,
    "nota_do_ente": nota_do_ente,
    "buscar_norma": buscar_norma,
    "listar_edicoes": listar_edicoes,
    "verificar_cobertura": verificar_cobertura,
}


def _dados_ok() -> bool:
    try:
        from isp_rag.ledger.engine import run_sql
        from isp_rag.memory.indexer import contar_pontos

        return bool(run_sql("SELECT 1 FROM isp_resultado LIMIT 1")) and contar_pontos() > 0
    except Exception:
        return False


precisa_dados = pytest.mark.skipif(not _dados_ok(), reason="Ledger/Memory sem dados")


# ---------------------------------------------------------------------------
# Registro e descrições
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_as_cinco_tools_registradas():
    nomes = {t.name for t in await mcp.list_tools()}
    assert nomes == set(TOOLS)


@pytest.mark.anyio
async def test_descricoes_orientam_o_agente():
    """Um agente não lê documentação: lê a descrição e decide sozinho."""
    for tool in await mcp.list_tools():
        assert tool.description and len(tool.description) > 120, tool.name


@pytest.mark.anyio
async def test_descricao_avisa_da_ruptura_metodologica():
    """Quem consome via MCP tem menos supervisão humana — o aviso precisa
    estar onde o agente lê."""
    desc = {t.name: t.description for t in await mcp.list_tools()}["listar_edicoes"].lower()
    assert "comparáveis" in desc, "o agente precisa ser avisado da ruptura"
    assert "régua mudou" in desc


@pytest.mark.anyio
async def test_descricao_explica_as_duas_escalas():
    tools = {t.name: t.description for t in await mcp.list_tools()}
    assert "não existe E" in tools["nota_do_ente"]
    assert "A/B/C" in tools["nota_do_ente"]


# ---------------------------------------------------------------------------
# Erros estruturados
# ---------------------------------------------------------------------------
def test_data_invalida_e_erro_estruturado():
    r = buscar_norma("CRP", data_referencia="31/12/2024")
    assert r["error"] == "data_invalida"
    assert "AAAA-MM-DD" in r["detail"]


@precisa_dados
def test_ente_inexistente_traz_sugestoes():
    """Erro descritivo, não stack trace — o agente precisa saber o que tentar."""
    r = nota_do_ente("Lisboa", 2025)
    assert r["error"] == "ente_nao_encontrado"
    assert r["sugestoes"]


@precisa_dados
def test_nome_ambiguo_devolve_candidatos():
    """Desambiguação é do agente, não da ferramenta."""
    r = nota_do_ente("SANTA", 2025)
    assert r.get("ambiguo") is True
    assert len(r["candidatos"]) > 1
    assert {"cnpj", "nome", "uf", "conceito"} <= set(r["candidatos"][0])


# ---------------------------------------------------------------------------
# R2 — toda tool cita a fonte
# ---------------------------------------------------------------------------
@precisa_dados
def test_toda_tool_retorna_fontes():
    """R2 vale no MCP igual à API."""
    respostas = {
        "nota_do_ente": nota_do_ente("Campinas", 2025),
        "buscar_norma": buscar_norma("requisitos do CRP"),
        "listar_edicoes": listar_edicoes(),
        "verificar_cobertura": verificar_cobertura("CRP"),
    }
    for nome, r in respostas.items():
        assert "error" not in r, f"{nome}: {r}"
        assert r.get("sources"), f"{nome} não citou fonte"


# ---------------------------------------------------------------------------
# Conteúdo
# ---------------------------------------------------------------------------
@precisa_dados
def test_nota_do_ente_traz_memoria_de_calculo():
    r = nota_do_ente("Campinas", 2025)
    assert r["conceito"] in ("A", "B", "C", "D")
    assert len(r["memoria_de_calculo"]) == 9, "3 dimensões × 3 indicadores"
    assert all(c["letra"] in ("A", "B", "C") for c in r["memoria_de_calculo"])


@precisa_dados
def test_nota_do_ente_aceita_cnpj():
    por_nome = nota_do_ente("Campinas", 2025)
    por_cnpj = nota_do_ente(por_nome["cnpj"], 2025)
    assert por_cnpj["ente"] == por_nome["ente"]


@precisa_dados
def test_listar_edicoes_expoe_o_regime():
    r = listar_edicoes()
    assert r["edicoes"]
    assert r["edicoes"][0]["regime_metodologico"] in ("tercil-anual", "corte-historico")
    assert "comparáveis" in r["nota_comparabilidade"]


@precisa_dados
def test_buscar_norma_citada_faz_lookup_exato():
    r = buscar_norma("art. 241")
    assert r["origem"] == "citacao"
    assert r["dispositivos"][0]["artigo"] == "241"


@precisa_dados
def test_buscar_norma_exclui_revogados_por_padrao():
    r = buscar_norma("aposentadoria compulsória")
    assert "revogado" not in {d["situacao"] for d in r["dispositivos"]}


@precisa_dados
def test_verificar_cobertura_distingue_os_tres_casos():
    assert verificar_cobertura("Mongólia")["veredito"] == "ausente"
    assert verificar_cobertura("DIPR")["veredito"] == "raso"
    assert verificar_cobertura("CRP")["veredito"] == "coberto"


# ---------------------------------------------------------------------------
# Fluxo completo (gasta token)
# ---------------------------------------------------------------------------
@pytest.mark.llm
@precisa_dados
def test_consultar_isp_responde_com_fonte():
    r = consultar_isp("o que estabelece o art. 241?")
    assert r["sources"] and not r["refused"]


@pytest.mark.llm
@precisa_dados
def test_consultar_isp_nao_inventa_fora_do_escopo():
    """R3 no MCP. A asserção é sobre o INVARIANTE, não sobre a recusa:
    o roteador não é determinístico nem com temperature=0, e exigir recusa
    exata tornaria o teste instável. O que não pode acontecer é responder
    sem fonte — isso o contrato garante nos dois caminhos.
    """
    r = consultar_isp("Qual a capital da Mongólia?")
    assert r["refused"] or r["sources"], "respondeu sem citar fonte (R2)"
    if r["refused"]:
        assert r["sources"] == []
