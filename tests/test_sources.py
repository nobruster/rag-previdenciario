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


def test_legislacao_levantada_e_verificada():
    """As 7 normas do corpus, mais o texto original da Portaria."""
    urls = legislacao_urls()
    assert set(urls) == {
        "portaria_mtp_1467_2022",
        "portaria_mtp_1467_2022_original",
        "lei_9717_1998",
        "lei_10887_2004",
        "ec_20_1998",
        "ec_41_2003",
        "ec_47_2005",
        "ec_103_2019",
    }
    assert all(u.startswith("https://") for u in urls.values())


def test_leis_e_ecs_em_html_do_planalto():
    """Spec §9: preferir HTML estruturado a PDF — a extração é muito melhor."""
    urls = legislacao_urls()
    for chave in ("lei_9717_1998", "lei_10887_2004", "ec_20_1998", "ec_103_2019"):
        assert urls[chave].startswith("https://www.planalto.gov.br/")
        assert urls[chave].endswith(".htm")


def test_portaria_aponta_para_o_texto_compilado():
    """A 1.467/2022 foi alterada depois. Indexar o texto original faria o
    Memory responder com redação superada."""
    urls = legislacao_urls()
    assert "Atualizadaat29dez2025" in urls["portaria_mtp_1467_2022"]
    assert urls["portaria_mtp_1467_2022"] != urls["portaria_mtp_1467_2022_original"]


def test_registro_integro():
    assert validate_sources() == []


def test_ua_e_ruptura_documentados_no_registro():
    """Os dois achados que mudam a implementação ficam junto das URLs."""
    dados = load_sources()
    assert "403" in dados["_nota_user_agent"]
    assert "2025" in dados["_nota_metodologia"]
