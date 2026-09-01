# T02 — Contratos Pydantic e provider de LLM

**Depende de:** T01 · **Paralelo com:** T03 · **Saída:** contratos que fazem R2/R3 falharem em runtime

## Contexto

T01 deixou o scaffold de pé: `settings` carrega do `.env`, os três serviços sobem.
Esta task cria as duas peças que todo o resto importa — o contrato de resposta e
a fronteira com o provedor de LLM.

Ela e a T03 são independentes; podem rodar em paralelo.

---

## PROMPT

````
Você vai implementar os contratos Pydantic e a camada de acesso ao LLM do projeto
ISP-RAG. Estas duas peças são importadas por praticamente todo o resto do sistema,
então as assinaturas abaixo são fixas.

## Regras que esta task materializa

R2 — Resposta sem fonte é erro de contrato. Não é questão de estilo: a validação
     Pydantic tem que FALHAR. Em domínio normativo, uma afirmação sem dispositivo
     citado é inútil.
R3 — Recusar é sucesso. O único caso em que sources pode ser vazio é uma recusa
     explícita.
R5 — O provedor de LLM fica atrás de uma interface. Trocar OpenAI por outro
     provedor deve custar um arquivo, não um refactor.

## Entregáveis

### 1. src/isp_rag/contracts.py

  from typing import Literal
  from datetime import date
  from pydantic import BaseModel, Field, field_validator, ValidationInfo

  EngineName = Literal["ledger", "memory", "brain"]

  class Source(BaseModel):
      """Toda afirmação factual rastreia até uma destas."""
      engine: EngineName
      ref: str          # "Portaria MTP 1.467/2022, art. 241"
                        # ou "isp_resultado, ed. 2025"
      url: str | None = None
      snippet: str | None = None

  class QueryRequest(BaseModel):
      question: str = Field(min_length=3, max_length=2000)
      reference_date: date | None = None   # filtro de vigência
      engines: list[EngineName] | None = None   # força engines; None = roteia

  class QueryResponse(BaseModel):
      answer: str
      sources: list[Source]
      engines_used: list[EngineName]
      sub_questions: list[str] = []
      refused: bool = False

      @field_validator("sources")
      @classmethod
      def _sources_required(cls, v: list[Source], info: ValidationInfo):
          if not v and not info.data.get("refused"):
              raise ValueError(
                  "resposta sem fonte viola R2: toda afirmação precisa citar "
                  "dispositivo normativo ou tabela+edição"
              )
          return v

ATENÇÃO à ordem dos campos: `refused` precisa ser declarado ANTES de `sources`
OU o validator precisa lidar com a ausência da chave em info.data. Pydantic v2
valida na ordem de declaração e info.data só contém os campos já validados.
Escolha uma das duas soluções e deixe um comentário explicando.

### 2. src/isp_rag/llm/provider.py

  from typing import Protocol

  class LLMProvider(Protocol):
      def complete(self, prompt: str, *, model: str | None = None) -> str: ...
      def embed(self, texts: list[str]) -> list[list[float]]: ...

  class OpenAIProvider:
      """Única fronteira com a OpenAI em todo o projeto (R5)."""
      def __init__(self) -> None:
          from openai import OpenAI
          self._client = OpenAI(api_key=settings.openai_api_key)

      def complete(self, prompt, *, model=None) -> str:
          # usa settings.llm_model por padrão; o judge passa settings.judge_model
          # temperature=0 — este sistema não é criativo
          ...

      def embed(self, texts) -> list[list[float]]:
          # settings.embed_model, batch de até 100 textos por chamada
          ...

  _provider: LLMProvider | None = None

  def get_provider() -> LLMProvider:
      """Singleton. Trocar de provedor = trocar esta função."""
      ...

Adicione também um helper que devolve os objetos do LlamaIndex configurados a
partir das mesmas settings, para as engines das próximas tasks:

  def llama_llm(model: str | None = None):   # -> llama_index OpenAI LLM
  def llama_embedding():                     # -> OpenAIEmbedding

### 3. src/isp_rag/llm/__init__.py

Reexporta APENAS: get_provider, LLMProvider, llama_llm, llama_embedding.
Nada de OpenAIProvider — o resto do sistema não deve conhecer a implementação.

### 4. tests/test_contracts.py

  - QueryResponse(answer="x", sources=[], engines_used=["ledger"])
      → ValidationError (R2)
  - QueryResponse(answer="Não há base...", sources=[], engines_used=["memory"],
                  refused=True)
      → válido (R3)
  - QueryResponse com 1 Source → válido, e sources[0].ref preservado
  - QueryRequest(question="ab") → ValidationError (min_length=3)
  - QueryRequest(question="Qual a nota?", reference_date=date(2024,1,1))
      → válido

### 5. tests/test_r5_boundary.py

Teste que FALHA se R5 for violada. Varre recursivamente src/ procurando
"import openai" ou "from openai" e falha se aparecer em qualquer arquivo que
não seja src/isp_rag/llm/provider.py.

  def test_openai_import_only_in_provider():
      offenders = []
      for py in Path("src").rglob("*.py"):
          if py.name == "provider.py" and py.parent.name == "llm":
              continue
          text = py.read_text(encoding="utf-8")
          if "import openai" in text or "from openai" in text:
              offenders.append(str(py))
      assert not offenders, f"R5 violada em: {offenders}"

Este teste vai rodar em CI e é o que impede o acoplamento de voltar por descuido
em qualquer task futura.

## Validação

  pytest tests/test_contracts.py tests/test_r5_boundary.py -v
  python -c "from isp_rag.llm import get_provider; print(get_provider().complete('diga ok'))"
````

---

## Validação

```bash
pytest tests/test_contracts.py tests/test_r5_boundary.py -v
python -c "from isp_rag.llm import get_provider; print(get_provider().complete('diga ok'))"
```

## Aceite

- [ ] `sources=[]` com `refused=False` levanta `ValidationError`
- [ ] `sources=[]` com `refused=True` é válido
- [ ] `test_r5_boundary` passa e realmente falharia se um `import openai` fosse plantado fora do provider
- [ ] `llm/__init__.py` não exporta `OpenAIProvider`
- [ ] `complete()` usa `temperature=0`
