"""Acesso ao LLM. `OpenAIProvider` fica deliberadamente fora daqui — o resto
do sistema não deve conhecer a implementação, só a interface (R5)."""

from isp_rag.llm.provider import LLMProvider, get_provider, llama_embedding, llama_llm

__all__ = ["LLMProvider", "get_provider", "llama_embedding", "llama_llm"]
