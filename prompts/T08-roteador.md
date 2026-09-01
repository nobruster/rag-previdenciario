# T08 — Roteador

**Depende de:** T05 e T07 · **Saída:** a pergunta escolhe a engine, e a escolha é observável

## Contexto

As duas engines existem: Ledger responde número, Memory responde texto normativo.
Esta task decide qual atende cada pergunta — e prepara o `SubQuestionQueryEngine`
para as perguntas que cruzam domínios (a de demonstração, spec §3.4).

A spec §6.1 é explícita: *"o acerto do roteador é medido, não presumido"*. Por
isso `route()` precisa expor a escolha **sem executar** — é o que T11 mede.

---

## PROMPT

````
Você vai implementar o roteamento de perguntas do ISP-RAG entre as engines.

## Regras aplicáveis

R5 — Selector usa llama_llm(). Sem import de openai.

## Entregáveis

### 1. src/isp_rag/query/router.py

  def build_tools(reference_date=None) -> list[QueryEngineTool]:
      """
      Uma tool por engine. As DESCRIÇÕES decidem o acerto do roteador —
      escreva-as com cuidado, são o prompt de fato.
      """

  Descrição da tool ledger:
    "Dados numéricos do Índice de Situação Previdenciária (ISP) por ente
     federativo e por edição. Use para: notas e conceitos (A a D) de um RPPS,
     rankings, médias, contagens, comparação numérica entre entes ou entre
     edições, memória de cálculo (valor e peso de cada indicador).
     Exemplos: 'qual a nota do RPPS de Campinas em 2025', 'quantos entes
     tiveram conceito A', 'média por UF'."

  Descrição da tool memory:
    "Texto normativo e técnico: Portaria MTP 1.467/2022, Leis 9.717/1998 e
     10.887/2004, Emendas Constitucionais, relatórios e notas metodológicas do
     ISP. Use para: o que a norma EXIGE, prazos, requisitos, definições,
     conteúdo de um artigo, metodologia do índice.
     Exemplos: 'qual o prazo de envio do DIPR', 'o que exige o art. 241',
     'como o ISP calcula o indicador de custeio'."

  Descrição da tool brain (registre já, mas só ative em T12):
    "Relações entre normas, edições, critérios e indicadores: qual norma alterou
     qual critério, o que mudou entre edições e por quê, cadeia de revogação,
     linhagem entre dispositivo normativo e indicador.
     Exemplos: 'que critério mudou entre 2023 e 2025', 'qual portaria alterou o
     cálculo do indicador X'."

  A tool de brain só entra na lista se a flag brain_enabled=True (default False
  até T12). Deixe o ponto de extensão pronto — T12 só liga a flag.

### 2. Router e SubQuestion

  def build_router(reference_date=None, brain_enabled=False) -> RouterQueryEngine:
      """LLMSingleSelector, temperature=0."""

  def build_subquestion_engine(reference_date=None, brain_enabled=False):
      """SubQuestionQueryEngine sobre as mesmas tools. Para perguntas que
      cruzam domínios — como a de demonstração da spec §3.4."""

### 3. route() — a escolha sem a execução

  def route(question: str, *, brain_enabled=False) -> RouteDecision:
      """
      Decide qual engine atenderia, SEM executar a query.
      É o que a camada de avaliação mede (T11).
      """

  class RouteDecision(BaseModel):
      engine: EngineName | None      # None quando é multi-domínio
      is_multi_domain: bool
      reason: str | None = None

### 4. Detecção de multi-domínio

  def needs_decomposition(question: str) -> bool:
      """
      Heurística barata ANTES de gastar chamada de LLM: a pergunta pede
      número E norma juntos? cita duas edições E pergunta 'por quê'?

      Sinais: presença simultânea de termo numérico (nota, conceito, caiu,
      subiu, ranking) e termo normativo (norma, portaria, exige, mudou,
      metodologia, por quê).

      A pergunta de demonstração da spec §3.4 é o caso canônico:
      'caiu de B para C entre 2023 e 2025. Foi o desempenho ou a metodologia
      que mudou? E qual norma alterou isso?'
      """

  Se needs_decomposition → SubQuestionQueryEngine; senão → RouterQueryEngine.

### 5. tests/test_router.py

9 perguntas rotuladas, 3 por engine:

  ledger:  "qual a nota do RPPS de <município> em 2025"
           "quantos entes tiveram conceito A em 2025"
           "qual a média das notas por UF"
  memory:  "qual o prazo para envio do DIPR"
           "o que o art. 241 da Portaria 1.467 exige"
           "quais os requisitos para emissão do CRP"
  brain:   "que critério do ISP mudou entre 2023 e 2025"        [xfail até T12]
           "qual norma alterou o cálculo do indicador de custeio" [xfail até T12]
           "quais indicadores compõem o critério de equilíbrio"   [xfail até T12]

  Mais:
  - a pergunta de demonstração da spec §3.4 → is_multi_domain=True
  - "qual a nota de X em 2025?" → is_multi_domain=False

Marque os de brain com @pytest.mark.xfail(reason="brain entra em T12") e
REMOVA os xfail na T12.

## Validação

  pytest tests/test_router.py -v
  python -c "
  from isp_rag.query.router import route
  for q in ['qual a nota do RPPS de Campinas em 2025',
            'o que o art. 241 exige',
            'caiu de B para C entre 2023 e 2025, foi o desempenho ou a metodologia?']:
      print(route(q), '<-', q)
  "
````

---

## Validação

```bash
pytest tests/test_router.py -v
```

## Aceite

- [ ] Descrições das tools ricas, com exemplos concretos
- [ ] `route()` devolve a escolha **sem executar** a query
- [ ] Pergunta multi-domínio detectada antes de gastar LLM
- [ ] A pergunta de demonstração (§3.4) marcada como multi-domínio
- [ ] Tool de brain registrada mas desligada por flag
- [ ] Testes de brain em `xfail`, para T12 remover
