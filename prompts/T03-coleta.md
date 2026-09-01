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

  As URLs do ISP JÁ ESTÃO LEVANTADAS E VERIFICADAS em data/raw/sources.json —
  9 edições (2017–2025), 20 arquivos, todas conferidas por requisição HTTP com
  content-type e magic bytes corretos.

  NÃO redigite as URLs no código. Carregue do JSON:

    SOURCES_FILE = Path("data/raw/sources.json")

    def load_sources() -> dict:
        """Lê data/raw/sources.json. É a fonte única das URLs — versionada
        junto do código, para a procedência ser auditável (R1)."""

    def isp_urls(ano: int) -> dict[str, str]:
        """URLs de uma edição. KeyError com os anos disponíveis se não existir."""

    def legislacao_urls() -> dict[str, str]:
        """URLs da legislação. Levanta erro claro enquanto estiverem null —
        são o TODO restante (ver abaixo)."""

  ⚠️ As URLs de LEGISLAÇÃO ainda são null no JSON. NÃO as invente. Preencher
  exige buscar em planalto.gov.br — e a spec §9 recomenda preferir HTML
  estruturado ao PDF, então avalie o HTML do Planalto antes de baixar PDF.
  Uma URL fabricada viola R1 na primeira execução e é pior que um TODO honesto.

  validate_sources() falha com mensagem clara se algo estiver null, para o CLI
  não rodar com lista vazia em silêncio.

### 3b. User-Agent obrigatório (descoberto na verificação)

  O portal gov.br responde **403 Forbidden** a User-Agent padrão de cliente HTTP.
  Verificado: com o UA do httpx todos os 20 arquivos dão 403; com UA de
  navegador, todos dão 200/206 com o content-type correto.

  Portanto o fetcher DEVE enviar, em toda requisição:

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }

  Sem isso, TODO download falha. Trate 403 como erro não-recuperável por retry
  (não adianta tentar de novo com o mesmo UA) e com mensagem apontando para esta
  causa provável.

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
- [ ] `sources.py` carrega de `data/raw/sources.json`, sem redigitar URLs
- [ ] **User-Agent de navegador em toda requisição** — sem ele, 403 em tudo
- [ ] URLs de legislação continuam `null`, **nenhuma inventada**
- [ ] Download interrompido não deixa arquivo parcial válido

> **URLs do ISP: já levantadas e verificadas** em
> [data/raw/sources.json](../data/raw/sources.json) — 9 edições (2017–2025),
> 20 arquivos, cada um conferido por requisição real (status, content-type e
> magic bytes). Falta apenas a legislação (Portaria 1.467/2022, leis e ECs),
> que continua `null` de propósito: preencher exige buscar no Planalto, e a
> spec §9 pede avaliar o HTML estruturado antes de recorrer a PDF.
