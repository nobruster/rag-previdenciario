# T11 — Gold set e métricas

**Depende de:** T10 · **Paralelo com:** T12 · **Saída:** o sistema deixa de "funcionar no demo" e passa a ser medido

## Contexto

A spec §7.1 diz que esta camada *"é o que mais frequentemente falta em projetos
de RAG — inclusive no material de referência que originou este desenho, cuja
validação é descrita como 'testes cruzados no terminal'"*.

Ela também avisa do erro mais comum: tratar como uma coisa só o que são **três
coisas distintas para medir**. Roteamento, recuperação e geração têm métricas
diferentes, custos diferentes e falham por motivos diferentes.

---

## PROMPT

````
Você vai construir a camada de avaliação do ISP-RAG. Não a trate como teste
automatizado comum: é o entregável que distingue um sistema que funciona no demo
de um sistema que se SABE que funciona.

## Regras aplicáveis

R4 — O gold set é escrito MANUALMENTE a partir dos dados reais já carregados.
     Não gere perguntas sinteticamente com LLM. Um gold set gerado pelo mesmo
     tipo de modelo que será avaliado mede concordância, não correção.

## Entregáveis

### 1. eval/gold_set.json — 40 perguntas, 8 por categoria

  Schema por item:
    {
      "id": "gs-001",
      "question": "...",
      "category": "fato_numerico" | "exigencia_normativa" |
                  "comparacao_edicoes" | "capciosa" | "sem_resposta",
      "expected_engine": "ledger" | "memory" | "brain" | "multi",
      "reference_sql": "SELECT ...",        // só fato_numerico/comparacao
      "expected_source_ref": "Portaria MTP 1.467/2022, art. 241",  // só normativa
      "should_refuse": false,
      "notes": "por que esta pergunta está no set"
    }

  As cinco categorias (spec §7.2):

  fato_numerico (8)      — resolvida pelo Ledger. Nota de um ente, contagem,
                           média, ranking. Tem reference_sql.
  exigencia_normativa(8) — resolvida pelo Memory. Prazo, requisito, definição.
                           Tem expected_source_ref.
  comparacao_edicoes (8) — exige Ledger e, dependendo da formulação, Brain.
                           Delta entre edições, evolução de conceito.
  capciosa (8)           — cita norma REVOGADA ou critério de edição em que ele
                           não existia. O sistema deve CORRIGIR a premissa.
                           should_refuse=false — corrigir não é recusar.
  sem_resposta (8)       — fora do escopo da base. should_refuse=true.
                           Ex.: "qual a alíquota do INSS do RGPS?" (é RGPS, não
                           RPPS), "qual a nota do RPPS de Lisboa?"

  IMPORTANTE: escreva as perguntas a partir dos dados REAIS já no banco. Consulte
  o Postgres para pegar municípios e notas que existem. Uma pergunta sobre um
  ente que não está na base não mede o sistema — mede a base.

  Deixe as 40 escritas mas marque com "todo": true aquelas cujo dado você não
  conseguiu confirmar, para revisão humana.

  ATENÇÃO — T11 pode rodar ANTES da T12 (são paralelas). Itens com
  expected_engine "brain" ou "multi" ainda não têm engine para atender.

  Adicione ao schema:
    "requires": ["ledger"] | ["memory"] | ["brain"] | ["ledger","brain"] ...

  Os runners PULAM (status "skipped", não "failed") os itens cujo `requires`
  inclui uma engine indisponível, e o resumo reporta quantos foram pulados:

    ROTEAMENTO    acurácia 0.92  (33/36)   [4 pulados: brain indisponível]

  Detecte a disponibilidade em runtime (GET /sources/brain ou tentativa de
  conexão), não por flag hardcoded. Depois da T12 os mesmos itens passam a
  contar sozinhos, sem editar o gold set.

  Isso importa: um item pulado por dependência ausente NÃO é uma falha de
  qualidade, e misturar os dois corrompe a leitura da métrica.

### 2. eval/runners/routing.py

  Métrica: acurácia + matriz de confusão sobre expected_engine.
  Determinística, barata, roda em segundos. Usa route() da T08 — decide sem
  executar.

  Saída: acurácia global, por categoria, e a matriz (esperado × obtido).

