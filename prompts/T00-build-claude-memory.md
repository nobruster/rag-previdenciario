# T00 — Construir a memória do projeto (CLAUDE.md)

**Depende de:** nada · **Antecede:** T01 · **Saída:** `CLAUDE.md` na raiz

## Contexto

Task zero. Antes de escrever qualquer linha de código, o agente precisa de um
contrato: o que este projeto é, quais regras não se quebram, o que é proibido.

O repositório já tem a especificação ([docs/projeto-isp-rag.md](../docs/projeto-isp-rag.md)),
a arquitetura ([plan.md](../plan.md)) e as 13 tasks ([prompts/](.)). Falta o
arquivo que o agente lê **primeiro**, em toda sessão, e que resume o essencial
sem duplicar o que já está nos outros.

Duplicar é o risco central desta task: duas fontes dizendo a mesma coisa
divergem na primeira alteração. `CLAUDE.md` aponta, não repete.

---

## PROMPT

````
Você vai criar o CLAUDE.md do projeto ISP-RAG: o contrato autoritativo que todo
agente lê antes de trabalhar neste repositório.

## Leia antes de escrever

1. docs/projeto-isp-rag.md — especificação completa (12 seções)
2. plan.md — arquitetura, regras invariantes R1–R7, schema, contratos
3. tasks.md e prompts/ — as 13 tasks de execução

## Princípio que governa esta task

CLAUDE.md APONTA, não repete.

Não copie para dentro dele: a árvore de diretórios (está em plan.md §3), o DDL
do Ledger (§7), a ontologia (§8), as assinaturas Pydantic (§6), a lista de
portas (§4) ou o conteúdo do .env (§5). Referencie.

Motivo: duas fontes dizendo a mesma coisa divergem na primeira alteração, e o
agente passa a seguir a errada. O CLAUDE.md é curto de propósito — mire em
80–100 linhas. Se passar de 120, você está duplicando algo.

O que ele PRECISA carregar por si só é o que muda o comportamento do agente
já na primeira leitura: o que é o projeto, as regras que não se quebram, e o
que é proibido.

## Estrutura

### Cabeçalho
Uma linha dizendo que é o contrato do projeto, e os links para plan.md,
prompts/ e docs/projeto-isp-rag.md, deixando claro que este arquivo não os
repete.

### O que é
Parágrafo curto: RAG multi-fonte sobre a previdência pública brasileira, que
ingere os resultados públicos do ISP-RPPS mais as portarias e notas técnicas
que os regulamentam.

Depois, a tabela das três camadas — é a tese do projeto e o que orienta toda
decisão de roteamento:

  | Camada | Tech | Responde |
  | Ledger | PostgreSQL + Text-to-SQL | "qual a nota do RPPS de X em 2025" |
  | Memory | Qdrant, denso + esparso  | "o que a norma exige" |
  | Brain  | Neo4j                     | "o que mudou entre edições e por quê" |

Feche dizendo: serving em FastAPI, consumo por agentes via MCP.

### Regras invariantes
As sete regras de plan.md §1, em tabela, na forma operacional (uma linha cada,
sem a justificativa — ela fica no plan.md, linkado).

  R1 download de URL pública com manifesto (URL, timestamp, tamanho, SHA-256);
     nenhuma cópia manual
  R2 QueryResponse.sources vazio é erro de contrato, exceto em recusa
  R3 sem base no contexto, recusa; nunca preenche lacuna
  R4 sem dado sintético; nada de Faker
  R5 import openai só em src/isp_rag/llm/provider.py
  R6 edicao_ano em toda tabela de fato
  R7 segredos só em .env; o repositório é público

Acima da tabela, a instrução que faz a regra valer na prática:
"Se uma task parecer exigir a quebra de uma delas, A TASK ESTÁ ERRADA — pare e
reformule." Sem isso o agente contorna a regra para fazer a task passar.

### Padrões
Só o que não é óbvio nem está em outro arquivo:
- Python 3.11+, layout src/, pyproject.toml (nunca requirements.txt)
- type hints obrigatórios; docstring em função e classe pública
- ruff, line-length 100
- temperature=0 em toda chamada de LLM — este sistema não é criativo
- toda saída de LLM passa por modelo Pydantic; nunca string crua
- Text-to-SQL e text-to-Cypher são SOMENTE LEITURA, com guarda explícita
- domínio em português (ente, edicao, nota_final, criterio), infra em inglês —
  são termos da fonte oficial; traduzir cria ambiguidade ao citar a norma

