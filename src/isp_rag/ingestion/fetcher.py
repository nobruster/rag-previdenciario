"""Download com registro de procedência (R1).

A ÚNICA porta de entrada de arquivo no sistema é `fetch(url)`. Nenhuma função
aqui aceita caminho local como fonte de dado — se uma task futura precisar de um
arquivo, ela chama fetch(), não copia.
"""

import hashlib
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from isp_rag.ingestion.manifest import Manifest, ManifestEntry, utcnow

# O portal gov.br responde 403 a User-Agent padrão de cliente HTTP. Verificado:
# com o UA do httpx, os 20 arquivos do ISP dão 403; com UA de navegador, todos
# respondem 200/206. Sem isto, nenhum download funciona.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

TIMEOUT = 60.0
MAX_TENTATIVAS = 3
CHUNK = 64 * 1024


class FetchError(RuntimeError):
    """Falha de coleta que não se resolve com nova tentativa."""


def _safe_filename(url: str, content_disposition: str | None) -> str:
    """Nome de arquivo a partir do Content-Disposition ou da URL.

    Sanitiza contra path traversal: só o nome final interessa, nunca o caminho.
    """
    nome = ""
    if content_disposition:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, re.I)
        if m:
            nome = unquote(m.group(1))
    if not nome:
        nome = unquote(Path(urlparse(url).path).name)
    if not nome:
        nome = "download"

    nome = Path(nome.replace("\\", "/")).name  # descarta qualquer diretório
    nome = unicodedata.normalize("NFC", nome)
    nome = re.sub(r'[<>:"|?*\x00-\x1f]', "_", nome)  # inválidos no Windows
    return nome.strip(". ") or "download"


def _sha256_do_arquivo(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloco in iter(lambda: fh.read(CHUNK), b""):
            h.update(bloco)
    return h.hexdigest()


def fetch(url: str, dest_dir: Path, *, force: bool = False) -> ManifestEntry:
    """Baixa uma URL pública e registra a procedência.

    - SHA-256 calculado em streaming (as planilhas do ISP passam de 3 MB)
    - grava em .tmp e faz rename atômico: download interrompido não deixa
      arquivo parcial parecendo íntegro
    - idempotente por hash: se o conteúdo já está no manifesto, não regrava
    - 3 tentativas com backoff em erro de rede ou 5xx; 4xx falha na hora
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifesto = Manifest(dest_dir / "manifest.json")

    ultimo_erro: Exception | None = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        tmp: Path | None = None
        try:
            with httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers=HEADERS) as client:
                with client.stream("GET", url) as resp:
                    if 400 <= resp.status_code < 500:
                        dica = ""
                        if resp.status_code == 403:
                            dica = " (403 no gov.br costuma ser User-Agent bloqueado)"
                        raise FetchError(f"HTTP {resp.status_code} em {url}{dica}")
                    resp.raise_for_status()

                    filename = _safe_filename(url, resp.headers.get("content-disposition"))
                    tmp = dest_dir / f".{filename}.tmp"
                    h = hashlib.sha256()
                    tamanho = 0
                    with tmp.open("wb") as fh:
                        for bloco in resp.iter_bytes(CHUNK):
                            h.update(bloco)
                            tamanho += len(bloco)
                            fh.write(bloco)
                    sha = h.hexdigest()
                    content_type = resp.headers.get("content-type", "").split(";")[0] or None

            existente = manifesto.has_sha(sha)
            if existente and not force:
                tmp.unlink(missing_ok=True)  # conteúdo idêntico já coletado
                return existente

            destino = dest_dir / filename
            tmp.replace(destino)  # atômico
            entrada = ManifestEntry(
                url=url,
                filename=filename,
                fetched_at=utcnow(),
                size_bytes=tamanho,
                sha256=sha,
                content_type=content_type,
            )
            manifesto.append(entrada)
            return entrada

        except FetchError:
            if tmp:
                tmp.unlink(missing_ok=True)
            raise  # 4xx: nova tentativa não resolve
        except Exception as exc:
            if tmp:
                tmp.unlink(missing_ok=True)
            ultimo_erro = exc
            if tentativa < MAX_TENTATIVAS:
                time.sleep(2 ** (tentativa - 1))  # 1s, 2s

    raise FetchError(f"falha ao baixar {url} após {MAX_TENTATIVAS} tentativas: {ultimo_erro}")


def fetch_all(urls: list[str], dest_dir: Path) -> tuple[list[ManifestEntry], list[tuple[str, str]]]:
    """Baixa em sequência. Um erro não aborta os demais — acumula e devolve.

    Retorna (entradas coletadas, [(url, mensagem de erro)]).
    """
    entradas: list[ManifestEntry] = []
    erros: list[tuple[str, str]] = []
    for url in urls:
        try:
            entradas.append(fetch(url, dest_dir))
        except Exception as exc:
            erros.append((url, str(exc)))
    return entradas, erros
