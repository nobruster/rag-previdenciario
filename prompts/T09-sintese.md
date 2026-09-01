# T09 — Síntese com citação obrigatória e recusa

**Depende de:** T08 · **Saída:** resposta que cita, ou recusa — nunca inventa

## Contexto

O roteador entrega os nodes recuperados. Esta task os transforma em resposta.

É onde R2 e R3 deixam de ser validação de schema e viram comportamento. A spec
§6.3 fecha com a frase que resume o projeto: *"em domínio normativo, um sistema
que inventa um prazo é pior que um sistema que diz não saber"*.

---

## PROMPT

````
Você vai implementar a camada de síntese do ISP-RAG: transformar contexto
recuperado em resposta validada.

## Regras que esta task materializa

R2 — Cada afirmação cita norma+dispositivo ou tabela+edição.
R3 — Sem base no contexto, o sistema RECUSA. Recusa correta é métrica de
     sucesso, não falha.

## Entregáveis

### 1. Prompt de síntese

Constante REFUSAL_PHRASE, usada tanto no prompt quanto na detecção:

  REFUSAL_PHRASE = (
      "Não há base na documentação indexada para responder a essa pergunta."
  )

  SYNTHESIS_PROMPT = """Você responde perguntas sobre a previdência pública
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

CONTEXTO:
{context}

PERGUNTA: {question}

RESPOSTA:"""

Não invente um prompt "melhorado" que suavize estas regras. A dureza é o produto.

### 2. src/isp_rag/query/synthesizer.py

  def build_context(nodes: list[NodeWithScore]) -> str:
      """
      Formata os nodes para o prompt. Cada bloco identificado, para o modelo
      conseguir citar:

        [FONTE 1 | Portaria MTP nº 1.467/2022, art. 241 | vigente]
        TÍTULO II > CAPÍTULO III > Art. 241
        <texto do artigo>

        [FONTE 2 | isp_resultado, ed. 2025]
        <resultado tabular>
      """

  def extract_sources(nodes, engines_used) -> list[Source]:
      """
      Monta Source a partir dos metadados. Para memory: ref = "{norma}, art. {n}",
      url e snippet (text_raw truncado em ~300 chars). Para ledger:
      ref = "{tabela}, ed. {ano}".
      """

  def is_refusal(answer: str) -> bool:
      """Normaliza (lower, sem acento, sem pontuação) e compara com
      REFUSAL_PHRASE. Tolerante a pequenas variações do modelo."""

  def synthesize(question, nodes, engines_used, sub_questions=None) -> QueryResponse:
      """
      1. Se nodes vazio → retorna QueryResponse com REFUSAL_PHRASE,
         sources=[], refused=True. NÃO chama o LLM (economia e determinismo).
      2. Monta contexto, chama llama_llm(temperature=0).
      3. Se is_refusal(answer) → refused=True, sources=[].
      4. Senão → extract_sources(). Se vier vazio mesmo com nodes,
         é bug: logue WARNING e trate como recusa, em vez de emitir resposta
         sem fonte (R2 não pode ser violada nem por bug).
      """

### 3. Verificação de citação (opcional mas recomendado)

  def has_citation(answer: str) -> bool:
      """Detecta se a resposta contém ao menos um padrão de citação
      — (Norma, art. N) ou (tabela, ed. AAAA)."""

  Se a resposta não tem citação e não é recusa, logue WARNING. T11 vai medir
  isso como "precisão da citação" — aqui só instrumente.

### 4. tests/test_synthesizer.py

  - nodes=[] → refused=True, answer == REFUSAL_PHRASE, LLM não é chamado
    (use mock e asserte call_count == 0)
  - contexto com art. 241 → sources não-vazio, sources[0].ref contém "241"
  - LLM devolve a frase de recusa → refused=True e sources=[] (e o
    QueryResponse valida, provando que R3 funciona junto de R2)
  - pergunta com premissa falsa ("o art. 999 da Portaria 1.467 exige o quê?")
    → a resposta menciona que o dispositivo não existe/não foi encontrado
  - is_refusal() tolera "Nao ha base na documentacao indexada..." sem acento
  - resposta com sources vazio mas nodes não-vazio → tratada como recusa,
    nunca emitida como resposta sem fonte

## Validação

  pytest tests/test_synthesizer.py -v
````

---

## Validação

```bash
pytest tests/test_synthesizer.py -v
```

## Aceite

- [ ] `REFUSAL_PHRASE` única, usada no prompt e na detecção
- [ ] `nodes=[]` recusa **sem** chamar o LLM
- [ ] Recusa produz `refused=True` + `sources=[]` que passa na validação
- [ ] Contexto formatado com fontes identificadas
- [ ] Premissa falsa é corrigida, não respondida
- [ ] Bug que zeraria `sources` vira recusa, nunca resposta sem fonte
- [ ] As 4 regras do prompt preservadas na íntegra
