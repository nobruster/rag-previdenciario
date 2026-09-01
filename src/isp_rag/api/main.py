"""Camada de serving do ISP-RAG.

Toda resposta passa pelo contrato Pydantic. Violação de R2 em runtime é BUG DO
SISTEMA (500), não erro do cliente (4xx) — um 4xx faria o usuário achar que a
pergunta dele estava errada.
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from llama_index.core.schema import NodeWithScore, TextNode
from pydantic import ValidationError

from isp_rag.config import settings
from isp_rag.contracts import EngineName, QueryRequest, QueryResponse
from isp_rag.ledger.engine import SQLSafetyError, checar_regimes, get_sql, run_sql
from isp_rag.query.router import needs_decomposition, route
from isp_rag.query.synthesizer import synthesize

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("isp_rag.api")

BRAIN_ENABLED = False  # ligado na T12


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Constrói as engines UMA vez. Por request custaria segundos."""
    from isp_rag.ledger.engine import build_ledger_engine
    from isp_rag.query.router import _memory_query_engine, build_subquestion_engine

    app.state.ledger = build_ledger_engine()
    app.state.memory = _memory_query_engine()
    app.state.subq = build_subquestion_engine(brain_enabled=BRAIN_ENABLED)
    log.info("engines prontas")
    yield


app = FastAPI(
    title="ISP-RAG",
    description="RAG multi-fonte sobre a previdência pública brasileira",
    version="0.1.0",
    lifespan=lifespan,
)


def _nodes_do_ledger(resposta: Any) -> tuple[list[NodeWithScore], str | None]:
    """Converte a resposta do Text-to-SQL em nodes, com a ressalva de regime.

    A checagem de regimes é determinística e roda aqui, entre a execução e a
    síntese — não confiada ao LLM (plan.md §7.1).
    """
    sql = get_sql(resposta)
    ressalva = None
    linhas: list[tuple] = []

    if sql:
        try:
            linhas = run_sql(sql)
            ressalva = checar_regimes(linhas, sql)
        except (SQLSafetyError, psycopg.Error) as exc:
            log.warning("falha ao reexecutar o SQL para checagem de regime: %s", exc)

    texto = str(resposta).strip()
    if not texto:
        return [], ressalva

    node = TextNode(
        text=texto,
        metadata={"ref": f"Ledger do ISP{f' — {sql}' if sql else ''}"[:200], "sql": sql},
    )
    return [NodeWithScore(node=node, score=1.0)], ressalva


