"""R5 — `import openai` só em src/isp_rag/llm/provider.py.

Este teste é o mecanismo que mantém a regra viva. Sem ele, o acoplamento volta
por descuido na primeira task que precisar de uma chamada rápida ao modelo.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
FRONTEIRA = SRC / "isp_rag" / "llm" / "provider.py"

# Casa `import openai`, `from openai import ...` e as variantes do LlamaIndex
# (llama_index.llms.openai), que também acoplam a um provedor específico.
PADRAO = re.compile(r"^\s*(?:from|import)\s+[\w.]*\bopenai\b", re.MULTILINE)


def test_import_de_openai_so_no_provider():
    infratores = [
        py.relative_to(SRC).as_posix()
        for py in SRC.rglob("*.py")
        if py != FRONTEIRA and PADRAO.search(py.read_text(encoding="utf-8"))
    ]
    assert not infratores, (
        f"R5 violada em: {infratores}. O acesso ao LLM passa por "
        f"isp_rag.llm.get_provider() / llama_llm() / llama_embedding()."
    )


def test_o_teste_detecta_de_fato(tmp_path):
    """Um teste que nunca falha não protege nada. Confirma que o padrão casa
    com as formas reais de import."""
    for codigo in (
        "import openai\n",
        "from openai import OpenAI\n",
        "from llama_index.llms.openai import OpenAI\n",
        "    import openai  # dentro de função\n",
    ):
        assert PADRAO.search(codigo), f"padrão não casou com: {codigo!r}"

    # E não deve casar com menções em comentário ou string.
    for inocente in ("# usa openai por baixo\n", "PROVIDER = 'openai'\n"):
        assert not PADRAO.search(inocente), f"falso positivo em: {inocente!r}"


def test_llm_init_nao_exporta_implementacao():
    """O resto do sistema conhece a interface, não a implementação."""
    import isp_rag.llm as llm

    assert not hasattr(llm, "OpenAIProvider")
    assert set(llm.__all__) == {"LLMProvider", "get_provider", "llama_llm", "llama_embedding"}
