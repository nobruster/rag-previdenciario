"""Roda as 60 perguntas de validação contra o sistema e checa os invariantes.

Aqui não se mede "a resposta é boa" — isso é o judge da T11. Mede-se o que dá
para verificar sem julgamento: o contrato foi respeitado, o SQL bate, a
recuperação achou o artigo, a base não foi alterada.

    python -m eval.validacao.rodar
    python -m eval.validacao.rodar --bloco adversarial
"""

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PERGUNTAS = Path(__file__).with_name("perguntas60.json")
RESULTADOS = Path(__file__).with_name("resultados")


@dataclass
class Achado:
    id: str
    bloco: str
    ok: bool
    detalhe: str = ""
    resposta: str = ""


@dataclass
class Relatorio:
    achados: list[Achado] = field(default_factory=list)

    def por_bloco(self, bloco: str) -> list[Achado]:
        return [a for a in self.achados if a.bloco == bloco]

    def resumo(self) -> str:
        linhas = []
        for bloco in ("adversarial", "normativo", "numerico"):
            itens = self.por_bloco(bloco)
            if not itens:
                continue
            ok = sum(1 for a in itens if a.ok)
            linhas.append(f"  {bloco:<14} {ok}/{len(itens)}")
        return "\n".join(linhas)


def _normalizar(resultset) -> list[tuple]:
    from decimal import Decimal

    def celula(v):
        return round(float(v), 4) if isinstance(v, Decimal | float) else v

    return sorted((tuple(celula(v) for v in linha) for linha in resultset), key=repr)


def _resposta_contem(resposta: str, esperado: list[tuple]) -> bool:
    """O resultado do SQL aparece na resposta?

    O modelo escreve em português: 1323 vira "1.323", e uma letra vira "'C'".
    Comparar cru daria falso negativo — foi o que aconteceu na primeira rodada,
    com 9 respostas corretas marcadas como falha.
    """
    texto = resposta.lower()
    sem_pontos = re.sub(r"[. ]", "", texto)

    for linha in esperado:
        casou = False
        for valor in linha:
            alvo = str(valor).lower()
            if isinstance(valor, int) and abs(valor) >= 1000:
                casou = str(valor) in sem_pontos
            elif len(alvo) == 1:
                # Letra de conceito: exige aspas ou delimitador, não substring solta.
                casou = bool(re.search(rf"['\"\s]{re.escape(alvo)}['\"\s.,)]", texto))
            else:
                casou = alvo in texto
            if casou:
                break
        if not casou:
            return False
    return True


def rodar(bloco: str | None = None) -> Relatorio:
    from fastapi.testclient import TestClient

    from isp_rag.api.main import app
    from isp_rag.ledger.engine import run_sql

    dados = json.loads(PERGUNTAS.read_text(encoding="utf-8"))
    itens = [i for i in dados["perguntas"] if not bloco or i["bloco"] == bloco]
    rel = Relatorio()

    antes = run_sql("SELECT count(*) FROM isp_resultado")[0][0]

    with TestClient(app) as client:
        for item in itens:
            r = client.post("/query", json={"question": item["question"]})
            if r.status_code != 200:
                rel.achados.append(
                    Achado(item["id"], item["bloco"], False, f"HTTP {r.status_code}")
                )
                continue

            corpo = r.json()
            resposta = corpo["answer"]
            problemas: list[str] = []

            # R2: resposta não recusada precisa citar fonte.
            if not corpo["refused"] and not corpo["sources"]:
                problemas.append("R2: resposta sem fonte")

            # R3: recusa não pode vir com fonte.
            if corpo["refused"] and corpo["sources"]:
                problemas.append("R3: recusou mas trouxe fonte")

            # Escala: o sistema nunca deve afirmar conceito E.
            if re.search(r"conceito\s+['\"]?E\b", resposta, re.IGNORECASE):
                problemas.append("afirmou conceito E (escala vai de A a D)")

            # Ressalva devida em comparação cross-regime.
            if item.get("requires_ressalva"):
                texto = resposta.lower()
                if not any(t in texto for t in ("régua", "regua", "metodolog", "comparáve")):
                    problemas.append("faltou a ressalva de comparabilidade")

            # Execution match, quando há SQL de referência.
            if item.get("reference_sql"):
                try:
                    esperado = _normalizar(run_sql(item["reference_sql"]))
                    if not _resposta_contem(resposta, esperado):
                        problemas.append(f"resposta não contém o resultado {esperado[:2]}")
                except Exception as exc:
                    problemas.append(f"SQL de referência falhou: {exc}")

            # Recuperação: o artigo esperado precisa estar entre as fontes.
            if ref := item.get("expected_source_ref"):
                m = re.search(r"art\.?\s*(\d+(?:-[A-Z])?)", ref, re.IGNORECASE)
                if m and not any(m.group(1) in s["ref"] for s in corpo["sources"]):
                    problemas.append(f"art. {m.group(1)} fora das fontes")

            # Recusa esperada.
            if item["should_refuse"] and not corpo["refused"]:
                problemas.append("deveria ter recusado")

            rel.achados.append(
                Achado(
                    item["id"],
                    item["bloco"],
                    not problemas,
                    "; ".join(problemas),
                    resposta[:200],
                )
            )

    depois = run_sql("SELECT count(*) FROM isp_resultado")[0][0]
    if antes != depois:
        rel.achados.append(
            Achado("INTEGRIDADE", "adversarial", False, f"a base mudou: {antes} -> {depois}")
        )
    else:
        rel.achados.append(
            Achado("INTEGRIDADE", "adversarial", True, f"base intacta ({antes} registros)")
        )

    return rel


def main() -> int:
    p = argparse.ArgumentParser(description="Valida o RAG contra as 60 perguntas.")
    p.add_argument("--bloco", choices=["adversarial", "normativo", "numerico"])
    args = p.parse_args()

    for ruidoso in ("llama_index", "httpx", "openai", "isp_rag"):
        logging.getLogger(ruidoso).setLevel(logging.ERROR)

    rel = rodar(args.bloco)
    print(rel.resumo())

    falhas = [a for a in rel.achados if not a.ok]
    if falhas:
        print(f"\n{len(falhas)} com problema:")
        for a in falhas:
            print(f"  [{a.id}] {a.detalhe}")
            if a.resposta:
                print(f"        {a.resposta[:120]}")

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    destino = RESULTADOS / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    destino.write_text(
        json.dumps(
            [
                {"id": a.id, "bloco": a.bloco, "ok": a.ok, "detalhe": a.detalhe,
                 "resposta": a.resposta}
                for a in rel.achados
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\ngravado em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
