# ISP-RAG

RAG multi-fonte sobre a previdência pública brasileira — **Ledger** (PostgreSQL) + **Memory** (Qdrant) + **Brain** (Neo4j), com avaliação medida e dados 100% públicos.

O sistema ingere os resultados públicos do **Índice de Situação Previdenciária (ISP-RPPS)**, publicados anualmente pelo Ministério da Previdência Social, junto com os relatórios técnicos, notas metodológicas e portarias que os regulamentam. Expõe tudo através de uma API validada por contratos rígidos e consumível por agentes via MCP.

## A ideia

A fonte do contexto é ditada pela natureza da pergunta, não pela limitação da ferramenta:

| Pergunta | Natureza | Camada |
|---|---|---|
| "Qual a nota do RPPS de tal município" | consulta relacional | **Ledger** — Text-to-SQL sobre PostgreSQL |
| "O que a norma exige" | busca semântica | **Memory** — similaridade vetorial no Qdrant |
| "O que mudou entre edições e por quê" | travessia de grafo | **Brain** — grafo no Neo4j |

Um sistema que só tem vetores responde mal a duas dessas três.

## Por que este domínio

- **Dado real, público e auditável.** Nenhum gerador sintético. Todo número tem URL de origem, data de coleta e hash de verificação.
- **Série temporal genuína.** Nove edições do ISP, de 2017 a 2025, para o mesmo conjunto de entes.
- **Metodologia versionada.** O índice mudou ao longo das edições — o que cria perguntas que exigem as três camadas simultaneamente.

## Stack

LlamaIndex (orquestração) · Pydantic (contratos) · FastAPI (serving) · PostgreSQL · Qdrant · Neo4j · Docker Compose · MCP Server

## Fases de entrega

| Fase | Capacidade nova |
|---|---|
| **v0** | Fato numérico e exigência normativa, com fonte citada e desempenho medido |
| **v1** | Comparação entre edições; o que a norma exige, não apenas o resultado |
| **v1.5** | Contexto fiscal do ente via SICONFI; dado vivo de fonte externa |
| **v2** | A pergunta de demonstração — cruzando as três camadas |
| **v3** | Consumo por agentes (MCP) e por usuário final |

## Regra de procedência

Todo arquivo entra no sistema por download automatizado a partir da URL pública de origem. Nenhum arquivo entra por cópia manual. Cada item registra em manifesto: URL, data e hora da coleta, tamanho e hash SHA-256.

## Documentação

📄 **[Especificação completa do projeto](docs/projeto-isp-rag.md)** — arquitetura, ingestão, chunking, ontologia, camada de avaliação, fases, riscos e custos.

## Demo local (Streamlit)

```bash
docker compose up -d
streamlit run demo/app.py
```

Tela para experimentar o sistema: mostra a resposta com as fontes citadas, qual
engine foi acionada, a recusa quando não há base, e uma checagem de cobertura do
corpus na barra lateral.

É **demonstração, não a interface do produto** — a spec §8 fixa UI em TypeScript
na fase v3. O Streamlit existe porque boa parte do que o sistema faz de
interessante (fonte citada, recusa honesta, ressalva de comparabilidade) só
aparece bem numa tela.

## Uso como ferramenta de agente (MCP)

O sistema se expõe como servidor MCP, com cinco tools. Registre no seu cliente:

```json
{
  "mcpServers": {
    "isp-rag": {
      "command": "python",
      "args": ["-m", "isp_rag.mcp.server"],
      "cwd": "/caminho/absoluto/para/rag-previdenciario",
      "env": { "PYTHONPATH": "src" }
    }
  }
}
```

Use o caminho **absoluto** do projeto em `cwd`. Antes de registrar, o `.env`
precisa estar preenchido e os serviços do Compose no ar (`docker compose up -d`).

| Tool | Para quê |
|---|---|
| `consultar_isp` | Pergunta aberta, cruzando as três camadas. Recusa quando não há base. |
| `nota_do_ente` | Conceito de um RPPS e a memória de cálculo, por CNPJ ou município. |
| `buscar_norma` | Dispositivos do corpus normativo, só vigentes por padrão. |
| `listar_edicoes` | O que está carregado, com o regime metodológico de cada edição. |
| `verificar_cobertura` | Se um assunto está no corpus — distingue recusa legítima de lacuna. |

Toda tool retorna as fontes citadas: um agente que recebe afirmação sem fonte
propaga o problema com menos supervisão que um usuário lendo a resposta.
