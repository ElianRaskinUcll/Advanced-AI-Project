"""Tab 1 — Forecast (skeleton). Inhoud volgt in issue 7.2."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from app.sidebar import inject_css, render_sidebar  # noqa: E402

st.set_page_config(page_title="Forecast — Foubert", page_icon="📈", layout="wide")
inject_css()
params = render_sidebar()

st.title("📈 Forecast")
st.write(
    "Heatmap van geforecaste demand per (zone, uur), met toggle tussen "
    "XGBoost en Transformer en een tijdslider om door de dag te scrollen."
)

st.info("**Skeleton — issue 7.2** vult deze pagina met de echte forecast-viz.", icon="🚧")

with st.expander("Sidebar-parameters die deze pagina zal gebruiken"):
    st.json(params)
