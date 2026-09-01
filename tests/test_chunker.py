"""T06 — chunking por artigo.

A estratégia convencional (cortar a cada N tokens) está proibida: em norma
jurídica ela separa o caput do parágrafo e a resposta perde a âncora citável.
"""

from datetime import date
from pathlib import Path

import pytest

from isp_rag.memory.chunker import (
    ART_RE,
    NormaMeta,
    chunk_documento_tecnico,
    chunk_norma,
    limpar_texto_pdf,
)

META = NormaMeta(
    norma="Portaria MTP nº 1.467/2022",
    numero="1.467",
    data_norma=date(2022, 6, 2),
    orgao="MTP",
    url="https://www.gov.br/previdencia/portaria-1467",
)

FIXTURE = Path(__file__).parent / "fixtures" / "portaria_trecho.txt"

SINTETICO = """CAPÍTULO III
DO CUSTEIO

Seção I
Das Alíquotas

Art. 10. O ente federativo deverá observar o prazo previsto no caput, conforme
disposto no art. 5º desta Portaria.
I - primeiro inciso;
II - segundo inciso;
III - terceiro inciso;
IV - quarto inciso;
V - quinto inciso.
§ 1º Primeiro parágrafo do artigo dez.
§ 2º Segundo parágrafo.

Art. 11. Artigo seguinte, que trata de outro assunto.
Parágrafo único. Um parágrafo único qualquer.

Art. 11-A. Artigo acrescentado posteriormente. (Incluído pela Portaria MPS nº 1.180, de 2024)

Art. 12. Este artigo foi revogado. (Revogado pela Portaria MPS nº 1.180, de 2024)
"""


# ---------------------------------------------------------------------------
# Detecção de artigo
# ---------------------------------------------------------------------------
def test_citacao_no_meio_de_paragrafo_nao_cria_chunk():
    """"nos termos do art. 5º" é citação, não artigo novo — o falso positivo
    mais comum, e a Portaria real tem centenas deles."""
    chunks = chunk_norma(SINTETICO, META)
    assert [c.artigo for c in chunks] == ["10", "11", "11-A", "12"]


def test_artigo_com_sufixo_e_distinto():
    """Art. 11-A não é o Art. 11."""
    artigos = {c.artigo for c in chunk_norma(SINTETICO, META)}
    assert "11" in artigos and "11-A" in artigos


@pytest.mark.parametrize(
    "linha", ["Art. 1º texto", "Art. 1o texto", "Art. 1° texto", "Artigo 1 texto",
              "Art. 241. texto", "Art 12 texto", "Art. 5º-A texto"]
)
def test_variantes_de_numeracao(linha):
    assert ART_RE.match(linha), f"não casou: {linha!r}"


def test_citacao_inline_nao_casa():
    assert not ART_RE.match("nos termos do art. 5º desta Portaria")


# ---------------------------------------------------------------------------
# Integridade do artigo
# ---------------------------------------------------------------------------
def test_artigo_com_incisos_permanece_integro():
    """Cinco incisos e dois parágrafos ficam no MESMO chunk."""
    art10 = next(c for c in chunk_norma(SINTETICO, META) if c.artigo == "10")
    for marca in ("I - primeiro", "V - quinto", "§ 1º", "§ 2º"):
        assert marca in art10.text_raw, f"{marca} foi separado do caput"


def test_hierarquia_prefixada_no_texto_indexado():
    """Resolve o artigo que diz "o prazo de que trata o caput" sem nomear o
    assunto: sem o prefixo, é irrecuperável por busca semântica."""
    art10 = next(c for c in chunk_norma(SINTETICO, META) if c.artigo == "10")
    assert art10.text.startswith("CAPÍTULO III > Seção I > Art. 10")
    assert "CAPÍTULO III" in art10.text
    assert not art10.text_raw.startswith("CAPÍTULO"), "text_raw fica limpo, para citação"


def test_hierarquia_herdada_apos_novo_capitulo():
    chunks = chunk_norma(SINTETICO, META)
    assert all(c.capitulo == "CAPÍTULO III" for c in chunks)
    assert all(c.secao == "Seção I" for c in chunks)


# ---------------------------------------------------------------------------
# Vigência
# ---------------------------------------------------------------------------
def test_situacao_detectada():
    por_artigo = {c.artigo: c.situacao for c in chunk_norma(SINTETICO, META)}
    assert por_artigo["12"] == "revogado"
    assert por_artigo["11-A"] == "alterado"
    assert por_artigo["10"] == "vigente"


def test_metadados_de_citacao_preservados():
    c = chunk_norma(SINTETICO, META)[0]
    assert c.norma == "Portaria MTP nº 1.467/2022"
    assert c.url.startswith("https://")
    assert c.ancora == "#art10"
    assert c.data_norma == date(2022, 6, 2)


# ---------------------------------------------------------------------------
# Limpeza de PDF
# ---------------------------------------------------------------------------
def test_hifenizacao_de_fim_de_linha_e_juntada():
    assert "previdenciária" in limpar_texto_pdf("previdenciá-\nria")


def test_numero_de_pagina_solto_e_removido():
    """A Portaria tem 248 desses — um por página."""
    limpo = limpar_texto_pdf("Art. 1º texto do artigo\n11\ncontinuação do texto")
    assert "\n11\n" not in limpo
    assert "continuação" in limpo


# ---------------------------------------------------------------------------
# Sub-chunks
# ---------------------------------------------------------------------------
def test_artigo_longo_vira_subchunks_repetindo_o_caput():
    corpo = "Art. 99. Caput do artigo muito longo.\n" + "".join(
        f"§ {i}º Parágrafo com bastante texto para forçar a divisão. {'x' * 400}\n"
        for i in range(1, 25)
    )
    subs = chunk_norma(corpo, META)
    assert len(subs) > 1
    assert all(c.is_subchunk for c in subs)
    assert all(c.artigo == "99" for c in subs)
    for s in subs[1:]:
        assert "Caput do artigo muito longo" in s.text_raw, "sub-chunk sem o caput como contexto"


# ---------------------------------------------------------------------------
# Contra o documento real
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture ausente")
def test_trecho_real_da_portaria():
    chunks = chunk_norma(FIXTURE.read_text(encoding="utf-8"), META)
    assert chunks, "nenhum artigo detectado no trecho real"
    assert all(c.text.count("\n\n") >= 1 for c in chunks)
    assert all(c.text_raw.strip() for c in chunks)
    # O trecho cita "art. 281-A" dentro de um parágrafo: não pode virar chunk.
    assert "281-A" not in {c.artigo for c in chunks}


# ---------------------------------------------------------------------------
# Documento técnico (sem artigos)
# ---------------------------------------------------------------------------
def test_documento_tecnico_usa_secoes():
    texto = (
        "5.1 Ledger\nModelo relacional com entes identificados por CNPJ e "
        "resultados por edição, o suficiente para haver corpo.\n"
        "5.2 Memory\nÉ a decisão técnica que mais impacta a qualidade final "
        "do sistema de recuperação.\n"
    )
    chunks = chunk_documento_tecnico(texto, META)
    assert [c.artigo for c in chunks] == ["5.1", "5.2"]
    assert chunks[0].text.startswith("Seção 5.1")
