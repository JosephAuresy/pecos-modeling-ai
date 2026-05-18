# Pecos SWAT+ Modeling Benchmark — Tooling

Two Streamlit apps for building, reviewing, and evaluating an AI-assisted
hydrologic modeling benchmark, plus the underlying RAG and evaluator modules.

This is the practical infrastructure for **Paper 4** of the PhD: a community-grounded
AI assistant for SWAT+/gwflow modeling, validated on Pecos watershed questions.

---

## What's in this folder

| File | Purpose |
|---|---|
| `benchmark_questions.json` | The 30 questions, reference answers, key_points, metadata. **Source of truth.** |
| `benchmark_app.py` | Review/edit app — read questions, hide/show reference, edit in place, take advisor notes. |
| `rag_app.py` | RAG runner app — upload PDFs, build vector store, run questions, score with LLM-judge. |
| `rag_engine.py` | Library: PDF loading, chunking, vector store, retrieval, Claude generation. |
| `evaluator.py` | Library: LLM-as-judge scoring against `key_points`. |
| `documents/` | (Auto-created) where uploaded PDFs are stored. |
| `vector_db/` | (Auto-created) where ChromaDB persists embeddings. |
| `runs/` | (Auto-created) saved benchmark runs with all answers and scores. |
| `backups/` | (Auto-created) timestamped backups of every edit to the questions. |
| `README.md` | This file. |

---

## Setup

### 1. Install dependencies

```bash
pip install streamlit chromadb sentence-transformers anthropic pypdf
```

First time you run the RAG app it will download the embedding model
(`all-MiniLM-L6-v2`, ~80 MB) — automatic, runs locally on CPU.

### 2. Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com).
You'll need it for the RAG app (not for the review app).

You can either:
- Paste it into the sidebar each time you start `rag_app.py`, or
- Set it once with `export ANTHROPIC_API_KEY=sk-ant-...` before launching

### 3. Pick the app you need

**For reviewing/editing the questions** (e.g., in a meeting with your advisor):
```bash
streamlit run benchmark_app.py
```

**For building a RAG and running the benchmark**:
```bash
streamlit run rag_app.py
```

---

## Workflow: from zero to first benchmark result

This is what you should do once, in roughly this order. Counts on you having
~30–60 minutes and an API key with maybe $2 of credit.

### Step 1 — Validate questions with your advisor (`benchmark_app.py`)

Run `benchmark_app.py`. With your advisor, walk through the Pecos-specific +
hard questions (Q08, Q14, Q17, Q22, Q27, Q28, Q30 are the highest stakes).
Edit any reference answers you both want to change. The app auto-backs-up
every edit.

### Step 2 — Build the corpus (`rag_app.py`, sidebar)

Run `rag_app.py`. In the sidebar, upload the **5 starter PDFs**:

1. **Bailey et al. 2020** — *A New Physically-Based Spatially-Distributed Groundwater Flow Module for SWAT+* — MDPI Hydrology 7(4):75
2. **Abbas et al. 2024** — *A framework for parameter estimation, sensitivity analysis, and uncertainty analysis for holistic hydrologic modeling using SWAT+* — HESS 28:21–48
3. **Bedekar et al. 2016** — *MT3D-USGS version 1* — USGS TM 6-A53
4. **SWAT+ Input/Output documentation** — from swat.tamu.edu
5. **Texas Produced Water Consortium 2024 Report** — from depts.ttu.edu/research/tx-water-consortium

Click "Ingest uploaded files". The app shows progress as it chunks and embeds.
Takes 1–5 minutes total.

### Step 3 — Try a single question first (Single question tab)

Pick **Q11** ("¿Cuándo es necesario usar gwflow...?") — it's medium difficulty
and the answer is in Bailey 2020 which you just uploaded.

Click **Run RAG**. Then click **Also run baseline** to compare. Look at the
scores. Look at which chunks were retrieved. Look at what the judge said.

This is the moment you understand what RAG is. Don't skip it.

### Step 4 — Run the full benchmark (Run full benchmark tab)

Pick "All 30", "Both (compare)", and "Score each answer". Hit go.

Takes ~10–15 minutes and costs roughly $1–3 in API calls (Sonnet 4).

When it's done, look at the per-question table. **The difference between RAG and
baseline is your first measurement.** This is the Paper 4 baseline result that
all your subsequent work will improve on.

### Step 5 — Save and iterate

The run is auto-saved in `runs/`. The next time you add documents (e.g., a
forum corpus), repeat Step 4 and compare scores. If the forum corpus is doing
its job, hard / Pecos-specific questions should improve more than easy ones.

---

## Architecture decisions

**Why ChromaDB + sentence-transformers locally?**
- Free, no external service needed.
- ChromaDB persists to disk so your corpus survives reloads.
- `all-MiniLM-L6-v2` is good enough for a starter system and runs in seconds on CPU.
- You can swap to OpenAI/Cohere embeddings later if you want; the interface is the same.

**Why Claude as both generator and judge?**
- Simpler than mixing providers.
- The judge prompt is structured to force JSON output, which makes it robust.
- For Paper 4 you may want to validate the judge against human ratings on a subset — this is a standard "LLM-as-judge validation" experiment.

**Why a separate `rag_engine.py`?**
- The Streamlit app shouldn't be the only way to use this.
- You can import `rag_engine` from a Jupyter notebook for batch experiments.
- The chunking and retrieval logic is reusable for Paper 1 (forum corpus) too.

---

## Limitations & known issues

- **Chunking is paragraph-aware but not section-aware.** PDFs with messy
  text extraction (multi-column layouts, embedded equations, tables) will
  produce noisy chunks. For Paper 4 quality, consider switching to a
  structured PDF parser (e.g., GROBID, unstructured.io) later.

- **No reranking yet.** Top-k retrieval by cosine similarity only.
  Adding a reranker (BGE-reranker open-source, or Cohere Rerank) is a
  documented improvement; we left it out for simplicity.

- **The judge is the same model that generated.** If Sonnet writes a confident
  wrong answer, Sonnet might score it generously. For Paper 4, plan a
  validation experiment: 30 candidate answers × 3 human raters vs the judge.

- **API costs accumulate quickly.** "Run all 30, both modes, with scoring" is
  120 API calls. At Sonnet pricing that's $1–3 per full run. Switch to
  Haiku 4.5 for ~10× cheaper if you're iterating frequently.

---

## Next steps after first run

1. **Validate the judge.** Pick 10 questions. Have your advisor manually
   score the RAG and baseline answers. Compare to the LLM-judge scores.
   This gives Paper 4 credibility.

2. **Add Paper 2 / Paper 3 documents** to the corpus as your modeling work
   progresses. Each major reference you read should land here.

3. **Build the forum corpus** (Paper 1). Once you have ~100 SWAT/MODFLOW
   forum threads tagged and stored, ingest them as text files and re-run.
   The hard / Pecos-specific category should be where you see the biggest
   improvement.

4. **Add a re-ranker** when you have >100 documents in the corpus and
   retrieval quality starts to matter more than coverage.

5. **Document everything.** Each run is saved with timestamp, model, k,
   and corpus stats. When you write Paper 4, this is your method section.
