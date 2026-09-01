1 - Verifique o arquivo @docs/projeto-isp-rag.md e me forneça uma breve informação sobre ele.

Onde os prompts gerados devem ficar e em qual formato?
Par tasks.md + plan.md

Seguir o padrão de desenvolvimento agêntico do próprio workshop (Seção 5.2): um plan.md para arquitetura/regras e tasks.md com prompts sequenciais

Quão prescritivo cada prompt deve ser?

Alto nível de detalhe (com trechos de código)

Incluir estruturas de arquivos esperadas, nomes das principais classes, blocos de código de exemplo, variáveis de ambiente, portas — mais próximo de um runbook (guia de execução)

Os prompts devem assumir um provedor de LLM e modelo de embeddings específicos?

OpenAI tanto para o LLM quanto para embeddings

GPT-4o-mini/4o + text-embedding-3-small — provedor único, configuração mais simples

Os prompts devem incluir o deploy no Railway + Grande Final com MCP (Seção 7.3)?

Apenas Docker local

Parar no FastAPI + MCP funcionando localmente; ignorar o deploy no Railway (pode ser adicionado depois)


Você pode gerar o prompt para cada etapa para construir isso completamente?