"""
Pecos SWAT+ Modeling Benchmark — Review & Editing App
======================================================

Streamlit app for reviewing the 30-question benchmark with your advisor.
Designed for in-meeting use: filter, navigate, edit reference answers,
take notes, and export the revised version.

Run with:
    streamlit run benchmark_app.py

Author: David Serrano Suarez
"""

import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

BENCHMARK_FILE = Path(__file__).parent / "benchmark_questions.json"
BACKUP_DIR = Path(__file__).parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

st.set_page_config(
    page_title="Pecos Benchmark Review",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Styling — restrained, functional, easy to read in a meeting
# -----------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Use a clear serif for reading reference answers, sans for UI */
    .reference-answer {
        font-family: 'Charter', 'Georgia', serif;
        font-size: 1.02rem;
        line-height: 1.55;
        background-color: #FAF7F2;
        padding: 1rem 1.2rem;
        border-left: 3px solid #5B7C99;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
    .question-text {
        font-size: 1.15rem;
        font-weight: 500;
        color: #1F2937;
        margin-bottom: 0.5rem;
        line-height: 1.4;
    }
    .key-point-pill {
        display: inline-block;
        background-color: #E8EEF4;
        color: #2C3E50;
        padding: 0.2rem 0.6rem;
        margin: 0.15rem;
        border-radius: 12px;
        font-size: 0.82rem;
        font-family: 'SF Mono', 'Consolas', monospace;
    }
    .meta-row {
        color: #6B7280;
        font-size: 0.9rem;
        margin-top: 0.2rem;
    }
    .difficulty-easy { color: #166534; font-weight: 600; }
    .difficulty-medium { color: #92400E; font-weight: 600; }
    .difficulty-hard { color: #991B1B; font-weight: 600; }
    .pecos-tag {
        background-color: #FEF3C7;
        color: #78350F;
        padding: 0.15rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .stTextArea textarea {
        font-family: 'Charter', 'Georgia', serif;
        font-size: 0.98rem;
    }
    .stat-card {
        background: #F9FAFB;
        padding: 0.8rem;
        border-radius: 6px;
        border: 1px solid #E5E7EB;
    }
    h1 { color: #1E3A5F !important; }
    h2 { color: #2C3E50 !important; }
    h3 { color: #34495E !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Data loading & saving
# -----------------------------------------------------------------------------

@st.cache_data
def load_benchmark():
    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_benchmark(data, label="autosave"):
    # Always save to main file
    with open(BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # And keep a timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"benchmark_{timestamp}_{label}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return backup_file


# Initialize session state from disk on first load
if "data" not in st.session_state:
    st.session_state.data = load_benchmark()
if "current_idx" not in st.session_state:
    st.session_state.current_idx = 0
if "show_reference" not in st.session_state:
    st.session_state.show_reference = True
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False

data = st.session_state.data
questions = data["questions"]
categories = data["categories"]

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

DIFFICULTY_CLASSES = {
    "easy": "difficulty-easy",
    "medium": "difficulty-medium",
    "hard": "difficulty-hard",
}

DIFFICULTY_LABELS = {
    "easy": "Easy",
    "medium": "Medium",
    "hard": "Hard",
}


def filter_questions(qs, cat_filter, diff_filter, pecos_filter, search):
    out = []
    for q in qs:
        if cat_filter and q["category"] not in cat_filter:
            continue
        if diff_filter and q["difficulty"] not in diff_filter:
            continue
        if pecos_filter == "Pecos-specific only" and not q["pecos_specific"]:
            continue
        if pecos_filter == "General only" and q["pecos_specific"]:
            continue
        if search:
            blob = (q["question"] + " " + q["reference_answer"]).lower()
            if search.lower() not in blob:
                continue
        out.append(q)
    return out


# -----------------------------------------------------------------------------
# Sidebar — navigation & filters
# -----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Pecos Benchmark")
    st.caption(f"v{data['metadata']['version']} · {len(questions)} questions · {len(categories)} topics")

    st.markdown("---")
    st.markdown("### Filters")

    cat_options = list(categories.keys())
    cat_filter = st.multiselect(
        "Category",
        options=cat_options,
        format_func=lambda c: categories[c]["label"],
        default=[],
        help="Empty = all categories",
    )

    diff_filter = st.multiselect(
        "Difficulty",
        options=["easy", "medium", "hard"],
        format_func=lambda d: DIFFICULTY_LABELS[d],
        default=[],
    )

    pecos_filter = st.radio(
        "Pecos relevance",
        options=["All", "Pecos-specific only", "General only"],
        index=0,
    )

    search = st.text_input("Search text", "", placeholder="word in question or answer...")

    filtered = filter_questions(questions, cat_filter, diff_filter, pecos_filter, search)

    st.markdown("---")
    st.markdown("### Navigate")
    st.caption(f"Showing **{len(filtered)}** of {len(questions)} questions")

    if filtered:
        ids = [q["id"] for q in filtered]
        # Find current_id within filtered list, fall back to first if not present
        current_id = questions[st.session_state.current_idx]["id"]
        try:
            pos_in_filter = ids.index(current_id)
        except ValueError:
            pos_in_filter = 0

        selected_id = st.selectbox(
            "Jump to question",
            options=ids,
            index=pos_in_filter,
            format_func=lambda qid: f"{qid} — {next(q for q in filtered if q['id']==qid)['subtopic']}",
        )
        # Update current_idx based on selection (idx in full list)
        st.session_state.current_idx = next(
            i for i, q in enumerate(questions) if q["id"] == selected_id
        )

    st.markdown("---")
    st.markdown("### Display")
    st.session_state.show_reference = st.toggle(
        "Show reference answer",
        value=st.session_state.show_reference,
        help="Hide when quizzing yourself or your advisor before revealing the answer",
    )
    st.session_state.edit_mode = st.toggle(
        "Edit mode",
        value=st.session_state.edit_mode,
        help="Turn on to modify the reference answer or notes",
    )

    st.markdown("---")
    st.markdown("### Export")
    export_label = st.text_input("Backup label", "review_session", help="Tag for the backup file")
    if st.button("💾 Save current state", use_container_width=True):
        backup_path = save_benchmark(data, label=export_label)
        st.success(f"Saved. Backup: `{backup_path.name}`")

    # Download button
    st.download_button(
        "⬇️ Download JSON",
        data=json.dumps(data, indent=2, ensure_ascii=False),
        file_name=f"benchmark_questions_{datetime.now().strftime('%Y%m%d')}.json",
        mime="application/json",
        use_container_width=True,
    )

# -----------------------------------------------------------------------------
# Main panel
# -----------------------------------------------------------------------------

st.markdown("# 🌊 Pecos SWAT+ Modeling Benchmark")
st.caption(data["metadata"]["description"])

# Top stats row
col1, col2, col3, col4 = st.columns(4)
total_easy = sum(1 for q in questions if q["difficulty"] == "easy")
total_medium = sum(1 for q in questions if q["difficulty"] == "medium")
total_hard = sum(1 for q in questions if q["difficulty"] == "hard")
total_pecos = sum(1 for q in questions if q["pecos_specific"])

with col1:
    st.markdown(
        f"<div class='stat-card'><b>{len(questions)}</b> total questions</div>",
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"<div class='stat-card'><b>{len(categories)}</b> topics · "
        f"<b>{total_pecos}</b> Pecos-specific</div>",
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"<div class='stat-card'><span class='difficulty-easy'>{total_easy}</span> easy · "
        f"<span class='difficulty-medium'>{total_medium}</span> medium · "
        f"<span class='difficulty-hard'>{total_hard}</span> hard</div>",
        unsafe_allow_html=True,
    )
with col4:
    st.markdown(
        f"<div class='stat-card'><b>v{data['metadata']['version']}</b> — "
        f"{data['metadata']['review_status']}</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# If no questions match filter, bail early
if not filtered:
    st.warning("No questions match the current filters. Adjust filters in the sidebar.")
    st.stop()

# Clamp current_idx to filtered set
current_q = questions[st.session_state.current_idx]
if current_q not in filtered:
    current_q = filtered[0]
    st.session_state.current_idx = questions.index(current_q)

# Determine position within filtered set for prev/next
filtered_ids = [q["id"] for q in filtered]
pos_in_filter = filtered_ids.index(current_q["id"])

# Navigation row (prev / counter / next)
nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns([1, 1, 2, 1, 1])

with nav_col1:
    if st.button("⬅ Previous", disabled=(pos_in_filter == 0), use_container_width=True):
        prev_id = filtered_ids[pos_in_filter - 1]
        st.session_state.current_idx = next(i for i, q in enumerate(questions) if q["id"] == prev_id)
        st.rerun()

with nav_col3:
    st.markdown(
        f"<div style='text-align:center; padding-top:0.4rem;'>"
        f"<b>Question {pos_in_filter + 1}</b> of {len(filtered)} in current filter"
        f"</div>",
        unsafe_allow_html=True,
    )

with nav_col5:
    if st.button("Next ➡", disabled=(pos_in_filter == len(filtered) - 1), use_container_width=True):
        next_id = filtered_ids[pos_in_filter + 1]
        st.session_state.current_idx = next(i for i, q in enumerate(questions) if q["id"] == next_id)
        st.rerun()

st.markdown("---")

# -----------------------------------------------------------------------------
# Question display
# -----------------------------------------------------------------------------

q = current_q
cat = categories[q["category"]]

# ID + category tag + difficulty + Pecos tag
header_html = (
    f"<div style='display:flex; gap:0.8rem; align-items:center; flex-wrap:wrap; margin-bottom:0.5rem;'>"
    f"<span style='font-family:monospace; font-size:1.1rem; font-weight:600; color:{cat['color']};'>{q['id']}</span>"
    f"<span style='background:{cat['color']}; color:white; padding:0.15rem 0.6rem; border-radius:4px; font-size:0.85rem;'>{cat['label']}</span>"
    f"<span class='{DIFFICULTY_CLASSES[q['difficulty']]}'>● {DIFFICULTY_LABELS[q['difficulty']]}</span>"
)
if q["pecos_specific"]:
    header_html += "<span class='pecos-tag'>PECOS-SPECIFIC</span>"
header_html += "</div>"
st.markdown(header_html, unsafe_allow_html=True)

st.markdown(
    f"<div class='meta-row'>Subtopic: <i>{q['subtopic']}</i> · Expected source: <i>{q['expected_source']}</i></div>",
    unsafe_allow_html=True,
)

st.markdown("### Question")
st.markdown(f"<div class='question-text'>{q['question']}</div>", unsafe_allow_html=True)

# Reference answer
st.markdown("### Reference answer")

if not st.session_state.show_reference:
    st.info("Reference answer hidden. Toggle 'Show reference answer' in the sidebar to reveal.")
else:
    if st.session_state.edit_mode:
        new_ref = st.text_area(
            "Edit reference answer",
            value=q["reference_answer"],
            height=240,
            key=f"ref_{q['id']}",
            label_visibility="collapsed",
        )
        if new_ref != q["reference_answer"]:
            if st.button("💾 Apply changes to reference answer", type="primary"):
                q["reference_answer"] = new_ref
                save_benchmark(data, label=f"edit_{q['id']}")
                st.success(f"Updated reference answer for {q['id']} (auto-backup saved)")
                st.rerun()
    else:
        st.markdown(
            f"<div class='reference-answer'>{q['reference_answer']}</div>",
            unsafe_allow_html=True,
        )

# Key points
st.markdown("### Key points (for evaluation)")
if st.session_state.edit_mode:
    new_kps = st.text_area(
        "Key points (one per line)",
        value="\n".join(q["key_points"]),
        height=120,
        key=f"kp_{q['id']}",
        help="These are matched against AI responses to score partial credit",
    )
    new_kps_list = [k.strip() for k in new_kps.split("\n") if k.strip()]
    if new_kps_list != q["key_points"]:
        if st.button("💾 Apply changes to key points"):
            q["key_points"] = new_kps_list
            save_benchmark(data, label=f"edit_kp_{q['id']}")
            st.success(f"Updated key points for {q['id']}")
            st.rerun()
else:
    pills_html = " ".join(
        f"<span class='key-point-pill'>{kp}</span>" for kp in q["key_points"]
    )
    st.markdown(pills_html, unsafe_allow_html=True)

# Evaluation notes
st.markdown("### Evaluation notes")
if st.session_state.edit_mode:
    new_eval = st.text_area(
        "Evaluation notes",
        value=q.get("evaluation_notes", ""),
        height=80,
        key=f"eval_{q['id']}",
    )
    if new_eval != q.get("evaluation_notes", ""):
        if st.button("💾 Apply changes to evaluation notes"):
            q["evaluation_notes"] = new_eval
            save_benchmark(data, label=f"edit_ev_{q['id']}")
            st.success(f"Updated evaluation notes for {q['id']}")
            st.rerun()
else:
    notes = q.get("evaluation_notes", "")
    if notes:
        st.markdown(f"*{notes}*")
    else:
        st.caption("(no evaluation notes yet)")

# Advisor notes — a new field for the meeting
st.markdown("### 📝 Advisor / review notes")
advisor_notes = q.get("advisor_notes", "")
new_advisor = st.text_area(
    "Notes from review meeting (saved automatically when changed)",
    value=advisor_notes,
    height=100,
    key=f"adv_{q['id']}",
    placeholder="e.g., 'Prof X says reconsider point 3', 'add reference to Y', 'check value range in semi-arid context'...",
)
if new_advisor != advisor_notes:
    q["advisor_notes"] = new_advisor
    save_benchmark(data, label=f"advnote_{q['id']}")
    st.caption("✓ Note saved")

# -----------------------------------------------------------------------------
# Footer — category summary table at the bottom
# -----------------------------------------------------------------------------

st.markdown("---")
with st.expander("📊 Topic breakdown"):
    rows = []
    for cat_key, cat_info in categories.items():
        n = sum(1 for x in questions if x["category"] == cat_key)
        n_pecos = sum(1 for x in questions if x["category"] == cat_key and x["pecos_specific"])
        n_hard = sum(1 for x in questions if x["category"] == cat_key and x["difficulty"] == "hard")
        rows.append(
            {
                "Topic": cat_info["label"],
                "Questions": n,
                "Pecos-specific": n_pecos,
                "Hard": n_hard,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

with st.expander("ℹ️ About this benchmark"):
    st.markdown(
        f"""
        **Purpose.** Evaluate AI assistants (RAG systems, fine-tuned LLMs, agentic systems) on
        their ability to answer real questions about coupled surface-groundwater modeling,
        contaminant transport, and produced water reuse — with a focus on the Pecos watershed.

        **How to use in a review meeting.**
        1. Filter by topic (sidebar) to focus the discussion — e.g. 'PFLOTRAN Challenges' or 'PhD Motivation'.
        2. Hide the reference answer (sidebar toggle) and let your advisor answer first.
        3. Reveal the reference. Discuss disagreements.
        4. Switch to Edit mode to update the reference or key points.
        5. Use the **Advisor / review notes** field to record what to change later.
        6. Click **Save current state** at the end to create a timestamped backup.

        **Status.** {data['metadata']['review_status']}

        **Notes from metadata:** {data['metadata']['notes']}
        """
    )
