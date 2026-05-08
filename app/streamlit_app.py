"""Streamlit entrypoint — Foubert IJs dispatcher demo.

Run met:    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Project root op sys.path zodat src.* imports werken vanuit de app
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from app.sidebar import inject_css, render_sidebar  # noqa: E402

st.set_page_config(
    page_title="Foubert Dispatcher Demo",
    page_icon="🍦",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
params = render_sidebar()

st.title("🍦 Foubert IJs — Dispatcher Demo")
st.write(
    "Interactieve verkenning van demand-forecasts en dispatch-strategieën, "
    "gebouwd op de 3-dagen Foubert-export (30 apr — 2 mei 2026)."
)

st.divider()
left, mid, right = st.columns(3)
with left:
    st.subheader("📈 Forecast")
    st.write(
        "Vergelijk XGBoost en Transformer voorspellingen per zone × uur. "
        "Selecteer dag-type en weer in de sidebar; zie hoe het forecast verandert."
    )
    st.page_link("pages/1_Forecast.py", label="Open forecast", icon="📈")

with mid:
    st.subheader("🚐 Dispatch")
    st.write(
        "Speel één dag af met een gekozen agent (random, greedy, Q-learning, DQN). "
        "Zie waar elke kar rijdt, welke calls beantwoord worden en welke gemist."
    )
    st.page_link("pages/2_Dispatch.py", label="Open dispatch", icon="🚐")

with right:
    st.subheader("📊 Comparison")
    st.write(
        "Vergelijk alle agents op % calls answered, revenue, distance en response time. "
        "Resultaten uit de eval-suite, met scatterplot en bar charts."
    )
    st.page_link("pages/3_Comparison.py", label="Open comparison", icon="📊")

st.divider()
st.caption(
    f"Huidige sidebar-parameters → dag: **{params['dag_type']}** · "
    f"temperatuur: **{params['temperatuur']}°C** · "
    f"neerslag: **{'aan' if params['neerslag'] else 'uit'}** · "
    f"karren: **{params['n_karren']}**"
)
