# T12 — Brain: ontologia e carga

**Depende de:** T10 · **Paralelo com:** T11 · **Saída:** a tese do projeto, demonstrada

## Contexto

Esta é a task que fecha o argumento. Até aqui o sistema tem duas camadas, e um
crítico razoável perguntaria se o Neo4j não é container decorativo.

A pergunta de demonstração da spec §3.4 responde isso: *"caiu de B para C entre
2023 e 2025. Foi o desempenho que piorou ou a metodologia que mudou? E qual norma
alterou isso?"* — Ledger dá o delta, Memory dá o texto, Brain diz qual edição
alterou qual critério e por qual norma. Nenhuma responde sozinha.

Princípio da spec §5.3: **schema ambicioso, carga incremental**. Migrar grafo
depois é caro; modele completo agora e popule por etapas.

---

## PROMPT

````
Você vai implementar o Brain do ISP-RAG: o grafo de normas, critérios e
indicadores no Neo4j.

## Princípio de projeto

Schema ambicioso, carga incremental. A ontologia é modelada COMPLETA desde o
início — migrar grafo depois é caro — mas povoada por etapas. Esta task carrega
o subgrafo obtenível dos documentos de metodologia do ISP; a cadeia normativa
completa fica como stub documentado.

## Entregáveis

### 1. src/isp_rag/brain/ontology.cypher

  Nós:     Norma · Dispositivo · Edicao · Criterio · Indicador · Ente
  Arestas: REVOGA · ALTERA · REGULAMENTA · FUNDAMENTA · COMPOE · CONSOME_CAMPO

  Constraints de unicidade:
    Norma(identificador)        — "portaria-mtp-1467-2022"
    Dispositivo(norma, artigo)  — composta
    Edicao(ano)
    Criterio(edicao_ano, nome)  — critério é por edição: o mesmo nome pode
                                  ter definição diferente entre edições, e é
                                  exatamente isso que a pergunta de demo explora
    Indicador(edicao_ano, nome)
    Ente(cnpj)

  Índices em: Norma(numero), Dispositivo(artigo), Criterio(nome),
              Indicador(nome)

  Propriedades mínimas por nó — documente cada uma no arquivo:
    Norma: identificador, tipo, numero, ano, data, orgao, url, situacao
    Dispositivo: norma, artigo, texto_ref, situacao,
                 data_inicio_vigencia, data_fim_vigencia
    Edicao: ano, metodologia_ref, url_fonte
    Criterio: edicao_ano, nome, peso, descricao
    Indicador: edicao_ano, nome, formula, unidade, peso, campo_origem
    Ente: cnpj, nome, uf

  Semântica das arestas (comente no arquivo):
    (Edicao)-[:COMPOE]->(Criterio)           edição tem critérios
    (Criterio)-[:COMPOE]->(Indicador)        critério tem indicadores
    (Norma)-[:REVOGA]->(Norma)
    (Norma)-[:ALTERA {dispositivo}]->(Norma)
    (Norma)-[:REGULAMENTA]->(Edicao)         a portaria que rege a edição
    (Dispositivo)-[:FUNDAMENTA]->(Criterio)  o dispositivo que embasa o critério
    (Dispositivo)-[:CONSOME_CAMPO]->(Indicador)  linhagem normativa

