"""Roteamento entre as engines.

A spec §6.1 é explícita: o acerto do roteador é MEDIDO, não presumido. Por isso
`route()` expõe a escolha sem executar a query — é o que a T11 mede, e medir
executando custaria uma consulta completa por pergunta avaliada.
"""

import re
from datetime import date

from llama_index.core.query_engine import RouterQueryEngine, SubQuestionQueryEngine
from llama_index.core.selectors import LLMSingleSelector
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from pydantic import BaseModel

from isp_rag.contracts import EngineName
from isp_rag.llm import llama_llm

DESC_LEDGER = (
    "Dados numéricos do Índice de Situação Previdenciária (ISP) por ente "
    "federativo e por edição. Use para: conceitos (A a D) de um RPPS, rankings, "
    "médias, contagens, comparação numérica entre entes ou entre edições, e a "
    "memória de cálculo (a letra A/B/C de cada indicador parcial). "
    "Exemplos: 'qual o conceito do RPPS de Campinas em 2025', 'quantos entes "
    "tiveram conceito A', 'média por UF', 'quais os 5 melhores colocados'."
)

DESC_MEMORY = (
    "Texto normativo e técnico: Portaria MTP 1.467/2022, Leis 9.717/1998 e "
    "10.887/2004, Emendas Constitucionais 20/1998, 41/2003, 47/2005 e 103/2019. "
    "Use para: o que a norma EXIGE, prazos, requisitos, definições, conteúdo de "
    "um artigo específico, metodologia do índice. "
    "Exemplos: 'qual o prazo de envio do DIPR', 'o que exige o art. 241', "
    "'quais os requisitos para emissão do CRP', 'o que é segurado'."
)

DESC_BRAIN = (
    "Relações entre normas, edições, critérios e indicadores: qual norma alterou "
    "qual critério, o que mudou entre edições e por quê, cadeia de revogação, "
    "linhagem entre dispositivo normativo e indicador. "
    "Exemplos: 'que critério mudou entre 2023 e 2025', 'qual portaria alterou o "
    "cálculo do indicador de cobertura', 'quais indicadores compõem a dimensão "
    "atuarial'."
)

# Sinais de que a pergunta pede número E norma, ou pede explicação de mudança.
_NUMERICO = re.compile(
    r"\b(nota|conceito|classifica[çc][ãa]o|caiu|subiu|piorou|melhorou|ranking|"
    r"m[ée]dia|quantos|posi[çc][ãa]o|resultado|pontua[çc][ãa]o)\b",
    re.IGNORECASE,
)
_NORMATIVO = re.compile(
    r"\b(norma|portaria|lei|emenda|artigo|art\.|exige|exig[êe]ncia|prazo|"
    r"requisito|metodologia|regra|disp[õo]e|alterou|mudou|por qu[êe]|porque)\b",
    re.IGNORECASE,
)
_MUDANCA = re.compile(
    r"\b(mudou|alterou|mudan[çc]a|altera[çc][ãa]o|entre \d{4} e \d{4}|"
    r"evolu[çc][ãa]o|desde)\b",
    re.IGNORECASE,
)


class RouteDecision(BaseModel):
    engine: EngineName | None = None
    """None quando a pergunta cruza domínios."""

    is_multi_domain: bool = False
    reason: str | None = None


def needs_decomposition(pergunta: str) -> bool:
    """Heurística barata ANTES de gastar chamada de LLM.

    A pergunta de demonstração da spec §3.4 é o caso canônico: pede o delta
    numérico E a norma que o explica.
    """
    tem_num = bool(_NUMERICO.search(pergunta))
    tem_norma = bool(_NORMATIVO.search(pergunta))
    tem_mudanca = bool(_MUDANCA.search(pergunta))
    return (tem_num and tem_norma) or (tem_num and tem_mudanca)


def build_tools(
    reference_date: date | None = None,
    brain_enabled: bool = False,
) -> list[QueryEngineTool]:
    """Uma tool por engine. As descrições são o prompt de fato do roteador."""
    from isp_rag.ledger.engine import build_ledger_engine

    tools = [
        QueryEngineTool(
            query_engine=build_ledger_engine(),
            metadata=ToolMetadata(name="ledger", description=DESC_LEDGER),
        ),
        QueryEngineTool(
            query_engine=_memory_query_engine(reference_date),
            metadata=ToolMetadata(name="memory", description=DESC_MEMORY),
        ),
    ]
    if brain_enabled:
        from isp_rag.brain.engine import build_brain_engine

        tools.append(
            QueryEngineTool(
                query_engine=build_brain_engine(),
                metadata=ToolMetadata(name="brain", description=DESC_BRAIN),
            )
        )
    return tools


def _memory_query_engine(reference_date: date | None = None):
    """Adapta a busca do Memory à interface de QueryEngine do LlamaIndex."""
    from llama_index.core.query_engine import CustomQueryEngine
    from llama_index.core.response_synthesizers import get_response_synthesizer
    from llama_index.core.schema import NodeWithScore, TextNode

    from isp_rag.memory.engine import buscar

    class MemoryQueryEngine(CustomQueryEngine):
        ref_date: date | None = None

        def custom_query(self, query_str: str):
            resultados = buscar(query_str, reference_date=self.ref_date, top_k=5)
            nodes = [
                NodeWithScore(
                    node=TextNode(text=r.chunk.text, metadata=r.chunk.model_dump(mode="json")),
                    score=r.score,
                )
                for r in resultados
            ]
            return get_response_synthesizer(llm=llama_llm()).synthesize(query_str, nodes=nodes)

    return MemoryQueryEngine(ref_date=reference_date)


def build_router(
    reference_date: date | None = None,
    brain_enabled: bool = False,
) -> RouterQueryEngine:
    """Domínio único: escolhe uma engine."""
    return RouterQueryEngine(
        selector=LLMSingleSelector.from_defaults(llm=llama_llm()),
        query_engine_tools=build_tools(reference_date, brain_enabled),
        verbose=False,
    )


def build_subquestion_engine(
    reference_date: date | None = None,
    brain_enabled: bool = False,
) -> SubQuestionQueryEngine:
    """Cruza domínios: decompõe em sub-perguntas e sintetiza ao final."""
    return SubQuestionQueryEngine.from_defaults(
        query_engine_tools=build_tools(reference_date, brain_enabled),
        llm=llama_llm(),
        verbose=False,
    )


def route(pergunta: str, *, brain_enabled: bool = False) -> RouteDecision:
    """Decide qual engine atenderia, SEM executar a query.

    É o que a camada de avaliação mede (T11). Executar para descobrir a rota
    custaria uma consulta completa por pergunta do gold set.
    """
    if needs_decomposition(pergunta):
        return RouteDecision(
            engine=None,
            is_multi_domain=True,
            reason="pergunta pede dado numérico e explicação normativa",
        )

    nomes = ["ledger", "memory"] + (["brain"] if brain_enabled else [])
    descricoes = [DESC_LEDGER, DESC_MEMORY] + ([DESC_BRAIN] if brain_enabled else [])
    escolhas = [ToolMetadata(name=n, description=d) for n, d in zip(nomes, descricoes, strict=True)]

    selector = LLMSingleSelector.from_defaults(llm=llama_llm())
    resultado = selector.select(escolhas, query=pergunta)
    idx = resultado.selections[0].index if resultado.selections else 0

    return RouteDecision(
        engine=nomes[idx],
        is_multi_domain=False,
        reason=resultado.selections[0].reason if resultado.selections else None,
    )
