"""Síntese da resposta final.

Três regras duras (spec §6.3): responder só com base no contexto recuperado,
citar a fonte em cada afirmação, e declarar ausência de base quando não houver.

A recusa correta é métrica de sucesso, não falha. Em domínio normativo, um
sistema que inventa um prazo é pior que um sistema que diz não saber.
"""

import re
import unicodedata

from llama_index.core.schema import NodeWithScore

from isp_rag.config import settings
from isp_rag.contracts import EngineName, QueryResponse, Source
from isp_rag.llm import get_provider

REFUSAL_PHRASE = "Não há base na documentação indexada para responder a essa pergunta."

SYNTHESIS_PROMPT = """Você responde perguntas sobre a previdência pública \
brasileira (RPPS) usando EXCLUSIVAMENTE o contexto abaixo.

REGRAS:

1. FUNDAMENTAÇÃO. Se o contexto não contém a resposta, responda exatamente:
   "{refusal}"
   Não infira, não complete com conhecimento geral, não ofereça resposta
   aproximada. Um prazo inventado é pior que um "não sei".

2. CITAÇÃO. Cada afirmação factual cita sua fonte no corpo da resposta:
   - norma e dispositivo — ex.: (Portaria MTP 1.467/2022, art. 241)
   - ou tabela e edição   — ex.: (isp_resultado, ed. 2025)
   Afirmação sem citação não é aceita.

3. PREMISSA FALSA. Se a pergunta parte de premissa incorreta — cita norma
   revogada, artigo inexistente, ou critério de uma edição em que ele não
   existia — CORRIJA a premissa antes de responder, indicando a fonte da
   correção.

4. VIGÊNCIA. Se o contexto traz dispositivo revogado ou alterado, diga isso
   explicitamente e informe a situação atual, se houver no contexto.

5. COMPARABILIDADE ENTRE EDIÇÕES. O ISP-2025 foi reformulado: até 2024 o
   conceito vinha de tercil anual (nota RELATIVA à distribuição do ano); de
   2025 em diante vem de cortes fixos sobre a distribuição histórica (nota
   ABSOLUTA), com três indicadores novos.
   Se o contexto traz uma RESSALVA OBRIGATÓRIA, reproduza-a ANTES da resposta:
   a variação do conceito NÃO significa, por si só, mudança de desempenho —
   a régua mudou.

CONTEXTO:
{context}

PERGUNTA: {question}

RESPOSTA:"""

# (Norma, art. N) ou (tabela, ed. AAAA)
CITACAO_RE = re.compile(
    r"\(([^)]*?(?:art\.?\s*\d+|ed\.?\s*\d{4}|artigo\s*\d+)[^)]*)\)",
    re.IGNORECASE,
)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", sem_acento).strip()


def is_refusal(resposta: str) -> bool:
    """Tolerante a pequenas variações do modelo (acento, pontuação)."""
    alvo = " ".join(_normalizar(REFUSAL_PHRASE).split())
    obtido = " ".join(_normalizar(resposta).split())
    return alvo in obtido


def has_citation(resposta: str) -> bool:
    return bool(CITACAO_RE.search(resposta))


def build_context(nodes: list[NodeWithScore], ressalva: str | None = None) -> str:
    """Formata os nodes para o prompt, com as fontes identificadas.

    A ressalva entra como FONTE 0, antes de tudo: quando é devida, precisa
    estar no contexto para a regra 5 ter o que citar.
    """
    blocos: list[str] = []
    if ressalva:
        blocos.append(
            "[FONTE 0 | edicao, regimes metodológicos | RESSALVA OBRIGATÓRIA]\n" + ressalva
        )

    for i, node in enumerate(nodes, start=1):
        meta = node.metadata or {}
        if meta.get("norma"):
            ref = f"{meta['norma']}, art. {meta.get('artigo', '?')}"
            situacao = meta.get("situacao", "vigente")
            cabecalho = f"[FONTE {i} | {ref} | {situacao}]"
        else:
            ref = meta.get("ref", "Ledger do ISP")
            cabecalho = f"[FONTE {i} | {ref}]"
        blocos.append(f"{cabecalho}\n{node.node.get_content()}")

    return "\n\n".join(blocos)


def extract_sources(nodes: list[NodeWithScore], engines_used: list[EngineName]) -> list[Source]:
    """Monta as fontes citáveis a partir dos metadados dos nodes."""
    fontes: list[Source] = []
    vistos: set[str] = set()

    for node in nodes:
        meta = node.metadata or {}
        if meta.get("norma"):
            ref = f"{meta['norma']}, art. {meta.get('artigo', '?')}"
            engine: EngineName = "memory"
            url = meta.get("url")
            trecho = (meta.get("text_raw") or node.node.get_content())[:300]
        else:
            ref = meta.get("ref", "isp_resultado")
            engine = "ledger" if "ledger" in engines_used else (engines_used or ["ledger"])[0]
            url = meta.get("url")
            trecho = node.node.get_content()[:300]

        if ref in vistos:
            continue
        vistos.add(ref)
        fontes.append(Source(engine=engine, ref=ref, url=url, snippet=trecho))

    return fontes


def synthesize(
    question: str,
    nodes: list[NodeWithScore],
    engines_used: list[EngineName],
    sub_questions: list[str] | None = None,
    ressalva: str | None = None,
) -> QueryResponse:
    """Transforma contexto recuperado em resposta validada.

    `ressalva` vem de `checar_regimes()` (T05) — checagem determinística, sem
    LLM, sobre os anos presentes no resultset. Se não-None, é injetada no
    contexto como fonte obrigatória. Sem isso a defesa seria o produto de duas
    probabilidades (o LLM do SQL lembrar de trazer o regime × o da síntese
    lembrar de ressalvar), e se o SQL não trouxesse, a síntese seria
    logicamente incapaz de ressalvar. Ver plan.md §7.1.
    """
    if not nodes:
        # Sem contexto não há o que sintetizar: recusa sem gastar chamada.
        return QueryResponse(
            answer=REFUSAL_PHRASE,
            sources=[],
            engines_used=engines_used,
            sub_questions=sub_questions or [],
            refused=True,
        )

    contexto = build_context(nodes, ressalva)
    prompt = SYNTHESIS_PROMPT.format(
        refusal=REFUSAL_PHRASE, context=contexto, question=question
    )
    resposta = get_provider().complete(prompt, model=settings.llm_model).strip()

    if is_refusal(resposta):
        return QueryResponse(
            answer=resposta,
            sources=[],
            engines_used=engines_used,
            sub_questions=sub_questions or [],
            refused=True,
        )

    fontes = extract_sources(nodes, engines_used)
    if not fontes:
        # Bug do sistema: havia contexto, mas nenhuma fonte citável saiu dele.
        # R2 não pode ser violada nem por bug — melhor recusar que emitir
        # resposta sem fonte.
        import logging

        logging.getLogger(__name__).warning(
            "nodes não vazios mas nenhuma fonte extraída; tratando como recusa"
        )
        return QueryResponse(
            answer=REFUSAL_PHRASE,
            sources=[],
            engines_used=engines_used,
            sub_questions=sub_questions or [],
            refused=True,
        )

    if not has_citation(resposta):
        import logging

        logging.getLogger(__name__).warning("resposta sem citação no corpo: %s", question[:80])

    return QueryResponse(
        answer=resposta,
        sources=fontes,
        engines_used=engines_used,
        sub_questions=sub_questions or [],
        refused=False,
    )
