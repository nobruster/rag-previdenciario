"""Cobertura do corpus — separa recusa legítima de falha de recuperação."""

import pytest

from isp_rag.memory.cobertura import cobertura_de, diagnosticar_recusa
from isp_rag.memory.indexer import contar_pontos


def _indexado() -> bool:
    try:
        return contar_pontos() > 100
    except Exception:
        return False


precisa_qdrant = pytest.mark.skipif(not _indexado(), reason="corpus não indexado")


@precisa_qdrant
def test_termo_ausente_e_detectado():
    c = cobertura_de("Mongólia")
    assert not c.coberto
    assert c.n_chunks == 0


@precisa_qdrant
def test_termo_bem_coberto():
    c = cobertura_de("aposentadoria")
    assert c.coberto
    assert c.n_chunks > 50
    assert c.artigos


@precisa_qdrant
def test_busca_ignora_acento_e_caixa():
    assert cobertura_de("APOSENTADORIA").n_chunks == cobertura_de("aposentadoria").n_chunks


@precisa_qdrant
def test_dipr_tem_cobertura_rasa():
    """O caso que motivou este módulo: a recusa da T09 é legítima.

    O termo aparece em 2 chunks de 714, e nenhum enuncia o prazo — o assunto
    é regulado em norma que não está no corpus.
    """
    c = cobertura_de("DIPR")
    assert 0 < c.n_chunks <= 3, "se isto mudar, o corpus mudou e a T11 precisa saber"


@precisa_qdrant
def test_diagnostico_classifica_fora_do_corpus():
    d = diagnosticar_recusa("Qual a capital da Mongólia?")
    assert d["veredito"] == "fora_do_corpus"
    assert "Mongólia" in d["termos_ausentes"]


@precisa_qdrant
def test_diagnostico_classifica_cobertura_rasa():
    """Recusa por cobertura rasa não é falha de recuperação."""
    d = diagnosticar_recusa("qual o prazo para envio do DIPR?")
    assert d["veredito"] == "cobertura_rasa"
    assert "DIPR" in d["termos_raros"]


@precisa_qdrant
def test_diagnostico_classifica_coberto():
    """Aqui uma recusa SERIA falha — o corpus tem o assunto."""
    d = diagnosticar_recusa("quais os requisitos para emissão do CRP?")
    assert d["veredito"] == "coberto"
    assert not d["termos_ausentes"]
