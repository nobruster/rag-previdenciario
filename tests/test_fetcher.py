"""T03 — a coleta é a única porta de entrada de arquivo (R1).

Sem rede: httpx.Client é substituído por um duplo que serve bytes conhecidos.
"""

import hashlib

import httpx
import pytest

from isp_rag.ingestion import fetcher
from isp_rag.ingestion.fetcher import FetchError, _safe_filename, fetch, fetch_all
from isp_rag.ingestion.manifest import Manifest

CONTEUDO = b"PK\x03\x04planilha do ISP" * 100
SHA_ESPERADO = hashlib.sha256(CONTEUDO).hexdigest()


class _FakeStream:
    def __init__(self, status, body, headers, falha_no_meio=False):
        self.status_code = status
        self._body = body
        self.headers = headers
        self._falha = falha_no_meio

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 500:
            raise httpx.HTTPStatusError("erro", request=None, response=None)

    def iter_bytes(self, chunk_size=None):
        yield self._body[: len(self._body) // 2]
        if self._falha:
            raise httpx.ReadError("conexão caiu no meio")
        yield self._body[len(self._body) // 2 :]


class _FakeClient:
    """Duplo de httpx.Client. `roteiro` é consumido a cada tentativa."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.headers_usados = None

    def __call__(self, **kwargs):
        self.headers_usados = kwargs.get("headers")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url):
        return self.roteiro.pop(0)


def _instalar(monkeypatch, *respostas):
    fake = _FakeClient(respostas)
    monkeypatch.setattr(fetcher.httpx, "Client", fake)
    return fake


def _ok(body=CONTEUDO, headers=None):
    return _FakeStream(200, body, headers or {"content-type": "application/pdf"})


def test_baixa_e_registra_procedencia(tmp_path, monkeypatch):
    _instalar(monkeypatch, _ok())
    e = fetch("https://gov.br/isp/relatorio.pdf", tmp_path)

    assert e.sha256 == SHA_ESPERADO
    assert e.size_bytes == len(CONTEUDO)
    assert e.filename == "relatorio.pdf"
    assert e.content_type == "application/pdf"
    assert (tmp_path / "relatorio.pdf").read_bytes() == CONTEUDO
    assert Manifest(tmp_path / "manifest.json").has_sha(SHA_ESPERADO)


def test_user_agent_de_navegador_e_enviado(tmp_path, monkeypatch):
    """Sem UA de navegador o gov.br responde 403 em tudo."""
    fake = _instalar(monkeypatch, _ok())
    fetch("https://gov.br/a.pdf", tmp_path)
    assert "Mozilla/5.0" in fake.headers_usados["User-Agent"]


def test_idempotente_por_hash(tmp_path, monkeypatch):
    """Mesmo conteúdo não é regravado — o manifesto não ganha linha nova."""
    _instalar(monkeypatch, _ok(), _ok())
    primeira = fetch("https://gov.br/a.pdf", tmp_path)
    segunda = fetch("https://gov.br/a.pdf", tmp_path)

    assert segunda.fetched_at == primeira.fetched_at
    assert len(Manifest(tmp_path / "manifest.json").load()) == 1


def test_erro_4xx_nao_tenta_de_novo(tmp_path, monkeypatch):
    fake = _instalar(monkeypatch, _FakeStream(404, b"", {}), _ok())
    with pytest.raises(FetchError, match="404"):
        fetch("https://gov.br/sumiu.pdf", tmp_path)
    assert len(fake.roteiro) == 1  # a segunda resposta não foi consumida


def test_403_menciona_user_agent(tmp_path, monkeypatch):
    """O 403 do gov.br é sintoma de UA bloqueado, não de URL errada."""
    _instalar(monkeypatch, _FakeStream(403, b"", {}))
    with pytest.raises(FetchError, match="User-Agent"):
        fetch("https://gov.br/a.pdf", tmp_path)


def test_erro_5xx_tenta_tres_vezes(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    fake = _instalar(
        monkeypatch,
        _FakeStream(500, b"", {}),
        _FakeStream(500, b"", {}),
        _FakeStream(500, b"", {}),
    )
    with pytest.raises(FetchError, match="3 tentativas"):
        fetch("https://gov.br/a.pdf", tmp_path)
    assert fake.roteiro == []


def test_recupera_apos_falha_transitoria(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    _instalar(monkeypatch, _FakeStream(500, b"", {}), _ok())
    assert fetch("https://gov.br/a.pdf", tmp_path).sha256 == SHA_ESPERADO


def test_download_interrompido_nao_deixa_arquivo(tmp_path, monkeypatch):
    """Rename atômico: parcial nunca vira arquivo final."""
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    _instalar(
        monkeypatch,
        _FakeStream(200, CONTEUDO, {}, falha_no_meio=True),
        _FakeStream(200, CONTEUDO, {}, falha_no_meio=True),
        _FakeStream(200, CONTEUDO, {}, falha_no_meio=True),
    )
    with pytest.raises(FetchError):
        fetch("https://gov.br/a.pdf", tmp_path)

    assert not (tmp_path / "a.pdf").exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_fetch_all_acumula_erros(tmp_path, monkeypatch):
    _instalar(monkeypatch, _ok(), _FakeStream(404, b"", {}), _ok(b"outro conteudo"))
    entradas, erros = fetch_all(
        ["https://gov.br/a.pdf", "https://gov.br/b.pdf", "https://gov.br/c.pdf"], tmp_path
    )
    assert len(entradas) == 2
    assert len(erros) == 1
    assert "b.pdf" in erros[0][0]


@pytest.mark.parametrize(
    "url,disposition,esperado",
    [
        ("https://gov.br/x/../../etc/passwd", None, "passwd"),
        ("https://gov.br/a%20b.pdf", None, "a b.pdf"),
        ("https://gov.br/x.pdf", 'attachment; filename="ISP 2025.xlsx"', "ISP 2025.xlsx"),
        ("https://gov.br/x.pdf", "attachment; filename=..\\..\\evil.exe", "evil.exe"),
        ("https://gov.br/", None, "download"),
    ],
)
def test_nome_de_arquivo_sanitizado(url, disposition, esperado):
    assert _safe_filename(url, disposition) == esperado
