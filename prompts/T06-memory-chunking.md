# T06 — Memory: chunking por artigo

**Depende de:** T03 · **Paralelo com:** T04 · **Saída:** normas fatiadas por artigo, com hierarquia

## Contexto

A spec §5.2 é direta: esta é *"a decisão técnica que mais impacta a qualidade
final, e o ponto onde a maioria dos projetos de RAG falha"*.

O erro padrão — cortar a cada N tokens com sobreposição — destrói o sentido em
norma jurídica: separa o caput do parágrafo, desliga o inciso do artigo que o
rege, e a resposta perde a âncora citável. Não aceite esse fallback nesta task.

---

## PROMPT

````
Você vai implementar o chunking do corpus normativo do ISP-RAG. Leia esta seção
inteira antes de escrever código — a estratégia aqui não é a convencional, e a
convencional está explicitamente proibida.

## Estratégia obrigatória: um chunk por artigo

PROIBIDO: SentenceSplitter, TokenTextSplitter, chunk_size/chunk_overlap, ou
qualquer corte por contagem de tokens sobre o texto normativo.

O chunk é o ARTIGO INTEIRO: caput + seus parágrafos + incisos + alíneas, juntos.
Um artigo é a menor unidade que se pode citar e que faz sentido sozinha.

## Entregáveis

### 1. src/isp_rag/memory/chunker.py

  class ArticleChunk(BaseModel):
      text: str                  # texto INDEXADO (com hierarquia prefixada)
      text_raw: str              # texto do artigo, sem prefixo
      norma: str                 # "Portaria MTP nº 1.467/2022"
      numero: str                # "1.467"
      data_norma: date | None
      orgao: str | None          # "MTP"
      titulo: str | None         # "TÍTULO II"
      capitulo: str | None
      secao: str | None
      artigo: str                # "241"
      situacao: Literal["vigente", "revogado", "alterado"]
      data_inicio_vigencia: date | None
      data_fim_vigencia: date | None
      url: str
      ancora: str | None         # "#art241"
      is_subchunk: bool = False
      subchunk_idx: int | None = None

  def chunk_norma(texto: str, meta: NormaMeta) -> list[ArticleChunk]

### 2. Detecção de artigo

Regex tolerante às variações reais do texto legal brasileiro:

  ART_RE = re.compile(
      r"^\s*Art(?:\.|igo)?\s*(\d+)\s*([ºo°]|-[A-Z])?\s*[.\-–—]?\s*",
      re.MULTILINE | re.IGNORECASE,
  )

Precisa casar: "Art. 1º", "Art. 1o", "Art. 1°", "Artigo 1", "Art. 241.",
"Art. 5º-A", "Art 12".

Cuidado com falso positivo: "nos termos do art. 5º" NO MEIO de um parágrafo não
inicia artigo novo. Só considere início de artigo quando o match estiver no
começo da linha (^ com MULTILINE) e seguido de texto que não seja continuação.

Detecte também a hierarquia, que aparece em linhas próprias e geralmente em
caixa alta:
  TITULO_RE   = r"^\s*T[ÍI]TULO\s+([IVXLC]+|ÚNICO)"
  CAPITULO_RE = r"^\s*CAP[ÍI]TULO\s+([IVXLC]+|ÚNICO)"
  SECAO_RE    = r"^\s*Se[çc][ãa]o\s+([IVXLC]+|[ÚU]nica)"

Mantenha o estado corrente de título/capítulo/seção enquanto varre o texto, e
carimbe cada artigo com o contexto vigente naquele ponto.

### 3. O prefixo de hierarquia (não é opcional)

O campo `text` — o que vai para o embedding — DEVE começar com o caminho
hierárquico:

  "TÍTULO II > CAPÍTULO III > Seção I > Art. 241\n\n{text_raw}"

Motivo, direto da spec: resolve o artigo que diz "o prazo de que trata o caput"
sem jamais mencionar o assunto pelo nome. Sem o prefixo, esse artigo é
irrecuperável por busca semântica — o vetor não tem sinal nenhum do tema.

Guarde `text_raw` separado, para citação limpa na resposta.

### 4. Artigos longos

Artigo com mais de ~1500 tokens vira sub-chunks. Regra:
  - corte nas fronteiras de parágrafo/inciso, nunca no meio de um
  - CADA sub-chunk REPETE o caput como contexto, antes do seu trecho
  - is_subchunk=True, subchunk_idx sequencial
  - todos mantêm o mesmo `artigo` e a mesma hierarquia

### 5. Documentos técnicos

Relatórios e notas técnicas do ISP não têm artigos. Aplique a MESMA lógica por
seção numerada ("5.2 Memory — Chunking" etc.), com a hierarquia de seções
prefixada do mesmo jeito.

  def chunk_documento_tecnico(texto: str, meta) -> list[ArticleChunk]
  (situacao="vigente", artigo recebe o número da seção)

### 6. src/isp_rag/ingestion/pdf_parser.py

  def extract_text(pdf_path: Path) -> str
    - pypdf, preservando quebras de linha
    - junta hifenização de fim de linha ("previdenciá-\nria" → "previdenciária")
    - remove cabeçalho/rodapé repetido em todas as páginas (detecte por
      repetição, não por posição fixa)
    - NÃO faz OCR — se o PDF não tem camada de texto, levante exceção clara
      dizendo que precisa de OCR (spec §9 reserva OCR só para digitalizados)

  Antes de recorrer a PDF, verifique se existe versão HTML estruturada da norma
  (planalto.gov.br costuma ter) — a spec §9 recomenda avaliar isso primeiro,
  porque a qualidade da extração é muito melhor. Deixe a função preparada:
  def extract_text_from_html(html: str) -> str

### 7. tests/test_chunker.py

Fixture: tests/fixtures/portaria_trecho.txt com um trecho REAL da Portaria
1.467/2022 (copie ~3 artigos do texto oficial, incluindo um com incisos e
alíneas e um com parágrafo único).

  - nenhum chunk parte um artigo ao meio
  - todo chunk tem o prefixo hierárquico em `text`
  - text_raw NÃO tem o prefixo
  - artigo com 5 incisos permanece íntegro em 1 chunk
  - "nos termos do art. 5º" no meio de um parágrafo NÃO cria chunk novo
  - "Art. 5º-A" é reconhecido como artigo distinto de "Art. 5º"
  - artigo longo vira sub-chunks, todos repetindo o caput
  - hierarquia é herdada corretamente após uma linha "CAPÍTULO II"

## Validação

  pytest tests/test_chunker.py -v
  python -c "
  from isp_rag.memory.chunker import chunk_norma
  chunks = chunk_norma(open('tests/fixtures/portaria_trecho.txt').read(), meta)
  for c in chunks[:3]: print(c.artigo, '|', c.text[:120], '\n')
  "
````

---

## Validação

```bash
pytest tests/test_chunker.py -v
```

## Aceite

- [ ] **Nenhum** `SentenceSplitter` / `chunk_size` sobre texto normativo
- [ ] Um chunk por artigo, com parágrafos/incisos/alíneas juntos
- [ ] `text` prefixado com `TÍTULO > CAPÍTULO > Seção > Art. N`
- [ ] `text_raw` limpo, para citação
- [ ] `art. 5º` citado no meio de parágrafo não vira chunk
- [ ] `Art. 5º-A` distinguido de `Art. 5º`
- [ ] Sub-chunks repetem o caput
- [ ] PDF sem camada de texto falha com mensagem clara, sem OCR silencioso
