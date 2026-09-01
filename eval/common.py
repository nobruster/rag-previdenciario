"""Base compartilhada pelos runners de avaliação.

Um item pulado por dependência ausente NÃO é falha de qualidade. Misturar os
dois corrompe a leitura da métrica — por isso `skipped` é status próprio, com
o motivo registrado.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import psycopg

from isp_rag.config import settings

GOLD_SET = Path(__file__).parent / "gold_set.json"
RUNS_DIR = Path(__file__).parent / "runs"

Status = Literal["ok", "falha", "skipped"]


@dataclass
class ItemResultado:
    id: str
    status: Status
    esperado: Any = None
    obtido: Any = None
    motivo: str | None = None


@dataclass
class Metrica:
    nome: str
    itens: list[ItemResultado] = field(default_factory=list)

    @property
    def avaliados(self) -> list[ItemResultado]:
        return [i for i in self.itens if i.status != "skipped"]

    @property
    def acertos(self) -> int:
        return sum(1 for i in self.avaliados if i.status == "ok")

    @property
    def pulados(self) -> int:
        return sum(1 for i in self.itens if i.status == "skipped")

    @property
    def taxa(self) -> float | None:
        n = len(self.avaliados)
        return self.acertos / n if n else None

    def resumo(self) -> str:
        if self.taxa is None:
            return f"{self.nome:<14} sem itens avaliáveis  [{self.pulados} pulados]"
        base = f"{self.nome:<14} {self.taxa:.2f}  ({self.acertos}/{len(self.avaliados)})"
        return base + (f"   [{self.pulados} pulados]" if self.pulados else "")

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "taxa": self.taxa,
            "acertos": self.acertos,
            "avaliados": len(self.avaliados),
            "pulados": self.pulados,
            "falhas": [
                {"id": i.id, "esperado": i.esperado, "obtido": i.obtido, "motivo": i.motivo}
                for i in self.itens
                if i.status == "falha"
            ],
        }


def carregar_gold_set() -> list[dict]:
    return json.loads(GOLD_SET.read_text(encoding="utf-8"))["perguntas"]


def edicoes_carregadas() -> set[int]:
    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=3) as c, c.cursor() as k:
            k.execute("SELECT DISTINCT edicao_ano FROM isp_resultado")
            return {r[0] for r in k.fetchall()}
    except Exception:
        return set()


def engines_disponiveis() -> set[str]:
    """Detecta em runtime, não por flag hardcoded."""
    disponiveis: set[str] = set()

    if edicoes_carregadas():
        disponiveis.add("ledger")

    try:
        from isp_rag.memory.indexer import contar_pontos

        if contar_pontos() > 0:
            disponiveis.add("memory")
    except Exception:
        pass

    try:
        from isp_rag.api.main import BRAIN_ENABLED

        if BRAIN_ENABLED:
            disponiveis.add("brain")
    except Exception:
        pass

    return disponiveis


def motivo_para_pular(item: dict, engines: set[str], edicoes: set[int]) -> str | None:
    """Por que este item não pode ser avaliado agora, se for o caso."""
    req = item.get("requires", {})

    faltando = set(req.get("engines", [])) - engines
    if faltando:
        return f"engine indisponível: {', '.join(sorted(faltando))}"

    se_expected = item.get("expected_engine")
    if se_expected and se_expected != "multi" and se_expected not in engines:
        return f"engine indisponível: {se_expected}"

    edicoes_faltando = set(req.get("edicoes", [])) - edicoes
    if edicoes_faltando:
        return f"edição não carregada: {', '.join(map(str, sorted(edicoes_faltando)))}"

    return None


def tem_cobertura(item: dict) -> bool:
    """Itens sem cobertura ficam fora do denominador do recall.

    Não se mede recuperação de algo que não está indexado.
    """
    return item.get("cobertura") == "coberto"
