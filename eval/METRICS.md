# Métricas do ISP-RAG

Resultados das rodadas de avaliação contra o gold set de 40 perguntas.
Rode com `python -m eval.run_all --deterministic-only`.

## Estado atual

| Métrica | Valor | Base |
|---|---|---|
| Roteamento | **0,96** | 25/26 avaliados · 14 pulados |
| Text-to-SQL (execution match) | **0,78–0,89** | 7–8/9 · 2 pulados |
| Recuperação | **1,00** | 4/4 · MRR 0,88 |
| Geração — fidelidade | **2,0** | amostra de 6 |
| Geração — precisão da citação | **1,17** | amostra de 6 |
| Geração — recusa correta | **2,0** | amostra de 6 |

Os pulados não são falhas: são itens que dependem do Brain (T12) ou das
edições 2022–2024, ainda não carregadas. Contá-los como erro mediria a
completude do projeto, não a qualidade do sistema.

O Text-to-SQL varia entre rodadas porque o LLM não é determinístico mesmo com
`temperature=0` — daí a faixa.

## Evolução

| Versão | Roteamento | Text-to-SQL | O que mudou |
|---|---|---|---|
| baseline | 0,74 | 0,67 | primeira rodada |
| gold set corrigido | 0,96 | 0,33 | itens de recusa saíram da métrica de rota; descrições das tools reescritas |
| contexto no `COMMENT ON` | 0,96 | **0,78–0,89** | formatos literais movidos para o comentário da view |

## Três defeitos que a avaliação encontrou

**1. Descrição de tool ambígua** (roteamento 0,74 → 0,96)

Seis perguntas normativas iam para o Ledger. A descrição dizia "conceitos" e
"indicador", termos que aparecem também em pergunta sobre norma. Reescrita com
um bloco explícito de *quando NÃO usar*, e com a observação de que institutos do
domínio (equacionamento, compensação, certificação) são **definidos em norma**,
não medidos por ente.

**2. `custom_table_info` é ignorado para views** (Text-to-SQL 0,33 → 0,78)

O modelo gerava `ente_nome = 'Campinas'` e `grupo = 'Grande Porte'`, mas o dado
é `'CAMPINAS - SP'` e `'GRANDE PORTE'`. Investigando, o contexto que eu passava
ao `SQLDatabase` **nunca chegava ao modelo** — para views, o LlamaIndex usa
apenas o `COMMENT ON` do banco. Os formatos literais foram movidos para lá.

Foi o achado mais valioso da task: um bug de arquitetura que nenhum teste
unitário pegaria, porque cada peça funcionava isoladamente.

**3. O judge não via a fonte** (precisão da citação 0,0 → 1,17)

Todos os itens recebiam 0 em precisão da citação. O motivo era do runner, não
do sistema: eu passava só o `snippet` como contexto, então o judge não tinha
como verificar uma citação a `isp_resultado, ed. 2025` — o identificador não
estava no que ele via. Uma citação correta era punida.

## Como ler os números

- **Roteamento** — determinístico e barato, roda em segundos. Usa `route()`,
  que decide sem executar a query.
- **Text-to-SQL** — *execution match*: compara os RESULTSETS, nunca as strings
  de SQL. Dois SQLs diferentes podem estar ambos corretos.
- **Recuperação** — Recall@5 e MRR. Itens sem cobertura no corpus ficam **fora
  do denominador**: não se mede recuperação de algo que não está indexado.
- **Geração** — LLM-as-judge com rubrica 0–2. É o custo dominante; use
  `--sample N` no desenvolvimento.
