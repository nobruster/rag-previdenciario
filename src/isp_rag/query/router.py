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
    "Banco de dados com o RESULTADO PUBLICADO do ISP por ente federativo e por "
    "edição. Responde apenas o que é NÚMERO ou LETRA já apurada de um ente "
    "concreto.\n"
    "USE quando a pergunta pede: o conceito de um município ou estado nomeado; "
    "contagem, ranking, média ou distribuição de entes; comparação de resultado "
    "entre edições.\n"
    "NÃO USE para 'o que é', 'como funciona', 'o que a norma exige', 'quais os "
    "requisitos', 'quais as medidas' — mesmo que o assunto seja do domínio "
    "previdenciário. Isso é definição ou regra, e está no memory.\n"
    "Exemplos: 'qual o conceito do RPPS de Campinas em 2025', 'quantos entes "
    "tiveram conceito A', 'qual UF tem mais RPPS avaliados'."
)

DESC_MEMORY = (
    "Texto integral das normas dos RPPS: Portaria MTP 1.467/2022, Leis "
    "9.717/1998 e 10.887/2004, Emendas Constitucionais 20/1998, 41/2003, "
    "47/2005 e 103/2019.\n"
    "USE quando a pergunta pede CONCEITO, DEFINIÇÃO, REGRA ou EXIGÊNCIA — "
    "tudo que começa com 'o que é', 'o que significa', 'quais são as', 'quais "
    "os requisitos', 'como funciona', 'o que a norma exige', 'qual o prazo' — "
    "e também o conteúdo de um artigo citado.\n"
    "É a engine correta para qualquer pergunta sobre institutos do domínio "
    "(equacionamento de déficit, compensação previdenciária, certificação "
    "institucional, Pró-Gestão, segurado, dependente), porque são definidos em "
    "norma, não medidos por ente.\n"
    "Exemplos: 'o que exige o art. 241', 'quais os requisitos para emissão do "
    "CRP', 'o que é a compensação previdenciária', 'quais são as medidas de "
    "equacionamento do déficit atuarial'."
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
# Metodologia do índice: como o ISP é apurado, quais critérios o compõem.
_METODOLOGIA = re.compile(
    r"\b(metodologia|tercil|corte|crit[ée]rio|indicador(?:es)? parcia|"
    r"como (?:o )?ISP|comp[õo]e|composi[çc][ãa]o|atribui|apura)\w*\b",
    re.IGNORECASE,
)
_EDICAO = re.compile(r"\b(20\d{2}|edi[çc][ãa]o|edi[çc][õo]es)\b", re.IGNORECASE)


class RouteDecision(BaseModel):
    engine: EngineName | None = None
    """None quando a pergunta cruza domínios."""

    is_multi_domain: bool = False
    reason: str | None = None


def needs_decomposition(pergunta: str) -> bool:
    """Heurística barata ANTES de gastar chamada de LLM.

    A pergunta de demonstração da spec §3.4 é o caso canônico: pede o delta
    numérico E a norma que o explica.

    O terceiro caso — metodologia cruzada com edição — não tem termo numérico
    ("o que mudou na metodologia do ISP em 2025?"), mas exige o Ledger para o
    dado e o Memory para a regra. Sem ele, essas perguntas caem numa engine só.
    """
    tem_num = bool(_NUMERICO.search(pergunta))
    tem_norma = bool(_NORMATIVO.search(pergunta))
    tem_mudanca = bool(_MUDANCA.search(pergunta))
    metodologia_por_edicao = bool(_METODOLOGIA.search(pergunta) and _EDICAO.search(pergunta))
    return (tem_num and tem_norma) or (tem_num and tem_mudanca) or metodologia_por_edicao


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
    """Cruza domínios: decompõe em sub-perguntas e sintetiza ao final.

    O question_generator é passado explicitamente: o default de
    `from_defaults` importa `llama_index.question_gen.openai`, cujo pacote
    ainda exige llama-index-core <0.13 e forçaria um downgrade do core.
    """
    from llama_index.core.question_gen import LLMQuestionGenerator

    llm = llama_llm()
    return SubQuestionQueryEngine.from_defaults(
        query_engine_tools=build_tools(reference_date, brain_enabled),
        llm=llm,
        question_gen=LLMQuestionGenerator.from_defaults(llm=llm),
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
