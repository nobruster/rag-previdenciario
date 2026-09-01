"""T03 — o manifesto é a prova de procedência (R1)."""

from datetime import UTC, datetime, timedelta

from isp_rag.ingestion.manifest import Manifest, ManifestEntry, utcnow

SHA_A = "a" * 64
SHA_B = "b" * 64


def _entry(sha: str, url: str, **kw) -> ManifestEntry:
    base = dict(
        url=url,
        filename="isp.xlsx",
        fetched_at=utcnow(),
        size_bytes=1024,
        sha256=sha,
        content_type="application/vnd.ms-excel",
    )
    return ManifestEntry(**{**base, **kw})


def test_persiste_e_recarrega_sem_perder_campos(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx"))

    recarregado = Manifest(tmp_path / "manifest.json").load()
    assert len(recarregado) == 1
    e = recarregado[0]
    assert e.sha256 == SHA_A
    assert e.url == "https://gov.br/a.xlsx"
    assert e.size_bytes == 1024
    assert e.content_type == "application/vnd.ms-excel"


def test_fetched_at_e_timezone_aware(tmp_path):
    """Coleta sem fuso é procedência ambígua."""
    m = Manifest(tmp_path / "manifest.json")
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx"))
    assert Manifest(tmp_path / "manifest.json").load()[0].fetched_at.tzinfo is not None


def test_has_sha_encontra_conteudo_ja_coletado(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx"))
    assert m.has_sha(SHA_A) is not None
    assert m.has_sha(SHA_B) is None


def test_by_url_devolve_a_coleta_mais_recente(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    antiga = utcnow() - timedelta(days=2)
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx", fetched_at=antiga))
    m.append(_entry(SHA_B, "https://gov.br/a.xlsx"))
    assert m.by_url("https://gov.br/a.xlsx").sha256 == SHA_B


def test_gravado_em_ordem_cronologica(tmp_path):
    m = Manifest(tmp_path / "manifest.json")
    m.append(_entry(SHA_B, "https://gov.br/b.xlsx"))
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx", fetched_at=utcnow() - timedelta(days=1)))
    datas = [e.fetched_at for e in Manifest(tmp_path / "manifest.json").load()]
    assert datas == sorted(datas)


def test_acento_preservado_no_json(tmp_path):
    """Nomes de arquivo do gov.br têm acento — ensure_ascii quebraria a leitura."""
    m = Manifest(tmp_path / "manifest.json")
    m.append(_entry(SHA_A, "https://gov.br/a.xlsx", filename="Situação Previdenciária.pdf"))
    texto = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert "Situação Previdenciária.pdf" in texto


def test_manifesto_ausente_carrega_vazio(tmp_path):
    assert Manifest(tmp_path / "nao_existe.json").load() == []


def test_sha_invalido_rejeitado(tmp_path):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ManifestEntry(
            url="https://gov.br/a.xlsx",
            filename="a.xlsx",
            fetched_at=datetime.now(UTC),
            size_bytes=1,
            sha256="curto",
        )