### 3. eval/runners/sql_match.py — EXECUTION MATCH

  Para itens com reference_sql:
    1. gera o SQL via engine do Ledger (get_sql da T05)
    2. executa o gerado e o de referência (run_sql)
    3. compara os RESULTSETS

  Normalização antes de comparar: ordena linhas, ordena colunas por nome,
  arredonda NUMERIC em 4 casas, trata None == NULL.

  NUNCA compare as strings de SQL. Dois SQLs diferentes podem estar ambos
  corretos — é o erro que a spec §7.3 aponta nominalmente.

  Reporte: match exato, mismatch (com os dois resultsets no output para
  diagnóstico), erro de execução.

### 4. eval/runners/retrieval.py

  Recall@k (k=1,3,5), MRR, e a pergunta direta: "o dispositivo correto apareceu
  no top-5?". Usa expected_source_ref.
  Determinística, ZERO custo de LLM (só embedding da pergunta).

### 5. eval/runners/generation.py — LLM-as-judge

  Modelo: settings.judge_model (gpt-4o). É o custo dominante das rodadas.

  Rubrica EXPLÍCITA, 0-2 por eixo:

    fidelidade_ao_contexto:
      0 = afirma o que não está no contexto
      1 = parcialmente ancorado, alguma extrapolação
      2 = inteiramente ancorado no contexto

    precisao_da_citacao:
      0 = sem citação, ou citação inexistente/errada
      1 = cita, mas impreciso (norma certa, artigo errado)
      2 = citação correta e verificável

    recusa_correta:
      0 = deveria recusar e respondeu, ou recusou tendo base
      1 = comportamento ambíguo
      2 = recusou quando devia, respondeu quando devia

  O judge recebe: pergunta, contexto recuperado, resposta, e o item do gold set.
  Devolve JSON com as três notas e uma justificativa por eixo.

  Suporte a --sample N para rodar em amostra durante desenvolvimento.

### 6. eval/run_all.py

  python -m eval.run_all                      # tudo
  python -m eval.run_all --deterministic-only # pula o judge (grátis)
  python -m eval.run_all --sample 10          # amostra do judge

  Grava eval/runs/<timestamp>.json e imprime tabela resumo:

    ROTEAMENTO    acurácia 0.92  (37/40)
    TEXT-TO-SQL   exec match 0.87 (14/16)
    RECUPERAÇÃO   recall@5 0.94  MRR 0.81
    GERAÇÃO       fidelidade 1.8  citação 1.7  recusa 1.9   [amostra: 10]

### 7. .github/workflows/eval.yml

  A cada push: sobe os serviços via compose, carrega uma edição, roda os runners
  DETERMINÍSTICOS (routing, sql_match, retrieval). O judge NÃO roda em push —
  só em tag de versão, por causa do custo.

  Falha o build se a acurácia de roteamento cair abaixo de um limiar
  configurável (comece em 0.85).

### 8. Regressão entre versões (spec §7.4)

  eval/runners/compare.py — compara dois runs e imprime o delta por métrica.
  Serve para documentar a evolução: chunking ingênuo → chunk por artigo →
  recuperação híbrida → com filtro de vigência.

  Gere também eval/METRICS.md com a tabela histórica, para o README linkar.

## Validação

  python -m eval.run_all --deterministic-only
  cat eval/runs/*.json | jq '.summary'
````

---

## Validação

```bash
python -m eval.run_all --deterministic-only
python -m eval.run_all --sample 5
```

## Aceite

- [ ] 40 perguntas, 8 por categoria, escritas manualmente sobre dados reais (R4)
- [ ] `sql_match` compara **resultsets**, nunca strings de SQL
- [ ] Runners determinísticos rodam sem custo de LLM
- [ ] Judge com rubrica explícita 0–2 e `--sample`
- [ ] Categoria `capciosa` espera correção da premissa, não recusa
- [ ] CI roda só os determinísticos; judge fica para tag de versão
- [ ] `compare.py` permite documentar a evolução entre versões
