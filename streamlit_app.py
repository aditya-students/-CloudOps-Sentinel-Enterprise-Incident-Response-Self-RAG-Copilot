import uuid
import streamlit as st
from pathlib import Path
from src.config import get_settings
from src.self_rag import run_self_rag
from src.ingestion import ingest_file, SUPPORTED
from src.db import init_db, save_audit, latest_audits

# Initialize Page Config
st.set_page_config(
    page_title="CloudOps Sentinel · Incident Copilot",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .reportview-container {
        background-color: #0d1117;
    }
    .main-title {
        font-family: 'DM Sans', sans-serif;
        font-size: 2.2rem;
        font-weight: 700;
        color: #e6edf3;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #8b949e;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .badge-route {
        background-color: #1f6feb;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-ok {
        background-color: #238636;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-web {
        background-color: #d29922;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .source-box {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 8px 12px;
        margin-top: 6px;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize audit database
init_db()

# Session State for thread persistence and conversation history
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"incident-{uuid.uuid4()}"

if "messages" not in st.session_state:
    st.session_state.messages = []

# Top Header
col_header, col_pill = st.columns([4, 1])
with col_header:
    st.markdown('<div class="main-title">CloudOps Sentinel</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Self-RAG Incident Response & Operations Copilot with Persistent Session Memory</div>', unsafe_allow_html=True)
with col_pill:
    st.success("🟢 Self-RAG Online")
    st.caption(f"Session: `{st.session_state.thread_id[:16]}...`")

# Sidebar: Controls & Runbook Vault
with st.sidebar:
    st.header("🗄️ Runbook Vault")
    st.write("Upload runbooks, SOPs, postmortems or incident guides to the Pinecone knowledge base.")

    uploaded_file = st.file_uploader(
        "Upload document",
        type=["pdf", "txt", "md", "docx"],
        help="Supported formats: PDF, TXT, MD, DOCX"
    )

    if uploaded_file is not None:
        if st.button("📥 Add to Knowledge Base", use_container_width=True):
            uploads_dir = Path("uploads")
            uploads_dir.mkdir(exist_ok=True)
            save_path = uploads_dir / uploaded_file.name
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            with st.spinner("Chunking, embedding and upserting into Pinecone..."):
                try:
                    num_chunks = ingest_file(save_path)
                    st.success(f"✓ Indexed {num_chunks} chunks into `{get_settings().pinecone_namespace}`")
                except Exception as e:
                    st.error(f"Ingestion error: {e}")

    st.markdown("---")
    st.subheader("⚙️ Session Controls")
    if st.button("🔄 New Incident Session", use_container_width=True):
        st.session_state.thread_id = f"incident-{uuid.uuid4()}"
        st.session_state.messages = []
        st.rerun()

    st.markdown("---")
    st.subheader("📊 Recent Audit Log")
    audits = latest_audits(5)
    for a in audits:
        with st.expander(f"📌 {a['question'][:30]}..."):
            st.caption(f"Time: {a['created_at']}")
            st.caption(f"Route: {a['route']}")
            st.text(a['answer'][:120] + "...")

# Quick Starter Buttons
st.write("💡 **Quick Incident Scenarios:**")
c1, c2, c3 = st.columns(3)
selected_prompt = None
if c1.button("502 after deployment", use_container_width=True):
    selected_prompt = "Our checkout API is returning 502 errors after deployment. What should the on-call engineer check first?"
if c2.button("High CPU incident", use_container_width=True):
    selected_prompt = "CPU on the payments service is above 90%. What is our recommended response procedure?"
if c3.button("CrashLoopBackOff", use_container_width=True):
    selected_prompt = "What should I verify when a Kubernetes pod keeps restarting with CrashLoopBackOff?"

# Display Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "meta" in msg:
            meta = msg["meta"]
            badges = []
            if meta.get("route"):
                badges.append(f'<span class="badge-route">ROUTE · {meta["route"]}</span>')
            if meta.get("support_status"):
                badges.append(f'<span class="badge-ok">IsSUP · {meta["support_status"].upper()}</span>')
            if meta.get("usefulness"):
                badges.append(f'<span class="badge-ok">IsUSE · {meta["usefulness"].upper()}</span>')
            if meta.get("used_web_search"):
                badges.append('<span class="badge-web">INTERNET SEARCH USED</span>')

            st.markdown(" ".join(badges), unsafe_allow_html=True)

            if meta.get("sources"):
                with st.expander("📚 Evidence Sources", expanded=False):
                    for s in meta["sources"]:
                        url_part = f" — [Open link]({s['url']})" if s.get("url") else ""
                        st.markdown(f"- **{s.get('title') or s.get('source')}** {url_part}")

            if meta.get("trace"):
                with st.expander("🔍 Self-RAG Execution Trace", expanded=False):
                    for step in meta["trace"]:
                        st.write(f"- {step}")

# Input prompt handler
user_input = st.chat_input("Describe the incident or ask an operations question...")
prompt_to_run = selected_prompt or user_input

if prompt_to_run:
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt_to_run})
    with st.chat_message("user"):
        st.markdown(prompt_to_run)

    # Run Self-RAG
    with st.chat_message("assistant"):
        with st.spinner("Running Self-RAG (Retrieval → Verification → Generation)..."):
            try:
                result = run_self_rag(prompt_to_run, st.session_state.thread_id)
                save_audit(prompt_to_run, result)

                st.markdown(result["answer"])

                badges = []
                if result.get("route"):
                    badges.append(f'<span class="badge-route">ROUTE · {result["route"]}</span>')
                if result.get("support_status"):
                    badges.append(f'<span class="badge-ok">IsSUP · {result["support_status"].upper()}</span>')
                if result.get("usefulness"):
                    badges.append(f'<span class="badge-ok">IsUSE · {result["usefulness"].upper()}</span>')
                if result.get("used_web_search"):
                    badges.append('<span class="badge-web">INTERNET SEARCH USED</span>')

                st.markdown(" ".join(badges), unsafe_allow_html=True)

                if result.get("sources"):
                    with st.expander("📚 Evidence Sources", expanded=False):
                        for s in result["sources"]:
                            url_part = f" — [Open link]({s['url']})" if s.get("url") else ""
                            st.markdown(f"- **{s.get('title') or s.get('source')}** {url_part}")

                if result.get("trace"):
                    with st.expander("🔍 Self-RAG Execution Trace", expanded=False):
                        for step in result["trace"]:
                            st.write(f"- {step}")

                # Save assistant response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "meta": result
                })
            except Exception as e:
                st.error(f"Execution Error: {e}")
