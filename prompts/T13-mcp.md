# T13 — MCP Server

**Depende de:** T10 (idealmente também T12) · **Saída:** escopo local completo

## Contexto

Última task. O sistema responde por HTTP; esta task o expõe como **ferramenta
de agente** via MCP — a camada de consumo da spec §3.2.

Diferença que importa no design das tools: um agente não lê documentação, lê a
descrição da tool e decide sozinho. Descrição ruim = tool nunca usada, ou usada
errada.

---

## PROMPT

````
Você vai expor o ISP-RAG como servidor MCP, para consumo por agentes.

## Regras aplicáveis

R2 — Toda tool retorna as fontes citadas. Vale no MCP igual à API: um agente que
     recebe afirmação sem fonte propaga o problema adiante, com menos supervisão
     humana que um usuário lendo a resposta.

## Entregáveis

### 1. src/isp_rag/mcp/server.py

Servidor MCP sobre stdio, com 4 tools.

  TOOL 1: consultar_isp
    Descrição para o agente:
      "Responde perguntas sobre a previdência pública brasileira (RPPS)
       cruzando três fontes: notas do Índice de Situação Previdenciária (ISP)
       por ente e edição, o texto das normas que regulamentam os RPPS
       (Portaria MTP 1.467/2022, Leis 9.717/1998 e 10.887/2004, Emendas
       Constitucionais), e o grafo de relações entre edições, critérios e
       indicadores.
       Use para qualquer pergunta sobre RPPS, notas do ISP, exigências
       normativas ou evolução entre edições. Toda resposta cita as fontes.
       Se não houver base na documentação indexada, a ferramenta recusa
       explicitamente em vez de inventar."
    Args: pergunta (str), data_referencia (str ISO, opcional)
    Retorno: QueryResponse serializada (answer, sources, engines_used,
             sub_questions, refused)

  TOOL 2: nota_do_ente
    Descrição:
      "Consulta direta da nota e do conceito (A a E) de um RPPS específico no
       ISP, por CNPJ ou nome do município, em uma edição. Mais rápido e preciso
       que consultar_isp quando você já sabe exatamente qual ente e qual ano
       quer. Retorna também a memória de cálculo por componente."
    Args: identificador (str — CNPJ ou nome), ano (int)
    Retorno: nota, conceito, componentes, e a fonte (tabela + edição)
    Se o nome casar com vários entes, retorne a lista de candidatos em vez de
    escolher um — desambiguação é do agente.

  TOOL 3: buscar_norma
    Descrição:
      "Busca no corpus normativo dos RPPS. Retorna os dispositivos (artigos)
       mais relevantes, com hierarquia, situação de vigência e URL da fonte.
       Por padrão retorna apenas dispositivos VIGENTES. Se a busca citar um
       artigo específico (ex.: 'art. 241'), faz busca exata."
    Args: termo (str), data_referencia (opcional), incluir_revogados (bool=False)
    Retorno: lista de dispositivos com norma, artigo, texto, situação, url

  TOOL 4: listar_edicoes
    Descrição:
      "Lista as edições do ISP disponíveis no sistema, com o número de entes
       em cada uma. Use antes de perguntar sobre um ano específico, para saber
       o que está indexado."
    Args: nenhum
    Retorno: lista de {ano, n_entes, url_fonte}

### 2. Fontes em toda tool (R2)

Nenhuma tool retorna afirmação sem fonte. Em nota_do_ente e listar_edicoes, a
fonte é a tabela + edição + url_fonte do manifesto. Em buscar_norma, é a
norma + artigo + url.

### 3. Erros

Erro vira retorno estruturado, não exceção que derruba o servidor:
  {"error": "ente_nao_encontrado", "detail": "...", "sugestoes": [...]}

Um agente lida melhor com erro descritivo do que com stack trace.

### 4. Reúso, não reimplementação

As tools chamam as MESMAS funções da API (T10). Não reimplemente o fluxo de
query — importe de isp_rag.query e isp_rag.ledger. Divergência entre o que a
API responde e o que o MCP responde seria um bug difícil de perceber.

Construa as engines uma vez, no startup do servidor.

### 5. Documentação no README.md

Adicione seção "Uso como ferramenta de agente (MCP)" com o bloco de configuração,
usando caminho ABSOLUTO do projeto:

  {
    "mcpServers": {
      "isp-rag": {
        "command": "python",
        "args": ["-m", "isp_rag.mcp.server"],
        "cwd": "/caminho/absoluto/para/rag-previdenciario",
        "env": {"PYTHONPATH": "src"}
      }
    }
  }

Explique que o .env precisa estar preenchido e os serviços do compose no ar.

### 6. tests/test_mcp.py

Invoca cada tool via cliente MCP em processo:
  - listar_edicoes → lista não-vazia, com os anos carregados
  - nota_do_ente com CNPJ válido → nota, conceito e fonte
  - nota_do_ente com nome ambíguo → lista de candidatos, não escolha arbitrária
  - nota_do_ente com ente inexistente → erro estruturado, servidor não cai
  - buscar_norma "art. 241" → busca exata, art. 241 em primeiro
  - buscar_norma padrão → nenhum dispositivo revogado
  - consultar_isp pergunta fora do escopo → refused=true, com a frase de recusa
  - TODA tool retorna campo de fontes não-vazio (exceto em recusa) — teste
    isso como asserção genérica sobre as 4 tools

## Validação

  python -m isp_rag.mcp.server    # deve ficar aguardando em stdio
  pytest tests/test_mcp.py -v

Ao fim desta task o escopo local está COMPLETO: ingestão com procedência,
três camadas cognitivas, API validada por contratos, avaliação medida e
consumo por agentes. O que fica de fora é deploy gerenciado, SICONFI (v1.5) e
a UI em TypeScript (v3).
````

---

## Validação

```bash
pytest tests/test_mcp.py -v
python -m isp_rag.mcp.server   # aguarda em stdio
```

## Aceite

- [ ] 4 tools com descrições escritas **para um agente decidir sozinho**
- [ ] Toda tool retorna fontes (R2), inclusive as de acesso direto
- [ ] Nome ambíguo devolve candidatos, não escolha arbitrária
- [ ] Erro estruturado, servidor não cai
- [ ] Tools reusam o código da API, sem reimplementar o fluxo
- [ ] README com bloco de configuração MCP e caminho absoluto
- [ ] **Escopo local completo**

---

## Depois desta task

Fora do escopo, registrado para não virar escopo por acidente:

| Item | Fase |
|---|---|
| SICONFI via API (tabela já existe em plan.md §7) | v1.5 |
| Cadeia normativa e linhagem no grafo (stubs em T12) | v2+ |
| Interface de consulta em TypeScript | v3 |
| Deploy gerenciado | fora |
