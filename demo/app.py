"""Demo local do ISP-RAG.

NÃO é a interface de consulta do produto: a spec §8 fixa UI em TypeScript na
fase v3, e o CLAUDE.md proíbe frontend nesta fase. Isto existe para mostrar o
sistema funcionando — sobretudo o que só aparece bem numa tela: a fonte citada,
a recusa honesta e a ressalva de comparabilidade.

    streamlit run demo/app.py
"""

import logging
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

for ruidoso in ("llama_index", "httpx", "openai", "isp_rag"):
    logging.getLogger(ruidoso).setLevel(logging.ERROR)

st.set_page_config(page_title="ISP-RAG", page_icon="📊", layout="wide")

EXEMPLOS = {
    "— escolha um exemplo —": "",
    "Fato numérico (Ledger)": "Quantos entes tiveram conceito A no ISP de 2025?",
    "Ente específico (Ledger)": "Qual o conceito do RPPS de Campinas em 2025?",
    "Exigência normativa (Memory)": "Quais os requisitos para emissão do CRP?",
    "Citação de artigo (lookup exato)": "O que estabelece o art. 241 da Portaria MTP 1.467/2022?",
    "Grafo (Brain)": "Quais indicadores compõem a dimensão atuária?",
    "Premissa falsa (deve corrigir)": "Quantos entes receberam conceito E no ISP 2025?",
    "Fora do escopo (deve recusar)": "Qual a capital da Mongólia?",
    "Cruza domínios (§3.4)": (
        "O RPPS de Recife caiu de conceito entre 2024 e 2025? Foi o desempenho "
        "dele que piorou ou a metodologia que mudou? E qual norma alterou isso?"
    ),
}


@st.cache_resource(show_spinner="Subindo as engines…")
def get_client():
    from fastapi.testclient import TestClient

    from isp_rag.api.main import app

    client = TestClient(app)
    client.__enter__()  # dispara o lifespan
    return client


@st.cache_data(ttl=60)
def status():
    c = get_client()
    saude = c.get("/health").json()
    fontes = {}
    for engine in ("ledger", "memory", "brain"):
        try:
            fontes[engine] = c.get(f"/sources/{engine}").json()
        except Exception:
            fontes[engine] = {}
    return saude, fontes


st.title("ISP-RAG")
st.caption(
    "RAG multi-fonte sobre a previdência pública brasileira — "
    "Ledger (PostgreSQL) · Memory (Qdrant) · Brain (Neo4j)"
)

# ---------------------------------------------------------------------------
# Barra lateral: o que o sistema tem, e portanto o que pode responder
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Estado do sistema")
    try:
        saude, fontes = status()
        for servico, estado in saude["services"].items():
            icone = {"ok": "🟢", "disabled": "⚪"}.get(estado, "🔴")
            st.write(f"{icone} {servico}: `{estado}`")

        st.divider()
        ledger = fontes.get("ledger", {})
        if ledger.get("edicoes"):
            e = ledger["edicoes"][0]
            st.metric("Entes no Ledger", f"{e['n_entes']:,}".replace(",", "."))
            st.caption(f"edição {e['ano']} · regime `{e['regime']}`")
        memory = fontes.get("memory", {})
        if memory.get("total_chunks"):
            st.metric("Chunks no Memory", memory["total_chunks"])
            sit = memory.get("situacao", {})
            st.caption(
                f"{sit.get('vigente', 0)} vigentes · {sit.get('alterado', 0)} alterados · "
                f"{sit.get('revogado', 0)} revogados"
            )
        brain = fontes.get("brain", {})
        if brain.get("status") == "ok":
            st.metric("Nós no Brain", sum(brain.get("nos", {}).values()))

        st.divider()
        st.subheader("O corpus cobre?")
        termo = st.text_input(
            "termo", placeholder="DIPR, CRP, segurado…", label_visibility="collapsed"
        )
        if termo:
            c = get_client().get("/cobertura", params={"termo": termo}).json()
            if not c["coberto"]:
                st.error(f"**{termo}** não está no corpus — a recusa seria correta")
            elif c["n_chunks"] <= 2:
                st.warning(f"**{termo}**: só {c['n_chunks']} chunk(s) — cobertura rasa")
            else:
                st.success(f"**{termo}**: {c['n_chunks']} chunks")
                st.caption("arts. " + ", ".join(c["artigos"][:8]))
    except Exception as exc:
        st.error(f"serviços indisponíveis: {exc}")
        st.caption("`docker compose up -d`")

# ---------------------------------------------------------------------------
# Pergunta
# ---------------------------------------------------------------------------
escolha = st.selectbox("Exemplos", list(EXEMPLOS), label_visibility="collapsed")
pergunta = st.text_area(
    "Pergunta",
    value=EXEMPLOS[escolha],
    height=90,
    placeholder="Pergunte sobre notas do ISP, exigências normativas ou o que mudou entre edições…",
)

col_enviar, col_data = st.columns([1, 3])
with col_enviar:
    enviar = st.button("Perguntar", type="primary", use_container_width=True)
with col_data:
    usar_data = st.checkbox("Filtrar por data de vigência")
    data_ref = st.date_input("data", label_visibility="collapsed") if usar_data else None

if enviar and pergunta.strip():
    corpo = {"question": pergunta.strip()}
    if data_ref:
        corpo["reference_date"] = str(data_ref)

    inicio = time.perf_counter()
    with st.spinner("Consultando…"):
        r = get_client().post("/query", json=corpo)
    latencia = time.perf_counter() - inicio

    if r.status_code != 200:
        st.error(f"HTTP {r.status_code}")
        st.json(r.json())
        st.stop()

    d = r.json()

    # A recusa é resultado válido, não erro — é o que a spec §6.3 chama de
    # métrica de sucesso. A tela precisa mostrar isso como tal.
    if d["refused"]:
        st.warning("**Recusa** — o sistema não encontrou base para responder")
        st.write(d["answer"])
        st.caption(
            "Recusar é comportamento correto quando o corpus não cobre o assunto. "
            "Use a checagem de cobertura na barra lateral para confirmar."
        )
    else:
        st.success(d["answer"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Engines", " + ".join(d["engines_used"]))
    m2.metric("Fontes", len(d["sources"]))
    m3.metric("Sub-perguntas", len(d["sub_questions"]))
    m4.metric("Latência", f"{latencia:.1f}s")

    if d["sub_questions"]:
        with st.expander(f"Decomposição em {len(d['sub_questions'])} sub-perguntas"):
            for s in d["sub_questions"]:
                st.write(f"- {s}")

    if d["sources"]:
        st.subheader("Fontes")
        st.caption("Toda afirmação rastreia até uma destas (R2)")
        for i, fonte in enumerate(d["sources"], start=1):
            with st.expander(f"{i}. {fonte['ref']}  ·  `{fonte['engine']}`"):
                if fonte.get("snippet"):
                    st.text(fonte["snippet"])
                if fonte.get("url"):
                    st.link_button("Ver na fonte oficial", fonte["url"])
    elif not d["refused"]:
        st.error("Resposta sem fonte — isso viola R2 e não deveria acontecer")

    with st.expander("Resposta completa (JSON)"):
        st.json(d)

st.divider()
st.caption(
    "Demo local. A interface de consulta do produto é TypeScript na fase v3 "
    "(spec §8) — isto existe para demonstrar o sistema, não para substituí-la."
)
