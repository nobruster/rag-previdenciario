"""Extração de texto do corpus normativo.

A spec §9 recomenda avaliar HTML estruturado antes de recorrer a parsing de PDF
— por isso as leis e ECs do Planalto foram coletadas em .htm. OCR fica reservado
a documentos digitalizados; um PDF sem camada de texto falha com mensagem clara,
em vez de devolver texto vazio silenciosamente.
"""

import html
import re
from pathlib import Path


class SemCamadaDeTexto(RuntimeError):
    """PDF digitalizado — precisaria de OCR, que está fora do escopo."""


def extract_text_from_pdf(path: Path) -> str:
    """Texto de um PDF, preservando quebras de linha e ordem de leitura."""
    import pypdf

    leitor = pypdf.PdfReader(str(path))
    paginas = [(p.extract_text() or "") for p in leitor.pages]
    texto = "\n".join(paginas)

    # Um PDF de 249 páginas com meia dúzia de caracteres é digitalizado.
    if len(texto.strip()) < 100 * max(1, len(paginas)) / 10:
        raise SemCamadaDeTexto(
            f"{path.name}: sem camada de texto ({len(texto.strip())} chars em "
            f"{len(paginas)} páginas). Precisaria de OCR — fora do escopo (spec §9)."
        )
    return texto


def extract_text_from_html(conteudo: str | bytes) -> str:
    """Texto de uma página do Planalto.

    O HTML do Planalto é antigo (tabelas, <p> soltos, ISO-8859-1), mas conserva
    a quebra por dispositivo — o que dá extração melhor que o PDF equivalente.
    """
    if isinstance(conteudo, bytes):
        for enc in ("utf-8", "iso-8859-1", "cp1252"):
            try:
                conteudo = conteudo.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            conteudo = conteudo.decode("utf-8", errors="replace")

    texto = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", conteudo)
    texto = re.sub(r"(?i)<br\s*/?>", "\n", texto)
    texto = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", texto)
    texto = re.sub(r"(?s)<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = re.sub(r"\n[ \t]+", "\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def extract_text(path: Path) -> str:
    """Despacha por extensão."""
    sufixo = path.suffix.lower()
    if sufixo == ".pdf":
        return extract_text_from_pdf(path)
    if sufixo in (".htm", ".html"):
        return extract_text_from_html(path.read_bytes())
    raise ValueError(f"extensão não suportada para extração de texto: {path.name}")
