"""T03 — o registro de fontes é a fonte única das URLs (R1)."""

import pytest

from isp_rag.ingestion.sources import (
    edicoes_disponiveis,
    isp_urls,
    legislacao_urls,
    load_sources,
    validate_sources,
)


def test_nove_edicoes_de_2017_a_2025():
    anos = edicoes_disponiveis()
    assert anos == list(range(2025, 2016, -1))


def test_urls_do_isp_sao_https_do_gov_br():
    """R1: procedência exige origem pública identificável."""
    for ano in edicoes_disponiveis():
        urls = isp_urls(ano)
        assert urls, f"edição {ano} sem URL"
        for chave, url in urls.items():
            assert url.startswith("https://www.gov.br/"), f"{ano}.{chave}: {url}"


def test_edicao_inexistente_lista_as_disponiveis():
    with pytest.raises(KeyError, match="2016"):
        isp_urls(2016)


def test_notas_do_json_nao_viram_url():
    """Chaves com `_` são anotações humanas, não documentos."""
    assert all(not k.startswith("_") for k in isp_urls(2020))
    assert "_nota" in load_sources()["edicoes"]["2020"]


def test_legislacao_pendente_falha_com_instrucao():
    """Nunca inventar URL: falhar com orientação é melhor que fabricar."""
    with pytest.raises(NotImplementedError, match="Planalto"):
        legislacao_urls()


def test_validate_reporta_apenas_a_legislacao():
    problemas = validate_sources()
    assert len(problemas) == 1
    assert "legislação pendente" in problemas[0]


def test_ua_e_ruptura_documentados_no_registro():
    """Os dois achados que mudam a implementação ficam junto das URLs."""
    dados = load_sources()
    assert "403" in dados["_nota_user_agent"]
    assert "2025" in dados["_nota_metodologia"]
