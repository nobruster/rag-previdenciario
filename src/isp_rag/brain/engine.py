"""Consulta ao grafo — text-to-Cypher sobre o Brain.

Mesma guarda do Text-to-SQL (T05): a engine de consulta é somente leitura.
Um LLM não deve conseguir escrever no grafo nem por acidente nem por prompt
injection vinda do texto de uma pergunta.
"""

import re
from typing import Any

from llama_index.core import PropertyGraphIndex
from llama_index.core.query_engine import CustomQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from isp_rag.brain.loader import get_driver
from isp_rag.config import settings
from isp_rag.llm import llama_embedding, llama_llm

CYPHER_PROIBIDO = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+apoc\.\w*\.(create|merge))\b",
    re.IGNORECASE,
)

SCHEMA = """O grafo modela a metodologia do ISP-RPPS.

NÓS
  (:Edicao {ano, regime_metodologico, n_entes, url_fonte})
  (:Criterio {edicao_ano, nome, descricao})    nome: gestao_transparencia,
                                               financas_liquidez, atuaria
  (:Indicador {edicao_ano, nome, dimensao})    ex.: cobertura_previdenciaria,
                                               regularidade, suficiencia_financeira
  (:Norma {identificador, tipo, numero, ano, nome})
  (:Ente {cnpj, nome, uf})                     nome MAIÚSCULO com UF: 'CAMPINAS - SP'

ARESTAS
  (:Edicao)-[:COMPOE]->(:Criterio)
  (:Criterio)-[:COMPOE]->(:Indicador)
  (:Norma)-[:REGULAMENTA]->(:Edicao)

IMPORTANTE
  Criterio e Indicador são POR EDIÇÃO — sempre filtre por edicao_ano, ou a
  mesma consulta mistura edições cujas definições podem diferir.
"""


class CypherSafetyError(RuntimeError):
    """Cypher gerado que não é somente leitura."""


def assert_somente_leitura(cypher: str) -> None:
    if not cypher or not cypher.strip():
        raise CypherSafetyError("Cypher vazio")
    limpo = re.sub(r"//[^\n]*", " ", cypher)
    if CYPHER_PROIBIDO.search(limpo):
        raise CypherSafetyError(f"Cypher contém comando de escrita: {cypher[:120]}")


def run_cypher(cypher: str, **params) -> list[dict]:
    """Executa Cypher de leitura e devolve os registros."""
    assert_somente_leitura(cypher)
    with get_driver() as driver, driver.session(default_access_mode="READ") as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _graph_store() -> Neo4jPropertyGraphStore:
    return Neo4jPropertyGraphStore(
        username=settings.neo4j_user,
        password=settings.neo4j_password,
        url=settings.neo4j_uri,
    )


def build_brain_engine() -> Any:
    """Engine de consulta sobre o grafo.

    Usa um CustomQueryEngine com text-to-Cypher próprio, em vez do retriever
    padrão do PropertyGraphIndex: precisamos da guarda somente-leitura e do
    schema explícito, e o retriever padrão não expõe o Cypher gerado.
    """
    llm = llama_llm()

    class BrainQueryEngine(CustomQueryEngine):
        def custom_query(self, query_str: str):
            prompt = (
                f"{SCHEMA}\n"
                f"Escreva UMA consulta Cypher somente-leitura que responda à "
                f"pergunta. Devolva apenas o Cypher, sem explicação e sem "
                f"blocos de markdown.\n\nPERGUNTA: {query_str}\n\nCYPHER:"
            )
            cypher = str(llm.complete(prompt)).strip()
            cypher = re.sub(r"^```(?:cypher)?|```$", "", cypher, flags=re.MULTILINE).strip()

            try:
                registros = run_cypher(cypher)
            except CypherSafetyError:
                raise
            except Exception as exc:
                registros = [{"erro": f"consulta falhou: {exc}"}]

            texto = "\n".join(str(r) for r in registros[:50]) or "(sem resultados)"
            node = NodeWithScore(
                node=TextNode(
                    text=texto,
                    metadata={"ref": "Brain — grafo do ISP", "cypher": cypher},
                ),
                score=1.0,
            )
            return get_response_synthesizer(llm=llm).synthesize(query_str, nodes=[node])

    return BrainQueryEngine(llm=llm, embed_model=llama_embedding())


def build_property_graph_index() -> PropertyGraphIndex:
    """PropertyGraphIndex sobre o grafo já carregado.

    Mantido para as fases v2+ (linhagem e cadeia normativa), quando a
    exploração semântica do grafo passar a valer.
    """
    return PropertyGraphIndex.from_existing(
        property_graph_store=_graph_store(),
        llm=llama_llm(),
        embed_model=llama_embedding(),
    )
