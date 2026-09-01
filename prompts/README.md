# prompts/ — execução task a task

Um arquivo por task. Cada um é **autocontido**: copie o bloco `PROMPT` inteiro
para o agente e ele tem tudo que precisa, sem abrir `plan.md` junto.

## Ordem

```
T00 ── T01 ─┬─ T02 ── T03 ─┬─ T04 ── T05 ─┬─ T08 ── T09 ── T10 ─┬─ T12 ── T13
            │              │              │                     │
            └─ (setup)     └─ T06 ── T07 ─┘                     └─ T11
```

T00 é a task zero: cria o `CLAUDE.md` que todas as outras assumem lido.

| # | Task | Depende | Paralelo com |
|---|---|---|---|
| [T00](T00-build-claude-memory.md) | Memória do projeto (`CLAUDE.md`) | — | — |
| [T01](T01-scaffold.md) | Scaffold + Docker Compose | T00 | — |
| [T02](T02-contratos.md) | Contratos Pydantic + provider LLM | T01 | T03 |
| [T03](T03-coleta.md) | Coleta com manifesto (R1) | T01 | T02 |
| [T04](T04-ledger-schema.md) | Ledger: schema e carga | T03 | T06 |
| [T05](T05-ledger-sql.md) | Ledger: Text-to-SQL | T04 | — |
| [T06](T06-memory-chunking.md) | Memory: chunk por artigo | T03 | T04 |
| [T07](T07-memory-hibrido.md) | Memory: índice híbrido | T06 | — |
| [T08](T08-roteador.md) | Roteador | T05, T07 | — |
| [T09](T09-sintese.md) | Síntese + recusa | T08 | — |
| [T10](T10-api.md) | FastAPI `/query` | T09 | — |
| [T11](T11-avaliacao.md) | Gold set + métricas | T10 | T12 |
| [T12](T12-brain.md) | Brain: ontologia | T10 | T11 |
| [T13](T13-mcp.md) | MCP Server | T10 | — |

## Como usar

Cada arquivo tem quatro partes:

- **Contexto** — o que já existe quando esta task começa
- **PROMPT** — o bloco a copiar (é só isso que vai para o agente)
- **Validação** — comandos que devem passar ao fim
- **Aceite** — checklist objetivo antes de seguir

Ao terminar uma task, rode a validação antes de abrir a próxima. Uma task que
"parece pronta" mas não passa na validação quebra todas as seguintes.

## Regras invariantes (R1–R7)

Repetidas em cada prompt onde se aplicam, mas valem sempre:

| # | Regra |
|---|---|
| R1 | Todo arquivo entra por download automatizado de URL pública, com manifesto (URL, timestamp, tamanho, SHA-256). Nenhuma cópia manual. |
| R2 | `QueryResponse.sources` vazio é erro de contrato — exceto em recusa explícita. |
| R3 | Sem base no contexto, o sistema recusa. Nunca preenche lacuna. |
| R4 | Sem dado sintético. Nada de Faker. |
| R5 | `import openai` só em `src/isp_rag/llm/provider.py`. |
| R6 | `edicao_ano` em toda tabela de fato. |
| R7 | Segredos só em `.env`, nunca commitado. |
