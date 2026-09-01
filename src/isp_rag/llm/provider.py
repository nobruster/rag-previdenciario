"""Única fronteira com o provedor de LLM em todo o projeto (R5).

Nenhum outro arquivo em `src/` pode importar `openai` — `tests/test_r5_boundary.py`
varre a árvore e falha se isso acontecer. Trocar de provedor deve custar este
arquivo, não um refactor.
"""

from typing import Protocol, runtime_checkable

from isp_rag.config import settings

# Lote de embeddings por chamada. A API aceita mais, mas 100 mantém o payload
# pequeno o suficiente para o retry ser barato.
_EMBED_BATCH = 100


@runtime_checkable
class LLMProvider(Protocol):
    """O que o resto do sistema conhece sobre o provedor."""

    def complete(self, prompt: str, *, model: str | None = None) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIProvider:
    """Implementação sobre a API da OpenAI."""

    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        """Completa um prompt.

        `model=None` usa LLM_MODEL (síntese). O judge da T11 passa
        JUDGE_MODEL explicitamente.

        temperature=0 sempre: este sistema responde sobre norma e número,
        não é criativo.
        """
        response = self._client.chat.completions.create(
            model=model or settings.llm_model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vetoriza em lote, preservando a ordem da entrada."""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = texts[start : start + _EMBED_BATCH]
            response = self._client.embeddings.create(
                model=settings.embed_model,
                input=batch,
            )
            # A API pode devolver fora de ordem; `index` é a garantia.
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Singleton. Trocar de provedor = trocar esta função."""
    global _provider
    if _provider is None:
        _provider = OpenAIProvider()
    return _provider


def llama_llm(model: str | None = None):
    """LLM do LlamaIndex, configurado a partir das mesmas settings.

    As engines das próximas tasks (NLSQLTableQueryEngine, RouterQueryEngine,
    PropertyGraphIndex) recebem este objeto — nunca constroem o seu.
    """
    from llama_index.llms.openai import OpenAI as LlamaOpenAI

    return LlamaOpenAI(
        model=model or settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def llama_embedding():
    """Modelo de embedding do LlamaIndex, para o índice do Memory (T07)."""
    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(
        model=settings.embed_model,
        api_key=settings.openai_api_key,
    )
