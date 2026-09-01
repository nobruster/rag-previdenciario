"""Chunking do corpus normativo — um chunk por artigo.

A spec §5.2 é direta: esta é a decisão que mais impacta a qualidade final, e o
ponto onde a maioria dos projetos de RAG falha.

O erro padrão é cortar a cada N tokens com sobreposição. Em norma jurídica isso
separa o caput do parágrafo, desliga o inciso do artigo que o rege, e a resposta
perde a âncora citável. Aqui o chunk é o ARTIGO INTEIRO: caput mais parágrafos,
incisos e alíneas.
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Situacao = Literal["vigente", "revogado", "alterado"]

# Início de artigo: SÓ no começo da linha. "nos termos do art. 9º" no meio de um
# parágrafo é citação, não artigo novo — é o falso positivo mais comum, e a
# Portaria 1.467 tem centenas deles.
ART_RE = re.compile(
    r"^[ \t]*Art(?:\.|igo)?[ \t]*(\d+)[ \t]*([ºo°])?[ \t]*(-[A-Z])?[ \t]*[.\-–—]?[ \t]*",
    re.MULTILINE | re.IGNORECASE,
)

TITULO_RE = re.compile(r"^[ \t]*T[ÍI]TULO[ \t]+([IVXLC]+|[ÚU]NICO)\b.*$", re.MULTILINE | re.I)
CAPITULO_RE = re.compile(r"^[ \t]*CAP[ÍI]TULO[ \t]+([IVXLC]+|[ÚU]NICO)\b.*$", re.MULTILINE | re.I)
SECAO_RE = re.compile(r"^[ \t]*Se[çc][ãa]o[ \t]+([IVXLC]+|[ÚU]nica)\b.*$", re.MULTILINE | re.I)
SUBSECAO_RE = re.compile(
    r"^[ \t]*Subse[çc][ãa]o[ \t]+([IVXLC]+|[ÚU]nica)\b.*$", re.MULTILINE | re.I
)

REVOGADO_RE = re.compile(r"\(\s*Revogad[oa]", re.IGNORECASE)
ALTERADO_RE = re.compile(r"\(\s*Redação dada|\(\s*Incluíd[oa]", re.IGNORECASE)

# Fronteiras aceitáveis para sub-chunk: parágrafo, inciso ou alínea.
FRONTEIRA_RE = re.compile(
    r"^[ \t]*(?:§[ \t]*\d+|Par[áa]grafo[ \t]+[úu]nico|[IVXLC]+[ \t]*-|[a-z]\))",
    re.MULTILINE,
)

MAX_CHARS = 6000  # ~1500 tokens


class NormaMeta(BaseModel):
    norma: str
    numero: str
    data_norma: date | None = None
    orgao: str | None = None
    url: str
    situacao_padrao: Situacao = "vigente"


class ArticleChunk(BaseModel):
    text: str = Field(min_length=1)
    """Texto INDEXADO — com a hierarquia prefixada."""

    text_raw: str
    """Texto do artigo, sem prefixo. É o que se cita na resposta."""

    norma: str
    numero: str
    data_norma: date | None = None
    orgao: str | None = None
    titulo: str | None = None
    capitulo: str | None = None
    secao: str | None = None
    subsecao: str | None = None
    artigo: str
    situacao: Situacao = "vigente"
    data_inicio_vigencia: date | None = None
    data_fim_vigencia: date | None = None
    url: str
    ancora: str | None = None
    is_subchunk: bool = False
    subchunk_idx: int | None = None

    @property
    def hierarquia(self) -> str:
        partes = [p for p in (self.titulo, self.capitulo, self.secao, self.subsecao) if p]
        partes.append(f"Art. {self.artigo}")
        return " > ".join(partes)


def limpar_texto_pdf(texto: str) -> str:
    """Remove ruído de extração de PDF.

    Junta hifenização de fim de linha e descarta números de página soltos — a
    Portaria 1.467 tem 248 deles, um por página, e sem isso viram lixo no meio
    do artigo.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", texto)  # previdenciá-\nria
    texto = re.sub(r"^[ \t]*\d{1,3}[ \t]*$\n?", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto


def _rotulo(match: re.Match) -> str:
    return " ".join(match.group(0).split())


def _situacao(texto: str, padrao: Situacao) -> Situacao:
    if REVOGADO_RE.search(texto):
        return "revogado"
    if ALTERADO_RE.search(texto):
        return "alterado"
    return padrao


def _dividir_em_subchunks(caput: str, corpo: str) -> list[str]:
    """Artigo longo vira sub-chunks que REPETEM o caput como contexto.

    O corte respeita fronteiras de parágrafo/inciso/alínea — nunca parte um
    inciso ao meio.
    """
    fronteiras = [m.start() for m in FRONTEIRA_RE.finditer(corpo)]
    if not fronteiras:
        return [corpo]

    partes, atual, inicio = [], "", 0
    for fim in fronteiras[1:] + [len(corpo)]:
        bloco = corpo[inicio:fim]
        if atual and len(atual) + len(bloco) > MAX_CHARS:
            partes.append(atual)
            atual = bloco
        else:
            atual += bloco
        inicio = fim
    if atual:
        partes.append(atual)

    if len(partes) == 1:
        return partes
    return [partes[0]] + [f"{caput}\n\n[continuação]\n{p}" for p in partes[1:]]


def chunk_norma(texto: str, meta: NormaMeta) -> list[ArticleChunk]:
    """Um chunk por artigo, com a hierarquia prefixada no texto indexado."""
    texto = limpar_texto_pdf(texto)

    # Marcadores de hierarquia, para saber o contexto vigente em cada posição.
    marcadores: list[tuple[int, str, str]] = []
    for regex, nivel in (
        (TITULO_RE, "titulo"),
        (CAPITULO_RE, "capitulo"),
        (SECAO_RE, "secao"),
        (SUBSECAO_RE, "subsecao"),
    ):
        marcadores += [(m.start(), nivel, _rotulo(m)) for m in regex.finditer(texto)]
    marcadores.sort()

    artigos = list(ART_RE.finditer(texto))
    chunks: list[ArticleChunk] = []

    for i, m in enumerate(artigos):
        inicio = m.start()
        fim = artigos[i + 1].start() if i + 1 < len(artigos) else len(texto)
        bruto = texto[inicio:fim].strip()
        if not bruto:
            continue

        # Contexto hierárquico vigente neste ponto do texto.
        ctx: dict[str, str | None] = {
            "titulo": None,
            "capitulo": None,
            "secao": None,
            "subsecao": None,
        }
        for pos, nivel, rotulo in marcadores:
            if pos > inicio:
                break
            ctx[nivel] = rotulo
            if nivel == "titulo":
                ctx["capitulo"] = ctx["secao"] = ctx["subsecao"] = None
            elif nivel == "capitulo":
                ctx["secao"] = ctx["subsecao"] = None
            elif nivel == "secao":
                ctx["subsecao"] = None

        numero = m.group(1) + (m.group(3) or "")
        situacao = _situacao(bruto, meta.situacao_padrao)

        base = dict(
            norma=meta.norma,
            numero=meta.numero,
            data_norma=meta.data_norma,
            orgao=meta.orgao,
            artigo=numero,
            situacao=situacao,
            url=meta.url,
            ancora=f"#art{numero}",
            **ctx,
        )

        caput = bruto.split("\n", 1)[0].strip()
        partes = _dividir_em_subchunks(caput, bruto) if len(bruto) > MAX_CHARS else [bruto]

        # O prefixo resolve o artigo que diz "o prazo de que trata o caput" sem
        # jamais mencionar o assunto pelo nome: sem ele, esse artigo é
        # irrecuperável por busca semântica.
        niveis = [v for v in (ctx["titulo"], ctx["capitulo"], ctx["secao"], ctx["subsecao"]) if v]
        prefixo = " > ".join([*niveis, f"Art. {numero}"])

        for idx, parte in enumerate(partes):
            chunks.append(
                ArticleChunk(
                    text=f"{prefixo}\n\n{parte}",
                    text_raw=parte,
                    is_subchunk=len(partes) > 1,
                    subchunk_idx=idx if len(partes) > 1 else None,
                    **base,
                )
            )

    return chunks


def chunk_documento_tecnico(texto: str, meta: NormaMeta) -> list[ArticleChunk]:
    """Mesma lógica aplicada a seções numeradas.

    Relatórios e notas técnicas do ISP não têm artigos; a unidade citável é a
    seção ("5.2 Memory — Chunking").
    """
    texto = limpar_texto_pdf(texto)
    secao_re = re.compile(r"^[ \t]*(\d+(?:\.\d+)*)[ \t]+(\S.*)$", re.MULTILINE)
    marcas = list(secao_re.finditer(texto))
    chunks: list[ArticleChunk] = []

    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        bruto = texto[m.start() : fim].strip()
        if len(bruto) < 40:  # cabeçalho solto, sem corpo
            continue
        numero, titulo = m.group(1), " ".join(m.group(2).split())[:80]
        prefixo = f"Seção {numero} {titulo}"
        chunk = ArticleChunk(
            text=f"{prefixo}\n\n{bruto}",
            text_raw=bruto,
            norma=meta.norma,
            numero=meta.numero,
            data_norma=meta.data_norma,
            orgao=meta.orgao,
            secao=f"{numero} {titulo}",
            artigo=numero,
            situacao=meta.situacao_padrao,
            url=meta.url,
            ancora=f"#sec{numero}",
        )
        chunks.append(chunk)

    return chunks