### Testes
- pytest; mock de serviços externos, nunca rede em teste
- Text-to-SQL: asserte sobre o RESULTADO da execução, nunca sobre a string do
  SQL — dois SQLs diferentes podem estar ambos corretos
- tests/test_r5_boundary.py varre src/ e falha se R5 for violada
- avaliação é outra coisa: gold set e métricas vivem em eval/ e medem qualidade
  (roteamento, recuperação, geração), não corretude de código

### Fluxo
- uma task por vez, do arquivo correspondente em prompts/
- ao concluir: rode a Validação e confira o Aceite daquele arquivo
- NÃO avance sem confirmação explícita
- relate desvios do prompt e o motivo

### Proibido
A seção mais útil do arquivo — dizer o que não fazer economiza mais correção
do que dizer o que fazer. Cada item com o motivo em meia linha:

- LangChain (é LlamaIndex), ChromaDB ou FAISS (é Qdrant)
- chunking por N tokens sobre texto normativo — quebra a âncora citável;
  é chunk por artigo (spec §5.2)
- nome de modelo hardcoded — vem do .env
- URL de fonte inventada — sem a URL real, deixe TODO explícito
- MongoDB e data lake S3/MinIO — cortados deliberadamente (spec §4.2)
- frontend nesta fase; API e MCP são a interface

### Escopo
Uma linha do que está dentro (Docker local até FastAPI + MCP, T01–T13) e do que
está fora, com a fase: SICONFI (v1.5), cadeia normativa completa no grafo (v2+),
UI TypeScript (v3), deploy gerenciado (fora).

## Restrições de escrita

- Português. É a língua do domínio e dos documentos do projeto.
- Sem emoji, sem "🚀", sem linguagem de marketing.
- Nada de inventar regra que não esteja na spec ou no plan.md. Se achar que
  falta uma, proponha na conversa — não a escreva no contrato por conta própria.
- Não invente versão de biblioteca que não esteja em plan.md §2.

## Validação

Depois de escrever, verifique você mesmo:
- o arquivo tem entre 80 e 120 linhas
- as 7 regras estão lá, com a instrução de parar em caso de conflito
- NENHUM trecho é cópia de plan.md (árvore, DDL, ontologia, portas, .env)
- todo link relativo resolve: plan.md, tasks.md, prompts/, docs/projeto-isp-rag.md
- a proibição de chunking por tokens está explícita
- nenhuma regra inventada além das que estão na spec e no plan.md
````

---

## Validação

```bash
wc -l CLAUDE.md          # esperado: 80–120
grep -c '^| \*\*R[1-7]\*\*' CLAUDE.md   # esperado: 7
grep -n 'chunking por N tokens' CLAUDE.md
# links relativos resolvem?
for f in plan.md tasks.md prompts docs/projeto-isp-rag.md; do
  test -e "$f" && echo "ok $f" || echo "QUEBRADO $f"
done
```

## Aceite

- [ ] 80–120 linhas — se passar disso, está duplicando `plan.md`
- [ ] As 7 regras presentes, com "a task está errada" em caso de conflito
- [ ] Nenhuma cópia de árvore de diretórios, DDL, ontologia, portas ou `.env`
- [ ] Tabela das três camadas com o tipo de pergunta que cada uma responde
- [ ] Seção **Proibido** com o motivo de cada item
- [ ] Chunking por tokens proibido explicitamente
- [ ] Todos os links relativos resolvem
- [ ] Nenhuma regra inventada além da spec e do `plan.md`

---

> **Nota.** O `CLAUDE.md` deste repositório já existe, escrito à mão. Este prompt
> é o que o reproduz — útil para regenerá-lo quando `plan.md` ou a spec mudarem,
> e para auditar se ele saiu do lugar. Rodando T00 sobre o arquivo atual, o
> resultado deve ser equivalente; divergência é sinal de que um dos dois
> precisa de atualização.
