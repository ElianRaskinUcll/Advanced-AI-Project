"""Shared sidebar voor alle pages.

Streamlit's pages/-folder rendert per page een eigen sidebar — om dezelfde
parameters op elk tabblad te tonen importeren we render_sidebar() vanuit elke
page-file en roepen we hem als eerste regel aan. De waarden worden in
st.session_state opgeslagen zodat ze meegenomen worden tussen page-switches.
"""
from __future__ import annotations

import streamlit as st

DAY_TYPES = ["werkdag", "feestdag", "weekend"]

DEFAULTS = {
    "dag_type": "werkdag",
    "temperatuur": 20,
    "neerslag": False,
    "n_karren": 15,
}


def _ensure_defaults() -> None:
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar() -> dict:
    """Toon de sidebar en return een dict met de huidige parameters."""
    _ensure_defaults()
    with st.sidebar:
        st.title("🍦 Foubert Dispatcher")
        st.caption("Demo — interactieve verkenning van forecast & dispatch")
        st.divider()
        st.subheader("Globale parameters")

        st.session_state.dag_type = st.selectbox(
            "Dag-type",
            DAY_TYPES,
            index=DAY_TYPES.index(st.session_state.dag_type),
            help="Werkdag = baseline, feestdag = piek-vraag (zoals 1 mei), weekend = reservaties domineren.",
        )
        st.session_state.temperatuur = st.slider(
            "Temperatuur (°C)", min_value=5, max_value=35,
            value=int(st.session_state.temperatuur),
        )
        st.session_state.neerslag = st.toggle(
            "Neerslag", value=bool(st.session_state.neerslag),
            help="Aan = regen verwacht; demand op terrassen daalt.",
        )
        st.session_state.n_karren = st.slider(
            "Aantal beschikbare karren", min_value=1, max_value=15,
            value=int(st.session_state.n_karren),
        )

        st.divider()
        st.caption(
            "Repo: [Advanced-AI-Project](../). "
            "Limitations: zie [docs/limitations.md](../docs/limitations.md)."
        )

    return {key: st.session_state[key] for key in DEFAULTS}


CSS = """
<style>
/* Foubert-ish accent: warm zalmrood voor primaire knoppen + headers */
:root {
    --foubert-orange: #e8743c;
    --foubert-cream: #f9f3e6;
}
section[data-testid="stSidebar"] h1 {
    color: var(--foubert-orange);
}
.stButton > button[kind="primary"] {
    background-color: var(--foubert-orange);
    border-color: var(--foubert-orange);
}
/* Subtieler grid + cards in main area */
[data-testid="stMetricValue"] {
    color: var(--foubert-orange);
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
