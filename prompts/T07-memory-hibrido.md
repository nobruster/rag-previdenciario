# T07 — Memory: índice híbrido no Qdrant

**Depende de:** T06 · **Saída:** recuperação densa + esparsa, com vigência e lookup por citação

## Contexto

Os chunks por artigo estão prontos, com hierarquia prefixada e metadados de
vigência. Esta task os indexa e monta a recuperação.

A spec §5.2 pede três coisas que a busca vetorial pura não dá: fusão híbrida
(a esparsa resolve "art. 241" e "DIPR" literalmente, onde a densa erra), filtro
de vigência por padrão, e lookup exato quando a pergunta cita um dispositivo.

---

## PROMPT

````
Você vai implementar a indexação e a recuperação do Memory, sobre os
ArticleChunk produzidos pelo chunker.

## Regras aplicáveis

R5 — Embeddings via isp_rag.llm.llama_embedding(). Nenhum import de openai.

## Entregáveis

### 1. src/isp_rag/memory/indexer.py

  def ensure_collection() -> None:
      """
      Cria a coleção Qdrant `isp_normas` se não existir, com DOIS vetores:
        - denso:   size=settings.embed_dim (1536), distance=COSINE
        - esparso: sparse vector nativo do Qdrant
      """

  def index_chunks(chunks: list[ArticleChunk], *, batch_size: int = 64) -> int:
      """
      Indexa em lote. O payload leva TODOS os campos do ArticleChunk —
      são eles que permitem os filtros de vigência e o lookup por citação.

      Campos indexados como payload index (para filtro eficiente):
        norma, numero, artigo, situacao, data_inicio_vigencia,
        data_fim_vigencia, titulo, capitulo, secao

      id do ponto: hash estável de (norma, artigo, subchunk_idx) — reindexar
      não duplica.

      O texto embeddado é chunk.text (COM o prefixo de hierarquia), nunca
      text_raw. Se você embeddar text_raw, perde exatamente o ganho da T06.
      """

  CLI: python -m isp_rag.memory.index --norma portaria-1467
       python -m isp_rag.memory.index --all

### 2. src/isp_rag/memory/engine.py

  def build_memory_engine(reference_date: date | None = None) -> QueryEngine:
      """
      VectorStoreIndex sobre QdrantVectorStore com enable_hybrid=True.

      Recuperação:
        - similarity_top_k=5 (denso)
        - sparse_top_k=10
        - fusão por Reciprocal Rank Fusion
      """

### 3. Filtro de vigência (padrão, não opção)

Se reference_date vier, o retriever filtra para dispositivos vigentes NAQUELA
data:

    situacao == "vigente"
    AND (data_inicio_vigencia IS NULL OR data_inicio_vigencia <= reference_date)
    AND (data_fim_vigencia   IS NULL OR data_fim_vigencia   >= reference_date)

Sem reference_date, o padrão é situacao == "vigente" (hoje). Recuperar norma
revogada só acontece se a pergunta pedir explicitamente o histórico — exponha
isso como parâmetro include_revogados=False.

Motivo: em domínio normativo, responder com dispositivo revogado é tão ruim
quanto inventar.

### 4. Lookup por citação (pré-etapa antes do vetorial)

Se a pergunta cita um dispositivo explicitamente, a busca vira consulta EXATA
por payload — não vetorial.

  CITACAO_RE = re.compile(
      r"art(?:igo|\.)?\s*(\d+)(?:\s*[ºo°])?(?:\s*-\s*([A-Z]))?",
      re.IGNORECASE,
  )
  NORMA_RE = re.compile(
      r"(?:portaria|lei|emenda constitucional|ec)\s*(?:mtp\s*)?"
      r"n?[ºo°.]?\s*([\d.]+)(?:/(\d{4}))?",
      re.IGNORECASE,
  )

  def citation_lookup(question: str, reference_date) -> list[NodeWithScore] | None:
      """
      Se detectar citação, faz scroll/filter no Qdrant por (norma?, artigo)
      e devolve os pontos exatos. Se não detectar, devolve None e o fluxo
      segue para o retriever híbrido.
      """

  Casos a cobrir: "o que diz o art. 241?", "art. 241 da Portaria 1.467",
  "artigo 9º da Lei 9.717/1998", "EC 103/2019".

### 5. tests/test_memory_engine.py

Com a coleção populada a partir da fixture da T06:

  - "qual o prazo para enviar o demonstrativo"
      → recupera por semântica, top-5 contém o artigo de prazo
  - "art. 241"
      → aciona citation_lookup, e o art. 241 é o top-1 (não apenas presente)
  - "DIPR"
      → a esparsa resolve o termo literal; o chunk que menciona DIPR aparece
        no top-5 (teste que a fusão está funcionando, não só o denso)
  - reference_date antiga → dispositivo com data_inicio_vigencia posterior
      NÃO aparece
  - include_revogados=False (padrão) → nenhum chunk com situacao="revogado"
  - reindexar os mesmos chunks não duplica pontos na coleção

## Validação

  docker compose up -d qdrant
  python -m isp_rag.memory.index --all
  pytest tests/test_memory_engine.py -v
  curl http://localhost:6333/collections/isp_normas | jq '.result.points_count'
````

---

## Validação

```bash
python -m isp_rag.memory.index --all
pytest tests/test_memory_engine.py -v
```

## Aceite

- [ ] Coleção com vetor denso **e** esparso, `enable_hybrid=True`
- [ ] Fusão por RRF (não só denso com filtro por cima)
- [ ] Embedding sobre `chunk.text` (com prefixo), não `text_raw`
- [ ] Filtro de vigência é o **padrão**
- [ ] `"art. 241"` faz lookup exato e traz o artigo em top-1
- [ ] `"DIPR"` é resolvido pela esparsa
- [ ] Reindexação não duplica pontos
