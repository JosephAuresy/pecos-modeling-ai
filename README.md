# Pecos Modeling AI

> Community-grounded AI tooling for coupled surface–groundwater hydrologic modeling, with a focus on the Pecos watershed and produced water beneficial reuse in Texas.

**Status:** 🚧 Early-stage PhD research. Active development. Expect rough edges.

---

## What this is

This repository hosts the practical infrastructure for a PhD research program on AI-assisted hydrologic modeling. It supports four research papers:

1. **An empirical taxonomy of hydrologic modeling errors** from SWAT/MODFLOW/SWAT+ community forums.
2. **A flexible-mesh SWAT+/gwflow model of the Pecos watershed** with rigorous uncertainty quantification.
3. **A multi-code transport comparison** (MT3D-USGS, PFLOTRAN, Delft3D-FM) for PFAS and salinity from produced water discharge.
4. **A community-knowledge-grounded AI assistant** for hydrologic modeling decisions, validated on Pecos-specific questions.

This repo currently contains the Paper 4 prototype: a Streamlit-based RAG system, benchmark of 30 questions, and LLM-as-judge evaluation framework.

## Why this matters

The state of Texas is reviewing permit applications for more than 18 million gallons per day of treated produced water discharge into the Pecos watershed. Models supporting these decisions need to capture coupled surface–groundwater flow, contaminant transport, and uncertainty rigorously. The community of modelers that has built SWAT, MODFLOW, and related tools over two decades has documented thousands of failure modes and fixes in public forums — but that knowledge has never been mined as a scientific dataset, and is not reflected in current AI tools for hydrology.

This work aims to close that gap.

---

## Quick start

```bash
# Clone
git clone https://github.com/<your-username>/pecos-modeling-ai.git
cd pecos-modeling-ai

# Set up a virtual environment (recommended)
python -m venv venv
source venv/bin/activate          # macOS/Linux
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Run the benchmark review app
cd benchmark_app
streamlit run benchmark_app.py
```

For the RAG runner you'll also need an Anthropic API key (see `benchmark_app/README.md`).

---

## Repository structure

```
pecos-modeling-ai/
├── benchmark_app/              # Streamlit apps and RAG infrastructure
│   ├── benchmark_questions.json    # The 30-question benchmark (source of truth)
│   ├── benchmark_app.py            # Review/edit the questions with your advisor
│   ├── rag_app.py                  # Build a RAG, run benchmark, score answers
│   ├── rag_engine.py               # PDF loading, chunking, retrieval, generation
│   ├── evaluator.py                # LLM-as-judge for scoring against key_points
│   └── README.md                   # Detailed usage docs
├── docs/                       # Proposal documents, notes, references
│   └── proposal/                   # The PhD proposal draft
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT
└── README.md                   # This file
```

---

## Citation

If you use this work, please cite (placeholder — to be updated as papers are published):

```
Serrano Suarez, David. (2026). Pecos Modeling AI: Community-grounded AI tooling for
coupled surface-groundwater hydrologic modeling. [Software].
https://github.com/<your-username>/pecos-modeling-ai
```

---

## Funding & affiliation

This work is part of a PhD at the Department of Civil, Environmental & Construction Engineering, Texas Tech University.
Supported in part by Texas Water Development Board / Texas Produced Water Consortium.

---

## License

MIT — see `LICENSE` for details.

---

## Contact

David Serrano Suarez — davidser@ttu.edu

For technical questions about the code: open an issue. For research questions or collaboration: email.
