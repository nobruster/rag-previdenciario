"""T12 — o grafo. Fecha a tese do projeto."""

import pytest

from isp_rag.brain.engine import CypherSafetyError, assert_somente_leitura, run_cypher
from isp_rag.brain.loader import load_cadeia_normativa, load_linhagem


def _grafo_ok() -> bool:
    try:
        return bool(run_cypher("MATCH (e:Edicao) RETURN count(e) AS n")[0]["n"])
    except Exception:
        return False


precisa_grafo = pytest.mark.skipif(not _grafo_ok(), reason="grafo não carregado")


# ---------------------------------------------------------------------------
# Guarda somente-leitura
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (n:Evil)",
        "MATCH (n) DETACH DELETE n",
        "MATCH (e:Edicao) SET e.ano = 1999",
        "MERGE (n:Norma {identificador: 'x'})",
        "MATCH (n) REMOVE n.nome",
        "LOAD CSV FROM 'http://x' AS l RETURN l",
        "",
    ],
)
def test_escrita_no_grafo_e_bloqueada(cypher):
    with pytest.raises(CypherSafetyError):
        assert_somente_leitura(cypher)


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (e:Edicao) RETURN e",
        "MATCH (c:Criterio)-[:COMPOE]->(i:Indicador) RETURN c.nome, i.nome",
        "MATCH (n) RETURN count(n)",
    ],
)
def test_leitura_e_permitida(cypher):
    assert_somente_leitura(cypher)


def test_comentario_nao_esconde_escrita():
    with pytest.raises(CypherSafetyError):
        assert_somente_leitura("// inofensivo\nMATCH (n) DELETE n")


@precisa_grafo
def test_run_cypher_recusa_escrita():
    with pytest.raises(CypherSafetyError):
        run_cypher("CREATE (n:Teste)")


# ---------------------------------------------------------------------------
# Ontologia e carga
# ---------------------------------------------------------------------------
@precisa_grafo
def test_ontologia_aplicada_e_idempotente():
    from isp_rag.brain.loader import load_ontology

    load_ontology()
    load_ontology()  # segunda vez não pode duplicar constraint
    constraints = run_cypher("SHOW CONSTRAINTS YIELD name RETURN count(*) AS n")
    assert constraints[0]["n"] >= 6, "os 6 nós da ontologia precisam de constraint"


@precisa_grafo
def test_subgrafo_edicao_criterio_indicador():
    r = run_cypher(
        """MATCH (e:Edicao {ano: 2025})-[:COMPOE]->(c:Criterio)-[:COMPOE]->(i:Indicador)
           RETURN c.nome AS criterio, count(i) AS n ORDER BY criterio"""
    )
    assert len(r) == 3, "três dimensões: gestão, finanças e atuária"
    assert all(x["n"] == 3 for x in r), "cada dimensão tem três indicadores"


@precisa_grafo
def test_criterio_tem_chave_composta_por_edicao():
    """O mesmo nome pode ter definição diferente entre edições — é o que a
    pergunta de demonstração explora."""
    r = run_cypher(
        "MATCH (c:Criterio) RETURN c.edicao_ano AS ano, c.nome AS nome LIMIT 1"
    )
    assert r and r[0]["ano"] is not None, "sem edicao_ano, edições se misturam"


@precisa_grafo
def test_norma_regulamenta_edicao():
    r = run_cypher(
        "MATCH (n:Norma)-[:REGULAMENTA]->(e:Edicao {ano: 2025}) RETURN n.numero AS numero"
    )
    assert r, "a edição precisa da norma que a rege — é o que responde 'qual norma alterou'"


# ---------------------------------------------------------------------------
# Stubs da v2+
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fn", [load_cadeia_normativa, load_linhagem])
def test_stubs_falham_explicitamente(fn):
    """Melhor NotImplementedError do que uma função que não faz nada."""
    with pytest.raises(NotImplementedError, match="v2"):
        fn()


# ---------------------------------------------------------------------------
# A pergunta de demonstração (gasta token)
# ---------------------------------------------------------------------------
@pytest.mark.llm
@precisa_grafo
def test_consulta_ao_grafo_responde():
    from isp_rag.brain.engine import build_brain_engine

    r = build_brain_engine().query("Quais critérios compõem a edição 2025 do ISP?")
    assert "gest" in str(r).lower() or "atuar" in str(r).lower()


@pytest.mark.llm
@precisa_grafo
def test_pergunta_de_demonstracao_aciona_as_tres_engines():
    """Spec §3.4 — se isto passa, a arquitetura de três camadas está
    justificada por comportamento, não por argumento no README."""
    from fastapi.testclient import TestClient

    from isp_rag.api.main import app

    pergunta = (
        "O RPPS de Recife caiu de conceito entre 2024 e 2025? Foi o desempenho "
        "dele que piorou ou a metodologia que mudou? E qual norma alterou isso?"
    )
    with TestClient(app) as client:
        d = client.post("/query", json={"question": pergunta}).json()

    assert set(d["engines_used"]) == {"ledger", "memory", "brain"}
    assert d["refused"] is False
    assert d["sources"]
    # A ruptura metodológica precisa ser declarada — é comparação cross-regime.
    assert "régua" in d["answer"].lower() or "metodolog" in d["answer"].lower()
