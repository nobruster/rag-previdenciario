# T03 — Coleta com manifesto de procedência

**Depende de:** T01 · **Paralelo com:** T02 · **Saída:** ingestão auditável, sem cópia manual

## Contexto

Esta é a task mais sensível do projeto. É ela que garante que o repositório pode
ser público: um único número de origem interna contamina tudo. A spec §2.4 chama
a regra de procedência de "inegociável" — o código aqui é o que a torna
verificável, em vez de declarada no README.

Segundo efeito, menos óbvio: com a memória de cálculo no banco e a procedência
registrada, o sistema pode **recalcular** o indicador e comparar com o publicado.
Isso vira material de análise em T04.

---

## PROMPT

````
Você vai implementar a camada de coleta do ISP-RAG. Ela tem uma regra que não
admite exceção.

## R1 — Regra de procedência (inegociável)

Todo arquivo entra no sistema por download automatizado a partir da URL pública
de origem. NENHUM arquivo entra por cópia manual.

Cada item ingerido registra em manifesto: URL de origem, data e hora da coleta,
tamanho e hash SHA-256.

Consequência de projeto: não escreva NENHUMA função que aceite um caminho de
arquivo local como porta de entrada de dado. A única porta é fetch(url). Se uma
task futura precisar de um arquivo, ela chama fetch() — não copia.

## Entregáveis

### 1. src/isp_rag/ingestion/manifest.py

  class ManifestEntry(BaseModel):
      url: str
      filename: str
      fetched_at: datetime      # UTC, timezone-aware
      size_bytes: int
      sha256: str               # 64 hex chars
      content_type: str | None = None

  class Manifest:
      """Registro append-only em data/raw/manifest.json."""
      def __init__(self, path: Path): ...
      def load(self) -> list[ManifestEntry]: ...
      def append(self, entry: ManifestEntry) -> None: ...
      def has_sha(self, sha256: str) -> ManifestEntry | None: ...
      def by_url(self, url: str) -> ManifestEntry | None: ...

  Serialização: JSON indentado, ordenado por fetched_at, UTF-8 sem escapes
  (ensure_ascii=False — nomes de arquivo têm acento).

  O manifesto É VERSIONADO no git (o .gitignore já abre exceção para ele).
  Os arquivos baixados NÃO são. Isso é deliberado: o manifesto é a prova de
  procedência; os binários são reconstituíveis a partir dele.

### 2. src/isp_rag/ingestion/fetcher.py

  def fetch(url: str, dest_dir: Path, *, force: bool = False) -> ManifestEntry:
      """
      Baixa via httpx com stream, calculando SHA-256 durante o download
      (não carregue o arquivo inteiro em memória — planilhas do ISP passam
      de 50 MB).

      - timeout=60s, follow_redirects=True
      - 3 tentativas com backoff exponencial (1s, 2s, 4s) em erro de rede ou 5xx
      - 4xx falha imediatamente, sem retry
      - nome do arquivo: do header Content-Disposition se houver, senão do path
        da URL; sanitize contra path traversal
      - IDEMPOTÊNCIA: se o sha256 resultante já existe no manifesto e force=False,
        descarta o download e retorna a entrada existente
      - grava primeiro em .tmp e faz rename atômico ao final — um download
        interrompido não pode deixar arquivo parcial parecendo íntegro
      """

  def fetch_all(urls: list[str], dest_dir: Path) -> list[ManifestEntry]:
      """Sequencial. Loga cada item. Um erro não aborta os demais —
      acumula e relata ao final."""

### 3. src/isp_rag/ingestion/sources.py

  Constantes com as URLs públicas.

  ISP_BASE = "https://www.gov.br/previdencia/..."   # TODO

  ISP_SOURCES: dict[int, list[str]] = {
      2025: [...],   # TODO: planilha individualizada, consolidada, relatório
      2024: [...],
      # ... 2017
  }

  LEGISLACAO_SOURCES: list[str] = [
      # TODO: Portaria MTP 1.467/2022, Leis 9.717/1998 e 10.887/2004,
      #       ECs 20/1998, 41/2003, 47/2005, 103/2019
  ]

  ⚠️ NÃO INVENTE URLs. Deixe os TODO explícitos e uma docstring dizendo onde
  encontrá-las (página de Divulgação de Resultados do ISP em gov.br/previdencia).
  Uma URL fabricada viola R1 na primeira execução e é pior que um TODO honesto.

  Adicione uma função validate_sources() que verifica se ainda há TODO pendente
  e falha com mensagem clara, para o CLI não rodar com lista vazia em silêncio.

### 4. CLI

  python -m isp_rag.ingestion.fetch_isp --year 2025
  python -m isp_rag.ingestion.fetch_isp --all
  python -m isp_rag.ingestion.fetch_legislacao

  Saída: tabela com filename, tamanho, sha256 (12 primeiros chars), status
  (baixado | já existia). Ao final, o caminho do manifesto.

### 5. tests/test_manifest.py e tests/test_fetcher.py

Com httpx mockado (respx ou monkeypatch — não faça rede em teste):

  - sha256 calculado bate com o do conteúdo conhecido
  - segunda chamada com mesmo conteúdo → status "já existia", não rebaixa
  - manifesto persiste e recarrega sem perder campos
  - fetched_at é timezone-aware em UTC
  - erro 500 → 3 tentativas e depois exceção
  - erro 404 → falha imediata, sem retry
  - download interrompido não deixa arquivo final (só .tmp, que é limpo)
  - filename com "../" na URL é sanitizado

## Validação

  pytest tests/test_manifest.py tests/test_fetcher.py -v
  cat data/raw/manifest.json    # após preencher as URLs e rodar o CLI
````

---

## Validação

```bash
pytest tests/test_manifest.py tests/test_fetcher.py -v
python -m isp_rag.ingestion.fetch_isp --year 2025   # requer URLs preenchidas
```

## Aceite

- [ ] Nenhuma função aceita arquivo local como entrada de dado (R1)
- [ ] SHA-256 calculado em streaming, não com o arquivo em memória
- [ ] Segunda execução não rebaixa o que já tem o mesmo hash
- [ ] `data/raw/manifest.json` versionado; os arquivos baixados, não
- [ ] `sources.py` tem TODOs honestos, **nenhuma URL inventada**
- [ ] Download interrompido não deixa arquivo parcial válido

> **Nota:** as URLs reais precisam ser preenchidas por você a partir da página do
> ISP em gov.br/previdencia. O agente não deve inventá-las — é exatamente o tipo
> de fabricação que R1 existe para impedir.
