"""Tab 3 — Comparison (skeleton). Inhoud volgt in issue 7.4."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from app.sidebar import inject_css, render_sidebar  # noqa: E402

st.set_page_config(page_title="Comparison — Foubert", page_icon="📊", layout="wide")
inject_css()
params = render_sidebar()

st.title("📊 Comparison")
st.write(
    "Volledige vergelijking van alle 5 agents (random, greedy, historical, "
    "q_learning, dqn) over de 3 dagen × seeds: tabel, bar charts, scatter "
    "(distance vs. answered calls), met als KPI hoeveel extra calls de "
    "RL-agents beantwoorden bovenop greedy."
)

st.info("**Skeleton — issue 7.4** vult deze pagina met de volledige comparison-viz.", icon="🚧")

with st.expander("Sidebar-parameters die deze pagina zal gebruiken"):
    st.json(params)
