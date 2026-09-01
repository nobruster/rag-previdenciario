"""T07 — indexação e recuperação híbrida.

Os testes que consultam o Qdrant pulam se a coleção não estiver indexada.
Os que gastam embedding ficam marcados `llm`.
"""

import pytest

from isp_rag.memory.chunker import ArticleChunk
from isp_rag.memory.engine import detectar_citacao, filtro_vigencia
from isp_rag.memory.indexer import contar_pontos, ponto_id, tokenizar, vetor_esparso


def _indexado() -> bool:
    try:
        return contar_pontos() > 100
    except Exception:
        return False


precisa_qdrant = pytest.mark.skipif(not _indexado(), reason="corpus não indexado")


def _chunk(**kw) -> ArticleChunk:
    base = dict(
        text="CAPÍTULO I > Art. 1\n\ntexto",
        text_raw="texto",
        norma="Portaria MTP nº 1.467/2022",
        numero="1.467",
        artigo="1",
        url="https://gov.br/x",
    )
    return ArticleChunk(**{**base, **kw})


# ---------------------------------------------------------------------------
# Id do ponto
# ---------------------------------------------------------------------------
def test_id_estavel_entre_execucoes():
    """Reindexar não pode duplicar."""
    assert ponto_id(_chunk()) == ponto_id(_chunk())


def test_artigos_homonimos_nao_colidem():
    """A Portaria 1.467 tem 17 "Art. 1º" — um por Anexo. Sem a hierarquia na
    chave, 222 dos 532 chunks se sobrescreviam em silêncio."""
    a = _chunk(capitulo="CAPÍTULO I", text_raw="primeiro")
    b = _chunk(capitulo="CAPÍTULO II", text_raw="segundo")
    assert ponto_id(a) != ponto_id(b)


def test_mesmo_artigo_mesma_secao_textos_diferentes():
    a = _chunk(text_raw="Art. 5º De 6 de março de 1997 até 6 de maio de 1999...")
    b = _chunk(text_raw="Art. 5º São segurados na condição de beneficiários...")
    assert ponto_id(a) != ponto_id(b)


def test_normas_diferentes_nao_colidem():
    assert ponto_id(_chunk(norma="Lei nº 9.717/1998")) != ponto_id(
        _chunk(norma="Emenda Constitucional nº 20/1998")
    )


# ---------------------------------------------------------------------------
# Vetor esparso
# ---------------------------------------------------------------------------
def test_tokenizacao_preserva_termos_do_dominio():
    tokens = tokenizar("Art. 241 do DIPR e o CRP")
    assert {"art", "241", "dipr", "crp"} <= set(tokens)


def test_esparso_e_deterministico():
    """hash() do Python varia entre processos; blake2b não."""
    a, b = vetor_esparso("art 241 dipr"), vetor_esparso("art 241 dipr")
    assert a.indices == b.indices and a.values == b.values


def test_esparso_conta_frequencia():
    v = vetor_esparso("prazo prazo prazo")
    assert max(v.values) == 3.0


# ---------------------------------------------------------------------------
# Detecção de citação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "pergunta,artigo,norma",
    [
        ("o que diz o art. 241?", "241", None),
        ("art. 241 da Portaria 1.467", "241", "1.467"),
        ("artigo 9º da Lei 9.717/1998", "9", "9.717"),
        ("o que exige o Art. 5º-A", "5-A", None),
        ("qual o prazo para envio do DIPR", None, None),
    ],
)
def test_deteccao_de_citacao(pergunta, artigo, norma):
    assert detectar_citacao(pergunta) == (artigo, norma)


# ---------------------------------------------------------------------------
# Filtro de vigência
# ---------------------------------------------------------------------------
def test_vigencia_e_o_padrao():
    """Responder com dispositivo revogado é tão ruim quanto inventar."""
    f = filtro_vigencia()
    assert f is not None
    assert any("situacao" in str(c) for c in f.must)


def test_incluir_revogados_desliga_o_filtro():
    assert filtro_vigencia(incluir_revogados=True) is None


# ---------------------------------------------------------------------------
# Contra o corpus indexado
# ---------------------------------------------------------------------------
@precisa_qdrant
def test_corpus_indexado():
    assert contar_pontos() > 600, "as 7 normas deveriam render ~714 pontos"


@pytest.mark.llm
@precisa_qdrant
def test_citacao_traz_o_artigo_em_primeiro():
    """Pergunta que cita dispositivo vira consulta EXATA, não vetorial."""
    from isp_rag.memory.engine import buscar

    r = buscar("art. 241", top_k=3)
    assert r[0].origem == "citacao"
    assert r[0].chunk.artigo == "241"


@pytest.mark.llm
@precisa_qdrant
def test_busca_semantica_sem_citacao():
    from isp_rag.memory.engine import buscar

    r = buscar("qual o prazo para envio do demonstrativo", top_k=5)
    assert r and all(x.origem == "hibrido" for x in r)


@pytest.mark.llm
@precisa_qdrant
def test_revogado_fora_por_padrao():
    from isp_rag.memory.engine import buscar

    r = buscar("aposentadoria compulsória", top_k=8)
    assert "revogado" not in {x.chunk.situacao for x in r}


@pytest.mark.llm
@precisa_qdrant
def test_reindexar_nao_duplica():
    from isp_rag.memory.indexer import index_chunks

    antes = contar_pontos()
    index_chunks([_chunk(text_raw="chunk de teste idempotência")])
    depois = contar_pontos()
    index_chunks([_chunk(text_raw="chunk de teste idempotência")])
    assert contar_pontos() == depois
    assert depois == antes + 1