def _nodes_do_memory(pergunta: str, reference_date) -> list[NodeWithScore]:
    from isp_rag.memory.engine import buscar

    return [
        NodeWithScore(
            node=TextNode(text=r.chunk.text, metadata=r.chunk.model_dump(mode="json")),
            score=r.score,
        )
        for r in buscar(pergunta, reference_date=reference_date, top_k=5)
    ]


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, request: Request) -> QueryResponse:
    inicio = time.perf_counter()
    engines: list[EngineName] = []
    nodes: list[NodeWithScore] = []
    sub_questions: list[str] = []
    ressalva: str | None = None

    forcadas = req.engines
    multi = forcadas is None and needs_decomposition(req.question)

    if multi:
        resposta = request.app.state.subq.query(req.question)
        engines = ["ledger", "memory"] + (["brain"] if BRAIN_ENABLED else [])
        nodes = list(getattr(resposta, "source_nodes", []) or [])
        sub_questions = [
            str(n.node.metadata.get("sub_question", "")) for n in nodes if n.node.metadata
        ]
        sub_questions = [s for s in sub_questions if s]
        if not nodes:
            nodes = [NodeWithScore(node=TextNode(text=str(resposta), metadata={}), score=1.0)]
    else:
        alvo = forcadas[0] if forcadas else (route(req.question).engine or "memory")
        engines = [alvo]
        if alvo == "ledger":
            nodes, ressalva = _nodes_do_ledger(request.app.state.ledger.query(req.question))
        else:
            nodes = _nodes_do_memory(req.question, req.reference_date)

    resultado = synthesize(
        req.question, nodes, engines, sub_questions=sub_questions, ressalva=ressalva
    )

    log.info(
        json.dumps(
            {
                "question": req.question[:200],
                "engines_used": resultado.engines_used,
                "multi_domain": multi,
                "n_sources": len(resultado.sources),
                "refused": resultado.refused,
                "latency_ms": round((time.perf_counter() - inicio) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return resultado


@app.get("/health")
async def health() -> JSONResponse:
    """Checa os três serviços de verdade, não só se a app subiu."""
    servicos: dict[str, str] = {}

    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=3) as c, c.cursor() as k:
            k.execute("SELECT 1")
        servicos["postgres"] = "ok"
    except Exception as exc:
        servicos["postgres"] = f"erro: {type(exc).__name__}"

    try:
        from isp_rag.memory.indexer import get_client

        get_client().get_collections()
        servicos["qdrant"] = "ok"
    except Exception as exc:
        servicos["qdrant"] = f"erro: {type(exc).__name__}"

    if not BRAIN_ENABLED:
        servicos["neo4j"] = "disabled"
    else:
        try:
            from neo4j import GraphDatabase

            with GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            ) as d:
                d.verify_connectivity()
            servicos["neo4j"] = "ok"
        except Exception as exc:
            servicos["neo4j"] = f"erro: {type(exc).__name__}"

    essenciais = [servicos["postgres"], servicos["qdrant"]]
    if all(s.startswith("erro") for s in essenciais):
        return JSONResponse({"status": "down", "services": servicos}, status_code=503)

    degradado = any(s.startswith("erro") for s in servicos.values())
    return JSONResponse({"status": "degraded" if degradado else "ok", "services": servicos})


@app.get("/sources/{engine}")
async def sources(engine: EngineName) -> dict:
    """O que está indexado — serve para saber o que o sistema PODE responder."""
    if engine == "ledger":
        with psycopg.connect(settings.postgres_dsn) as c, c.cursor() as k:
            k.execute(
                """SELECT e.ano, e.regime_metodologico, count(r.cnpj), e.url_fonte
                     FROM edicao e LEFT JOIN isp_resultado r ON r.edicao_ano = e.ano
                    GROUP BY e.ano, e.regime_metodologico, e.url_fonte
                    ORDER BY e.ano DESC"""
            )
            edicoes = [
                {"ano": a, "regime": rg, "n_entes": n, "url_fonte": u}
                for a, rg, n, u in k.fetchall()
            ]
        return {"engine": "ledger", "edicoes": edicoes}

    if engine == "memory":
        from qdrant_client import models as qm

        from isp_rag.memory.indexer import contar_pontos, get_client

        client = get_client()
        pontos, _ = client.scroll(settings.qdrant_collection, limit=1000, with_payload=True)
        por_norma: dict[str, int] = {}
        por_situacao: dict[str, int] = {}
        for p in pontos:
            norma = p.payload.get("norma", "?")
            por_norma[norma] = por_norma.get(norma, 0) + 1
            s = p.payload.get("situacao", "?")
            por_situacao[s] = por_situacao.get(s, 0) + 1
        _ = qm  # o import documenta a dependência do payload
        return {
            "engine": "memory",
            "total_chunks": contar_pontos(),
            "normas": por_norma,
            "situacao": por_situacao,
        }

    return {"engine": "brain", "status": "disabled", "detail": "habilitado na T12"}


@app.get("/cobertura")
async def cobertura(termo: str) -> dict:
    """O corpus cobre este assunto?

    Serve para distinguir, antes de perguntar, o que o sistema pode responder
    do que ele vai recusar por ausência de base. Ver isp_rag.memory.cobertura.
    """
    from isp_rag.memory.cobertura import cobertura_de

    c = cobertura_de(termo)
    return {
        "termo": c.termo,
        "n_chunks": c.n_chunks,
        "coberto": c.coberto,
        "artigos": c.artigos[:20],
    }


@app.exception_handler(ValidationError)
async def contrato_violado(request: Request, exc: ValidationError) -> JSONResponse:
    """R2 violada em runtime é bug do sistema, não erro do cliente."""
    log.error("violação de contrato: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "contract_violation",
            "detail": "a resposta gerada violou o contrato (R2): resposta sem fonte citada",
            "validation": str(exc)[:500],
        },
    )


@app.exception_handler(SQLSafetyError)
async def sql_bloqueado(request: Request, exc: SQLSafetyError) -> JSONResponse:
    log.error("SQL bloqueado: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "sql_safety", "detail": str(exc)[:300]},
    )
