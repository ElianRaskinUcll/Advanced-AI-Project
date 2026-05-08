"""Shared sidebar voor alle pages.

Streamlit's pages/-folder rendert per page een eigen sidebar — om dezelfde
parameters op elk tabblad te tonen importeren we render_sidebar() vanuit elke
page-file en roepen we hem als eerste regel aan. De waarden worden in
st.session_state opgeslagen zodat ze meegenomen worden tussen page-switches.
"""
from __future__ import annotations

from pathlib import Path

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
            help=(
                "Selecteert welk dag-profiel uit de 3-dagen-export gebruikt wordt:\n"
                "• **werkdag** — donderdag 30/04, baseline-vraag\n"
                "• **feestdag** — 1 mei (Dag van de Arbeid), piek-vraag\n"
                "• **weekend** — zaterdag 02/05, reservaties domineren"
            ),
        )
        st.session_state.temperatuur = st.slider(
            "Temperatuur (°C)", min_value=5, max_value=35,
            value=int(st.session_state.temperatuur),
            help="Forecaster-input: hogere temperatuur → hogere verwachte ijs-vraag (zie SHAP in notebook 02).",
        )
        st.session_state.neerslag = st.toggle(
            "Neerslag", value=bool(st.session_state.neerslag),
            help="Aan = matige regen (~2 mm/u). Demand op terrassen daalt; afhaal-vraag minder gevoelig.",
        )
        st.session_state.n_karren = st.slider(
            "Aantal beschikbare karren", min_value=1, max_value=15,
            value=int(st.session_state.n_karren),
            help="Hoeveel ijswagens de dispatcher mag inzetten. Foubert heeft er 15 in productie; lager = stress-test van de strategie.",
        )

        st.divider()
        st.caption(
            "ℹ️ [About-pagina](/About) · "
            "📚 [Limitations](https://github.com/RalphBogaertUCLL/Advanced-AI-Project/blob/main/docs/limitations.md)"
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


# Mapping van model-bestand → train-commando dat het opnieuw genereert.
# Gedeeld over alle pages zodat de instructies consistent blijven.
_TRAIN_COMMANDS = {
    "models/xgb_v1.pkl": "python -m src.models.xgb_forecast",
    "models/transformer_v1.pt": "python -m src.models.transformer_forecast",
    "models/q_table.pkl": "python -m src.agents.q_learning",
    "models/dqn_v1.pt": "python -m src.agents.dqn",
    "data/processed/features.parquet": "python -m src.features.build_features",
}


def require_files(*relative_paths: str) -> None:
    """Stop de page met een duidelijke error als een vereist bestand ontbreekt.

    Toont voor elk ontbrekend bestand het commando dat het opnieuw aanmaakt,
    zodat een gebruiker zonder gepre-trainde modellen niet stuit op een
    cryptische FileNotFoundError uit torch/pickle.
    """
    root = Path(__file__).resolve().parent.parent
    missing = [(p, root / p) for p in relative_paths if not (root / p).exists()]
    if not missing:
        return
    lines = ["**Vereiste bestanden ontbreken** — train ze opnieuw via:"]
    for rel, _ in missing:
        cmd = _TRAIN_COMMANDS.get(rel, f"# regenereer {rel}")
        lines.append(f"- `{rel}` → `{cmd}`")
    lines.append(
        "\nZie [README.md — Usage](https://github.com/RalphBogaertUCLL/Advanced-AI-Project#usage) "
        "voor de volledige pipeline-volgorde."
    )
    st.error("\n".join(lines), icon="⚠️")
    st.stop()
