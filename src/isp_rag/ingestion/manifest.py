"""Manifesto de procedência (R1).

Cada arquivo que entra no sistema registra origem, momento da coleta, tamanho e
hash. O manifesto é versionado no git; os arquivos baixados não são. É ele que
torna a procedência verificável pelo próprio código, e não por declaração no
README.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    url: str
    filename: str
    fetched_at: datetime
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str | None = None


class Manifest:
    """Registro append-only em `data/raw/manifest.json`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[ManifestEntry] | None = None

    def load(self) -> list[ManifestEntry]:
        if self._entries is None:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = [ManifestEntry(**item) for item in raw]
            else:
                self._entries = []
        return self._entries

    def append(self, entry: ManifestEntry) -> None:
        entries = self.load()
        entries.append(entry)
        self._save(entries)

    def _save(self, entries: list[ManifestEntry]) -> None:
        ordered = sorted(entries, key=lambda e: e.fetched_at)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                [json.loads(e.model_dump_json()) for e in ordered],
                indent=2,
                ensure_ascii=False,  # nomes de arquivo do gov.br têm acento
            )
            + "\n",
            encoding="utf-8",
        )
        self._entries = ordered

    def has_sha(self, sha256: str) -> ManifestEntry | None:
        """O mesmo conteúdo já foi coletado? É o que dá idempotência ao fetch."""
        return next((e for e in self.load() if e.sha256 == sha256), None)

    def by_url(self, url: str) -> ManifestEntry | None:
        """Coleta mais recente para uma URL."""
        matches = [e for e in self.load() if e.url == url]
        return max(matches, key=lambda e: e.fetched_at) if matches else None


def utcnow() -> datetime:
    """Timestamp timezone-aware. Coleta sem fuso é procedência ambígua."""
    return datetime.now(UTC)
