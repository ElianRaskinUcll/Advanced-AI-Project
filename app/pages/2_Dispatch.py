"""Tab 2 — Dispatch (skeleton). Inhoud volgt in issue 7.3."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from app.sidebar import inject_css, render_sidebar  # noqa: E402

st.set_page_config(page_title="Dispatch — Foubert", page_icon="🚐", layout="wide")
inject_css()
params = render_sidebar()

st.title("🚐 Dispatch")
st.write(
    "Animatie van één gesimuleerde dag op basis van de gekozen agent: "
    "live van-posities op kaart, agent-keuze dropdown, play/pause, "
    "live counters voor sales en (un)answered calls."
)

st.info("**Skeleton — issue 7.3** vult deze pagina met de animated map + live counters.", icon="🚧")

with st.expander("Sidebar-parameters die deze pagina zal gebruiken"):
    st.json(params)
