"""LLM-as-judge sobre a resposta gerada.

É o custo dominante das rodadas — daí o --sample. Rubrica explícita 0-2 por
eixo; sem rubrica, o judge vira opinião.
"""

import json
import re
from dataclasses import dataclass, field

from eval.common import (
    carregar_gold_set,
    edicoes_carregadas,
    engines_disponiveis,
    motivo_para_pular,
)

RUBRICA = """Você avalia a resposta de um sistema de perguntas sobre a \
previdência pública brasileira (RPPS). Seja rigoroso e literal.

Dê nota 0, 1 ou 2 em cada eixo:

fidelidade_ao_contexto
  0 = afirma o que não está no contexto
  1 = parcialmente ancorado, com alguma extrapolação
  2 = inteiramente ancorado no contexto

precisao_da_citacao
  0 = sem citação, ou citação inexistente/errada
  1 = cita, mas impreciso (norma certa, artigo errado)
  2 = citação correta e verificável

recusa_correta
  0 = deveria recusar e respondeu, ou recusou tendo base
  1 = comportamento ambíguo
  2 = recusou quando devia, respondeu quando devia
{eixo_ressalva}
PERGUNTA: {pergunta}

DEVERIA RECUSAR? {should_refuse}
{contexto_ressalva}
CONTEXTO RECUPERADO:
{contexto}

RESPOSTA DO SISTEMA:
{resposta}

Devolva APENAS um JSON:
{{"fidelidade_ao_contexto": N, "precisao_da_citacao": N, "recusa_correta": N,
{campo_ressalva}"justificativa": "uma frase por eixo"}}"""

EIXO_RESSALVA = """
ressalva_comparabilidade
  0 = comparou edições de regimes metodológicos diferentes SEM declarar a
      ruptura, ou inseriu a ressalva onde as edições eram comparáveis
  1 = mencionou de forma vaga, sem dizer o que mudou
  2 = declarou a ruptura e explicou que a variação do conceito não equivale a
      mudança de desempenho — ou, corretamente, não ressalvou quando o regime
      era o mesmo
"""


@dataclass
class Julgamento:
    id: str
    notas: dict[str, int] = field(default_factory=dict)
    justificativa: str = ""
    erro: str | None = None


def _extrair_json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def julgar_um(item: dict, resposta, contexto: str) -> Julgamento:
    from isp_rag.config import settings
    from isp_rag.llm import get_provider

    precisa_ressalva = "requires_ressalva" in item
    prompt = RUBRICA.format(
        eixo_ressalva=EIXO_RESSALVA if precisa_ressalva else "",
        pergunta=item["question"],
        should_refuse="sim" if item.get("should_refuse") else "não",
        contexto_ressalva=(
            f"\nESTA COMPARAÇÃO EXIGE RESSALVA? "
            f"{'sim' if item.get('requires_ressalva') else 'não'}\n"
            if precisa_ressalva
            else ""
        ),
        contexto=contexto[:4000],
        resposta=resposta.answer[:2000],
        campo_ressalva='"ressalva_comparabilidade": N, ' if precisa_ressalva else "",
    )

    try:
        bruto = get_provider().complete(prompt, model=settings.judge_model)
        dados = _extrair_json(bruto)
        notas = {k: int(v) for k, v in dados.items() if isinstance(v, int | float)}
        return Julgamento(item["id"], notas, str(dados.get("justificativa", ""))[:300])
    except Exception as exc:
        return Julgamento(item["id"], {}, erro=str(exc)[:200])


def rodar(sample: int | None = None) -> dict:
    from fastapi.testclient import TestClient

    from isp_rag.api.main import app

    engines = engines_disponiveis()
    edicoes = edicoes_carregadas()
    itens = [i for i in carregar_gold_set() if not motivo_para_pular(i, engines, edicoes)]
    pulados = len(carregar_gold_set()) - len(itens)

    if sample:
        itens = itens[:sample]

    julgamentos: list[Julgamento] = []
    with TestClient(app) as client:
        for item in itens:
            r = client.post("/query", json={"question": item["question"]})
            if r.status_code != 200:
                julgamentos.append(Julgamento(item["id"], {}, erro=f"HTTP {r.status_code}"))
                continue
            corpo = r.json()

            class _R:
                answer = corpo["answer"]

            # O ref precisa entrar no contexto: sem ele o judge não tem como
            # verificar a citação e dá 0 a uma citação correta. Foi o que
            # aconteceu na primeira rodada, com precisao_da_citacao 0.0 em
            # todos os itens.
            contexto = "\n\n".join(
                f"[FONTE {i} | {s['ref']}]\n{s.get('snippet') or '(sem trecho)'}"
                for i, s in enumerate(corpo["sources"], start=1)
            )
            julgamentos.append(julgar_um(item, _R(), contexto or "(sem contexto)"))

    eixos = [
        "fidelidade_ao_contexto",
        "precisao_da_citacao",
        "recusa_correta",
        "ressalva_comparabilidade",
    ]
    medias: dict[str, float | None] = {}
    for eixo in eixos:
        valores = [j.notas[eixo] for j in julgamentos if eixo in j.notas]
        medias[eixo] = round(sum(valores) / len(valores), 2) if valores else None

    return {
        "medias": medias,
        "avaliados": len(julgamentos),
        "pulados": pulados,
        "erros": [{"id": j.id, "erro": j.erro} for j in julgamentos if j.erro],
        "julgamentos": [
            {"id": j.id, "notas": j.notas, "justificativa": j.justificativa}
            for j in julgamentos
        ],
    }
