"""
Pecos RAG Benchmark Runner
============================

Streamlit app that:
1. Loads PDFs into a vector store (RAG corpus)
2. Lets you run individual questions or the full 30-question benchmark
3. Compares RAG answers vs baseline (no retrieval) answers
4. Scores answers with an LLM-as-judge against key_points
5. Saves all runs for later comparison (e.g., before vs after adding forum corpus)

Run with:
    streamlit run rag_app.py

Designed to be shown live in an advisor meeting.
"""

import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import streamlit as st

# Local modules
import rag_engine as rag
import evaluator as ev


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

APP_DIR = Path(__file__).parent
BENCHMARK_FILE = APP_DIR / "benchmark_questions.json"
DOCS_DIR = APP_DIR / "documents"             # where PDFs live
DB_DIR = APP_DIR / "vector_db"               # where ChromaDB persists
RUNS_DIR = APP_DIR / "runs"                  # where benchmark runs are saved
for d in (DOCS_DIR, DB_DIR, RUNS_DIR):
    d.mkdir(exist_ok=True)


# -----------------------------------------------------------------------------
# Streamlit config & styling
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Pecos RAG Runner",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .answer-box {
        font-family: 'Charter', 'Georgia', serif;
        font-size: 1.0rem;
        line-height: 1.55;
        background-color: #FAF7F2;
        padding: 1rem 1.2rem;
        border-left: 3px solid #5B7C99;
        border-radius: 4px;
    }
    .baseline-box {
        font-family: 'Charter', 'Georgia', serif;
        background-color: #F5F2F7;
        padding: 1rem 1.2rem;
        border-left: 3px solid #7C5B9C;
        border-radius: 4px;
    }
    .reference-box {
        font-family: 'Charter', 'Georgia', serif;
        background-color: #F2F7F4;
        padding: 1rem 1.2rem;
        border-left: 3px solid #5B9C7C;
        border-radius: 4px;
    }
    .chunk-box {
        background: #F9FAFB;
        border: 1px solid #E5E7EB;
        padding: 0.6rem 0.9rem;
        border-radius: 4px;
        margin: 0.4rem 0;
        font-size: 0.9rem;
        font-family: 'Charter', 'Georgia', serif;
    }
    .score-pill {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.9rem;
        margin: 0.15rem;
    }
    .stat-card {
        background: #F9FAFB;
        padding: 0.9rem;
        border-radius: 6px;
        border: 1px solid #E5E7EB;
        text-align: center;
    }
    .stat-label { font-size: 0.85rem; color: #6B7280; }
    .stat-value { font-size: 1.4rem; font-weight: 700; color: #1F2937; }
    h1 { color: #1E3A5F !important; }
    h2 { color: #2C3E50 !important; }
    code { font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def score_color(score: float) -> str:
    if score >= 0.75:
        return "#166534"  # green
    elif score >= 0.5:
        return "#92400E"  # amber
    else:
        return "#991B1B"  # red


def score_pill_html(label: str, score: float) -> str:
    color = score_color(score)
    return (
        f"<span class='score-pill' style='background:{color}20; color:{color}; "
        f"border:1px solid {color}40;'>{label}: {score:.2f}</span>"
    )


@st.cache_data
def load_benchmark_questions():
    if not BENCHMARK_FILE.exists():
        return None
    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource
def get_vector_store():
    """Cached so the embedder model is only loaded once per session."""
    return rag.VectorStore(db_path=DB_DIR, collection_name="pecos_corpus")


def save_run(run_data: dict, label: str = "run") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RUNS_DIR / f"{timestamp}_{label}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run_data, f, indent=2, ensure_ascii=False, default=str)
    return path


def list_runs():
    return sorted(RUNS_DIR.glob("*.json"), reverse=True)


# -----------------------------------------------------------------------------
# Session state initialization
# -----------------------------------------------------------------------------

if "api_key" not in st.session_state:
    st.session_state.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_eval" not in st.session_state:
    st.session_state.last_eval = None
if "last_baseline" not in st.session_state:
    st.session_state.last_baseline = None
if "last_baseline_eval" not in st.session_state:
    st.session_state.last_baseline_eval = None
if "batch_results" not in st.session_state:
    st.session_state.batch_results = None


# -----------------------------------------------------------------------------
# Sidebar — config & corpus management
# -----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    # API key
    api_key = st.text_input(
        "Anthropic API key",
        value=st.session_state.api_key,
        type="password",
        help="Required to call Claude as the generator and the judge. "
             "Get one at console.anthropic.com.",
    )
    st.session_state.api_key = api_key

    model_choice = st.selectbox(
        "Claude model",
        options=["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
        index=0,
        help="Sonnet 4 is better; Haiku 4.5 is much cheaper and faster.",
    )

    k_retrieve = st.slider(
        "Chunks to retrieve (k)",
        min_value=2, max_value=12, value=5,
        help="How many chunks to retrieve and pass to Claude.",
    )

    st.markdown("---")
    st.markdown("## 📚 Corpus")

    store = get_vector_store()
    stats = store.stats()

    st.metric("Total chunks in store", stats["total_chunks"])
    if stats["sources"]:
        with st.expander(f"Sources ({len(stats['sources'])})"):
            for src, n in sorted(stats["sources"].items()):
                st.markdown(f"- `{src}` ({n} chunks)")

    # Upload PDFs
    uploaded = st.file_uploader(
        "Add PDFs or text files",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        help="Recommended starter set: Bailey 2020, Abbas 2024, SWAT+ manual, "
             "Bedekar 2016 (MT3D-USGS), TXPWC 2024.",
    )

    if uploaded:
        target_words = st.number_input("Target chunk size (words)", 100, 600, 250)
        if st.button("📥 Ingest uploaded files", use_container_width=True, type="primary"):
            progress = st.progress(0.0, text="Starting ingestion...")
            total_added = 0
            for i, up in enumerate(uploaded):
                # Save the uploaded file to documents/
                dest = DOCS_DIR / up.name
                with open(dest, "wb") as f:
                    f.write(up.getbuffer())

                progress.progress(
                    (i + 0.3) / len(uploaded),
                    text=f"Loading {up.name}...",
                )
                try:
                    pages = rag.load_document(dest)
                except Exception as e:
                    st.error(f"Failed to load {up.name}: {e}")
                    continue

                progress.progress(
                    (i + 0.6) / len(uploaded),
                    text=f"Chunking {up.name}...",
                )
                all_chunks = []
                for page_num, text in pages:
                    chunks = rag.chunk_text(
                        text, source=up.name, page=page_num,
                        target_words=target_words,
                    )
                    all_chunks.extend(chunks)

                progress.progress(
                    (i + 0.9) / len(uploaded),
                    text=f"Embedding {len(all_chunks)} chunks from {up.name}...",
                )
                try:
                    n_added = store.add_chunks(all_chunks)
                    total_added += n_added
                except Exception as e:
                    st.error(f"Failed to embed {up.name}: {e}")
                    continue

            progress.progress(1.0, text="Done.")
            st.success(f"Added {total_added} new chunks from {len(uploaded)} file(s).")
            st.rerun()

    if stats["total_chunks"] > 0:
        with st.expander("⚠️ Danger zone"):
            if st.button("🗑️ Reset corpus (delete all chunks)"):
                store.reset()
                # Also delete saved documents
                if DOCS_DIR.exists():
                    shutil.rmtree(DOCS_DIR)
                    DOCS_DIR.mkdir()
                st.success("Corpus reset. All chunks deleted.")
                st.cache_resource.clear()
                st.rerun()


# -----------------------------------------------------------------------------
# Main page
# -----------------------------------------------------------------------------

st.markdown("# 🔬 Pecos RAG Benchmark Runner")
st.caption(
    "Build a RAG corpus, run questions against it, score answers automatically. "
    "Use this to measure how well a retrieval-grounded AI answers your benchmark, "
    "and to compare against a baseline LLM with no retrieval."
)

# Load benchmark
benchmark = load_benchmark_questions()
if benchmark is None:
    st.error(f"Benchmark file not found: {BENCHMARK_FILE}")
    st.stop()

questions = benchmark["questions"]
categories = benchmark["categories"]

# Top status row
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(
        f"<div class='stat-card'><div class='stat-label'>Questions in benchmark</div>"
        f"<div class='stat-value'>{len(questions)}</div></div>",
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"<div class='stat-card'><div class='stat-label'>Chunks in corpus</div>"
        f"<div class='stat-value'>{stats['total_chunks']}</div></div>",
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"<div class='stat-card'><div class='stat-label'>Sources loaded</div>"
        f"<div class='stat-value'>{len(stats['sources'])}</div></div>",
        unsafe_allow_html=True,
    )
with col4:
    n_runs = len(list_runs())
    st.markdown(
        f"<div class='stat-card'><div class='stat-label'>Saved runs</div>"
        f"<div class='stat-value'>{n_runs}</div></div>",
        unsafe_allow_html=True,
    )

# Gate the rest on having an API key
if not api_key:
    st.warning(
        "⚠️ Enter your Anthropic API key in the sidebar to run questions. "
        "You can still upload documents and inspect the corpus without one."
    )

# Tabs for the three main modes
tab_single, tab_batch, tab_runs = st.tabs(
    ["🎯 Single question", "📊 Run full benchmark", "📁 Previous runs"]
)


# -----------------------------------------------------------------------------
# TAB 1 — Single question
# -----------------------------------------------------------------------------

with tab_single:
    st.markdown("### Pick a question to test")

    q_options = [
        f"{q['id']} — [{q['difficulty'].upper()}] {q['subtopic']}"
        for q in questions
    ]
    selected = st.selectbox(
        "Question",
        options=range(len(questions)),
        format_func=lambda i: q_options[i],
    )
    q = questions[selected]

    # Show the question
    st.markdown("#### Question text")
    st.info(q["question"])

    cols_meta = st.columns(4)
    with cols_meta[0]:
        st.caption(f"**ID:** {q['id']}")
    with cols_meta[1]:
        st.caption(f"**Category:** {categories[q['category']]['label']}")
    with cols_meta[2]:
        st.caption(f"**Difficulty:** {q['difficulty']}")
    with cols_meta[3]:
        st.caption(f"**Pecos-specific:** {'Yes' if q['pecos_specific'] else 'No'}")

    # Run button + compare baseline toggle
    run_cols = st.columns([1, 1, 2])
    with run_cols[0]:
        run_rag = st.button(
            "▶️ Run RAG",
            type="primary",
            disabled=not api_key or stats["total_chunks"] == 0,
            use_container_width=True,
        )
    with run_cols[1]:
        run_baseline = st.button(
            "🔵 Also run baseline",
            disabled=not api_key,
            use_container_width=True,
            help="No retrieval — Claude answers from its training knowledge only.",
        )
    with run_cols[2]:
        also_score = st.checkbox(
            "Score with LLM-judge after generating",
            value=True,
            help="Compares the candidate answer to the reference + key_points.",
        )

    # --- RAG run
    if run_rag:
        if stats["total_chunks"] == 0:
            st.error("Corpus is empty. Upload at least one document first.")
        else:
            with st.spinner("Retrieving and generating..."):
                try:
                    result = rag.rag_answer(
                        question=q["question"],
                        store=store,
                        api_key=api_key,
                        k=k_retrieve,
                        model=model_choice,
                    )
                    st.session_state.last_result = result
                    st.session_state.last_eval = None
                except Exception as e:
                    st.error(f"RAG generation failed: {type(e).__name__}: {e}")
                    st.session_state.last_result = None

            if st.session_state.last_result and also_score:
                with st.spinner("Scoring with LLM-judge..."):
                    eval_result = ev.evaluate_answer(
                        question_id=q["id"],
                        question=q["question"],
                        reference=q["reference_answer"],
                        key_points=q["key_points"],
                        candidate=st.session_state.last_result.answer,
                        api_key=api_key,
                        model=model_choice,
                    )
                    st.session_state.last_eval = eval_result

    # --- Baseline run
    if run_baseline:
        with st.spinner("Generating baseline (no retrieval)..."):
            try:
                baseline_text = rag.baseline_answer(
                    question=q["question"],
                    api_key=api_key,
                    model=model_choice,
                )
                st.session_state.last_baseline = baseline_text
                st.session_state.last_baseline_eval = None
            except Exception as e:
                st.error(f"Baseline generation failed: {type(e).__name__}: {e}")
                st.session_state.last_baseline = None

        if st.session_state.last_baseline and also_score:
            with st.spinner("Scoring baseline with LLM-judge..."):
                baseline_eval = ev.evaluate_answer(
                    question_id=q["id"] + "_baseline",
                    question=q["question"],
                    reference=q["reference_answer"],
                    key_points=q["key_points"],
                    candidate=st.session_state.last_baseline,
                    api_key=api_key,
                    model=model_choice,
                )
                st.session_state.last_baseline_eval = baseline_eval

    # --- Display results
    if st.session_state.last_result or st.session_state.last_baseline:
        st.markdown("---")
        st.markdown("### Results")

        # If both run, show side by side; otherwise full width
        if st.session_state.last_result and st.session_state.last_baseline:
            colA, colB = st.columns(2)
        elif st.session_state.last_result:
            colA = st.container()
            colB = None
        else:
            colA = None
            colB = st.container()

        # RAG result
        if st.session_state.last_result and colA is not None:
            with colA:
                st.markdown("#### 🟦 RAG answer (with retrieval)")
                st.markdown(
                    f"<div class='answer-box'>{st.session_state.last_result.answer}</div>",
                    unsafe_allow_html=True,
                )
                if st.session_state.last_eval:
                    e = st.session_state.last_eval
                    if e.error:
                        st.error(f"Judge error: {e.error}")
                    else:
                        pills = (
                            score_pill_html("Overall", e.overall_score)
                            + score_pill_html("Coverage", e.coverage_score)
                            + score_pill_html("Correctness", e.correctness_score)
                            + score_pill_html("Relevance", e.relevance_score)
                        )
                        st.markdown(pills, unsafe_allow_html=True)
                        with st.expander("Judge details"):
                            st.markdown(f"**Notes:** *{e.judge_notes}*")
                            if e.key_points_covered:
                                st.markdown("**Covered key points:**")
                                for kp in e.key_points_covered:
                                    st.markdown(f"- ✅ {kp}")
                            if e.key_points_missed:
                                st.markdown("**Missed key points:**")
                                for kp in e.key_points_missed:
                                    st.markdown(f"- ❌ {kp}")

        # Baseline result
        if st.session_state.last_baseline and colB is not None:
            with colB:
                st.markdown("#### 🟣 Baseline (no retrieval)")
                st.markdown(
                    f"<div class='baseline-box'>{st.session_state.last_baseline}</div>",
                    unsafe_allow_html=True,
                )
                if st.session_state.last_baseline_eval:
                    e = st.session_state.last_baseline_eval
                    if e.error:
                        st.error(f"Judge error: {e.error}")
                    else:
                        pills = (
                            score_pill_html("Overall", e.overall_score)
                            + score_pill_html("Coverage", e.coverage_score)
                            + score_pill_html("Correctness", e.correctness_score)
                            + score_pill_html("Relevance", e.relevance_score)
                        )
                        st.markdown(pills, unsafe_allow_html=True)
                        with st.expander("Judge details"):
                            st.markdown(f"**Notes:** *{e.judge_notes}*")
                            if e.key_points_covered:
                                st.markdown("**Covered:**")
                                for kp in e.key_points_covered:
                                    st.markdown(f"- ✅ {kp}")
                            if e.key_points_missed:
                                st.markdown("**Missed:**")
                                for kp in e.key_points_missed:
                                    st.markdown(f"- ❌ {kp}")

        # Reference + retrieved chunks
        st.markdown("---")
        ref_col, ret_col = st.columns(2)
        with ref_col:
            st.markdown("#### 🟢 Reference answer")
            st.markdown(
                f"<div class='reference-box'>{q['reference_answer']}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("**Key points:**")
            for kp in q["key_points"]:
                st.markdown(f"- {kp}")

        with ret_col:
            if st.session_state.last_result:
                st.markdown("#### 📄 Retrieved chunks")
                retrieved = st.session_state.last_result.retrieved
                if not retrieved.chunks:
                    st.warning("No chunks retrieved. Is the corpus empty?")
                else:
                    for i, (chunk, dist) in enumerate(
                        zip(retrieved.chunks, retrieved.distances)
                    ):
                        with st.expander(
                            f"Chunk {i+1} — {chunk.source}"
                            + (f", p.{chunk.page}" if chunk.page else "")
                            + f" (distance: {dist:.3f})",
                            expanded=(i == 0),
                        ):
                            st.markdown(
                                f"<div class='chunk-box'>{chunk.text}</div>",
                                unsafe_allow_html=True,
                            )

        # Show the actual prompt sent (for debugging / transparency)
        if st.session_state.last_result:
            with st.expander("🔍 Show the full prompt sent to Claude"):
                st.code(st.session_state.last_result.prompt_used, language="text")


# -----------------------------------------------------------------------------
# TAB 2 — Batch run
# -----------------------------------------------------------------------------

with tab_batch:
    st.markdown("### Run multiple questions in one go")
    st.caption(
        "This is what produces your benchmark numbers. Pick a subset (or all 30), "
        "run them, and save the results for later comparison."
    )

    # Subset selection
    subset_choice = st.radio(
        "Which questions?",
        options=["All 30", "Easy only", "Medium only", "Hard only",
                 "Pecos-specific only", "Custom selection"],
        horizontal=True,
    )

    if subset_choice == "All 30":
        subset_ids = [q["id"] for q in questions]
    elif subset_choice == "Easy only":
        subset_ids = [q["id"] for q in questions if q["difficulty"] == "easy"]
    elif subset_choice == "Medium only":
        subset_ids = [q["id"] for q in questions if q["difficulty"] == "medium"]
    elif subset_choice == "Hard only":
        subset_ids = [q["id"] for q in questions if q["difficulty"] == "hard"]
    elif subset_choice == "Pecos-specific only":
        subset_ids = [q["id"] for q in questions if q["pecos_specific"]]
    else:  # Custom
        subset_ids = st.multiselect(
            "Pick questions",
            options=[q["id"] for q in questions],
            default=[],
            format_func=lambda qid: f"{qid} — {next(q['subtopic'] for q in questions if q['id']==qid)}",
        )

    st.caption(f"**{len(subset_ids)}** questions selected")

    # Run options
    run_cols = st.columns(3)
    with run_cols[0]:
        run_mode = st.selectbox(
            "Mode",
            options=["RAG only", "Baseline only", "Both (compare)"],
            help="'Both' takes twice as long and twice the API calls.",
        )
    with run_cols[1]:
        batch_score = st.checkbox("Score each answer with judge", value=True)
    with run_cols[2]:
        run_label = st.text_input("Label for this run", "run1",
                                  help="Used in the saved filename")

    # Cost estimate
    n = len(subset_ids)
    api_calls = n
    if "Both" in run_mode:
        api_calls = n * 2
    if batch_score:
        api_calls += n if run_mode != "Both (compare)" else n * 2

    st.caption(f"≈ **{api_calls}** API calls to Claude. "
               f"Approximate time: {api_calls * 4} seconds (4s per call). "
               f"Approximate cost: ${api_calls * 0.01:.2f} (Sonnet, rough estimate).")

    if st.button(
        f"🚀 Run {n} questions",
        type="primary",
        disabled=not api_key or n == 0 or (run_mode != "Baseline only" and stats["total_chunks"] == 0),
        use_container_width=True,
    ):
        # Build the run
        run_data = {
            "label": run_label,
            "timestamp": datetime.now().isoformat(),
            "model": model_choice,
            "k_retrieve": k_retrieve,
            "mode": run_mode,
            "corpus_stats": stats,
            "results": [],
        }

        progress = st.progress(0.0)
        status = st.empty()

        for i, qid in enumerate(subset_ids):
            q = next(qq for qq in questions if qq["id"] == qid)
            status.write(f"**{i+1}/{n}** — Running {qid}: *{q['subtopic']}*")
            row = {"question_id": qid, "question": q["question"]}

            # RAG run
            if run_mode in ("RAG only", "Both (compare)"):
                try:
                    rag_resp = rag.rag_answer(
                        question=q["question"], store=store,
                        api_key=api_key, k=k_retrieve, model=model_choice,
                    )
                    row["rag_answer"] = rag_resp.answer
                    row["rag_chunks"] = [
                        {"source": c.source, "page": c.page, "text_preview": c.text[:200]}
                        for c in rag_resp.retrieved.chunks
                    ]
                    if batch_score:
                        rag_eval = ev.evaluate_answer(
                            question_id=qid, question=q["question"],
                            reference=q["reference_answer"],
                            key_points=q["key_points"],
                            candidate=rag_resp.answer,
                            api_key=api_key, model=model_choice,
                        )
                        row["rag_eval"] = asdict(rag_eval)
                except Exception as e:
                    row["rag_error"] = f"{type(e).__name__}: {e}"

            # Baseline run
            if run_mode in ("Baseline only", "Both (compare)"):
                try:
                    baseline = rag.baseline_answer(
                        question=q["question"],
                        api_key=api_key, model=model_choice,
                    )
                    row["baseline_answer"] = baseline
                    if batch_score:
                        baseline_eval = ev.evaluate_answer(
                            question_id=qid + "_baseline",
                            question=q["question"],
                            reference=q["reference_answer"],
                            key_points=q["key_points"],
                            candidate=baseline,
                            api_key=api_key, model=model_choice,
                        )
                        row["baseline_eval"] = asdict(baseline_eval)
                except Exception as e:
                    row["baseline_error"] = f"{type(e).__name__}: {e}"

            run_data["results"].append(row)
            progress.progress((i + 1) / n)

        # Aggregate summary
        if batch_score:
            rag_evals = [
                ev.EvalResult(**r["rag_eval"])
                for r in run_data["results"]
                if "rag_eval" in r
            ]
            baseline_evals = [
                ev.EvalResult(**r["baseline_eval"])
                for r in run_data["results"]
                if "baseline_eval" in r
            ]
            run_data["summary"] = {
                "rag": ev.aggregate_results(rag_evals) if rag_evals else None,
                "baseline": ev.aggregate_results(baseline_evals) if baseline_evals else None,
            }

        # Save
        saved_path = save_run(run_data, label=run_label)
        st.session_state.batch_results = run_data
        st.success(f"Done. Saved to `{saved_path.name}`")
        status.empty()

    # Display latest batch results
    if st.session_state.batch_results:
        st.markdown("---")
        st.markdown("### Latest batch results")
        rd = st.session_state.batch_results

        # Summary
        if "summary" in rd:
            sum_cols = st.columns(2)
            with sum_cols[0]:
                if rd["summary"].get("rag"):
                    s = rd["summary"]["rag"]
                    st.markdown("#### 🟦 RAG summary")
                    st.markdown(
                        score_pill_html("Mean Overall", s["mean_overall"])
                        + score_pill_html("Coverage", s["mean_coverage"])
                        + score_pill_html("Correctness", s["mean_correctness"])
                        + score_pill_html("Relevance", s["mean_relevance"]),
                        unsafe_allow_html=True,
                    )
                    st.caption(f"n = {s['n']} ({s['n_errors']} errors)")
            with sum_cols[1]:
                if rd["summary"].get("baseline"):
                    s = rd["summary"]["baseline"]
                    st.markdown("#### 🟣 Baseline summary")
                    st.markdown(
                        score_pill_html("Mean Overall", s["mean_overall"])
                        + score_pill_html("Coverage", s["mean_coverage"])
                        + score_pill_html("Correctness", s["mean_correctness"])
                        + score_pill_html("Relevance", s["mean_relevance"]),
                        unsafe_allow_html=True,
                    )
                    st.caption(f"n = {s['n']} ({s['n_errors']} errors)")

        # Per-question table
        st.markdown("#### Per-question scores")
        table_rows = []
        for r in rd["results"]:
            row = {"id": r["question_id"]}
            if "rag_eval" in r:
                row["RAG overall"] = round(r["rag_eval"]["overall_score"], 2)
                row["RAG coverage"] = round(r["rag_eval"]["coverage_score"], 2)
            if "baseline_eval" in r:
                row["Baseline overall"] = round(r["baseline_eval"]["overall_score"], 2)
                row["Baseline coverage"] = round(r["baseline_eval"]["coverage_score"], 2)
            if "RAG overall" in row and "Baseline overall" in row:
                row["Δ (RAG - baseline)"] = round(
                    row["RAG overall"] - row["Baseline overall"], 2
                )
            table_rows.append(row)
        if table_rows:
            st.dataframe(table_rows, use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# TAB 3 — Previous runs
# -----------------------------------------------------------------------------

with tab_runs:
    st.markdown("### Saved benchmark runs")
    runs = list_runs()
    if not runs:
        st.info("No runs saved yet. Use the 'Run full benchmark' tab to create one.")
    else:
        run_labels = [f"{p.name}" for p in runs]
        selected_run = st.selectbox("Pick a run", options=range(len(runs)),
                                    format_func=lambda i: run_labels[i])
        run_path = runs[selected_run]
        with open(run_path) as f:
            run = json.load(f)

        # Summary
        meta_cols = st.columns(4)
        with meta_cols[0]:
            st.metric("Questions", len(run.get("results", [])))
        with meta_cols[1]:
            st.metric("Mode", run.get("mode", "?"))
        with meta_cols[2]:
            st.metric("Model", run.get("model", "?").replace("claude-", ""))
        with meta_cols[3]:
            st.metric("Timestamp", run.get("timestamp", "?")[:16])

        if "summary" in run and run["summary"]:
            st.markdown("#### Summary")
            sum_cols = st.columns(2)
            with sum_cols[0]:
                if run["summary"].get("rag"):
                    s = run["summary"]["rag"]
                    st.markdown("**🟦 RAG**")
                    st.markdown(
                        score_pill_html("Overall", s["mean_overall"])
                        + score_pill_html("Coverage", s["mean_coverage"])
                        + score_pill_html("Correctness", s["mean_correctness"]),
                        unsafe_allow_html=True,
                    )
            with sum_cols[1]:
                if run["summary"].get("baseline"):
                    s = run["summary"]["baseline"]
                    st.markdown("**🟣 Baseline**")
                    st.markdown(
                        score_pill_html("Overall", s["mean_overall"])
                        + score_pill_html("Coverage", s["mean_coverage"])
                        + score_pill_html("Correctness", s["mean_correctness"]),
                        unsafe_allow_html=True,
                    )

        # Download
        st.download_button(
            "⬇️ Download this run (JSON)",
            data=json.dumps(run, indent=2, ensure_ascii=False, default=str),
            file_name=run_path.name,
            mime="application/json",
        )

        # Per-question view
        st.markdown("---")
        if run.get("results"):
            q_choice = st.selectbox(
                "Inspect one question",
                options=range(len(run["results"])),
                format_func=lambda i: run["results"][i]["question_id"],
            )
            r = run["results"][q_choice]
            st.markdown(f"**Question:** {r['question']}")
            inspect_cols = st.columns(2)
            with inspect_cols[0]:
                if "rag_answer" in r:
                    st.markdown("**🟦 RAG answer**")
                    st.markdown(
                        f"<div class='answer-box'>{r['rag_answer']}</div>",
                        unsafe_allow_html=True,
                    )
                    if "rag_eval" in r:
                        e = r["rag_eval"]
                        st.markdown(
                            score_pill_html("Overall", e["overall_score"])
                            + score_pill_html("Cov", e["coverage_score"])
                            + score_pill_html("Corr", e["correctness_score"]),
                            unsafe_allow_html=True,
                        )
                        st.caption(e.get("judge_notes", ""))
            with inspect_cols[1]:
                if "baseline_answer" in r:
                    st.markdown("**🟣 Baseline**")
                    st.markdown(
                        f"<div class='baseline-box'>{r['baseline_answer']}</div>",
                        unsafe_allow_html=True,
                    )
                    if "baseline_eval" in r:
                        e = r["baseline_eval"]
                        st.markdown(
                            score_pill_html("Overall", e["overall_score"])
                            + score_pill_html("Cov", e["coverage_score"])
                            + score_pill_html("Corr", e["correctness_score"]),
                            unsafe_allow_html=True,
                        )
                        st.caption(e.get("judge_notes", ""))


# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------

st.markdown("---")
with st.expander("ℹ️ How this works"):
    st.markdown(
        """
**Pipeline:**
1. PDFs you upload get chunked (~250 words per chunk, paragraph-aware) and embedded with
   `sentence-transformers/all-MiniLM-L6-v2` (a small, fast, free model that runs locally).
2. Embeddings are stored in ChromaDB on disk (`vector_db/`).
3. When you ask a question, the system retrieves the top-k most similar chunks and passes
   them to Claude with a structured prompt.
4. The **judge** is a separate Claude call that compares the candidate answer to the
   reference answer + key_points and scores three dimensions (coverage, correctness, relevance).

**Why compare against the baseline?**
The baseline is Claude with no retrieval — answering from its training knowledge only.
If your RAG with literature doesn't beat the baseline, retrieval isn't helping.
This is the experiment that, when you later add the forum corpus, will demonstrate
the actual contribution of community knowledge.

**Cost & speed:**
Each Sonnet 4 call ≈ $0.01 and 3-5 seconds. Running all 30 questions in
"Both + score" mode = 120 API calls = ~$1-2 and ~7 minutes.
Switch to `claude-haiku-4-5` for ~10x cheaper and faster, slightly less reliable judge.
        """
    )