### 2. src/isp_rag/brain/loader.py

  def load_ontology() -> None:
      """Aplica constraints e índices. Idempotente."""

  def load_metodologia(ano: int) -> LoadReport:
      """
      Carrega Edicao -[:COMPOE]-> Criterio -[:COMPOE]-> Indicador a partir dos
      documentos de metodologia do ISP já coletados (T03) e parseados.

      Fonte: relatório técnico e nota metodológica da edição. Extraia a árvore
      de critérios e indicadores com seus pesos.

      Se a estrutura não for extraível automaticamente do PDF, crie
      eval/../data/ontologia_<ano>.yaml preenchido MANUALMENTE a partir do
      documento oficial, e carregue dele. Mapeamento manual a partir de fonte
      pública é legítimo — o que R1 proíbe é DADO entrar por cópia manual,
      não estrutura ser mapeada por leitura do documento. Documente a decisão.
      """

  def load_normas_basicas() -> None:
      """Nós Norma para as normas já no Memory, com REGULAMENTA para as edições
      que elas regem."""

  # Stubs documentados — v2+, NÃO implemente agora:
  def load_cadeia_normativa() -> None:
      """TODO v2+: REVOGA/ALTERA entre normas.
      Fonte: cláusulas de revogação no texto ('Revoga-se a Portaria X').
      Requer parsing das disposições finais."""

  def load_linhagem() -> None:
      """TODO v2+: Dispositivo -[:CONSOME_CAMPO]-> Indicador.
      É a rastreabilidade normativa do sistema de indicadores — governança de
      dados expressa em grafo (spec §5.3)."""

  CLI: python -m isp_rag.brain.load --ontology
       python -m isp_rag.brain.load --metodologia 2025

### 3. src/isp_rag/brain/engine.py

  def build_brain_engine() -> QueryEngine:
      """PropertyGraphIndex sobre Neo4jPropertyGraphStore, com llama_llm()."""

  Forneça o schema do grafo no contexto do text-to-cypher — o modelo precisa
  conhecer labels, propriedades e a semântica das arestas para gerar Cypher útil.

  Guarda de segurança, como em T05: bloqueie CREATE, MERGE, DELETE, SET, REMOVE,
  DROP no Cypher gerado. A engine de consulta é somente-leitura.

### 4. Ativação no roteador

  - Ligue brain_enabled=True por padrão em build_router e
    build_subquestion_engine (T08)
  - REMOVA os @pytest.mark.xfail dos testes de brain em tests/test_router.py
  - Habilite o brain na API (T10) e no /health e /sources/brain

### 5. tests/test_brain.py

  - load_ontology() duas vezes não duplica constraint
  - "quais critérios compõem a edição 2025?" → traversal Edicao→Criterio correto
  - "quais indicadores compõem o critério X?" → Criterio→Indicador
  - Cypher com CREATE → bloqueado pela guarda
  - Criterio com mesmo nome em 2023 e 2025 são nós DISTINTOS (chave composta)

  E o teste que fecha o projeto:

  - A PERGUNTA DE DEMONSTRAÇÃO (spec §3.4):
    "O RPPS de <município real> caiu de B para C entre 2023 e 2025. Foi o
     desempenho dele que piorou ou a metodologia que mudou? E qual norma
     alterou isso?"

    Asserte:
      - is_multi_domain=True
      - engines_used contém "ledger", "memory" E "brain"
      - sub_questions tem ao menos 2 itens
      - sources contém entradas dos três tipos de engine
      - a resposta não é recusa

    Se o dado real não permitir uma queda B→C, escolha um ente e um par de
    edições que EXISTAM no banco e ajuste a pergunta. Não force o dado para
    caber na pergunta (R4) — ajuste a pergunta ao dado.

## Validação

  docker compose up -d neo4j
  python -m isp_rag.brain.load --ontology
  python -m isp_rag.brain.load --metodologia 2025
  pytest tests/test_brain.py tests/test_router.py -v
  # Neo4j Browser em http://localhost:7474 para inspecionar o grafo
````

---

## Validação

```bash
python -m isp_rag.brain.load --ontology --metodologia 2025
pytest tests/test_brain.py tests/test_router.py -v
```

## Aceite

- [ ] Ontologia **completa** (6 nós, 6 arestas), ainda que a carga seja parcial
- [ ] `Criterio` e `Indicador` com chave composta por edição
- [ ] Subgrafo edição→critério→indicador carregado
- [ ] `load_cadeia_normativa` e `load_linhagem` como stubs documentados
- [ ] Cypher de escrita bloqueado
- [ ] `xfail` de brain removidos em `test_router.py`
- [ ] **A pergunta de demonstração aciona as três engines e cita as três fontes**

> Se o último item passa, a arquitetura de três camadas está justificada por
> comportamento observável — não por argumento no README.
