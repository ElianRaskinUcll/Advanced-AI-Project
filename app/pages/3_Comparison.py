"""Tab 3 — Comparison: alle 5 agents naast elkaar op dezelfde gesimuleerde dag.

Hergebruikt `evaluate_episode` uit src/eval/metrics.py voor identieke metric-
berekening als de offline eval-suite (issue 5.1). Replay-acties voor de
Historical-agent worden eenmaal per (datum, n_vans) gebouwd via cache_resource
zodat opeenvolgende runs niet elke keer DBSCAN op alle GPS hoeven herdoen.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch  # noqa: F401  # torch before pandas on Windows

from datetime import date as date_t

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app.sidebar import inject_css, render_sidebar, require_files
from src.agents.dqn import DQNAgent, MODEL_PATH as DQN_PATH
from src.agents.greedy_agent import GreedyAgent
from src.agents.historical_agent import HistoricalAgent
from src.agents.q_learning import Q_TABLE_PATH, TabularQAgent
from src.agents.random_agent import RandomAgent
from src.env.dispatcher_env import DispatcherEnv
from src.env.forecast_service import ForecastService
from src.env.replay import build_replay_actions
from src.eval.metrics import evaluate_episode

st.set_page_config(page_title="Comparison — Foubert", page_icon="📊", layout="wide")
inject_css()
params = render_sidebar()
require_files("models/transformer_v1.pt", "models/q_table.pkl", "models/dqn_v1.pt")

DAG_TYPE_TO_DATE = {
    "werkdag": date_t(2026, 4, 30),
    "feestdag": date_t(2026, 5, 1),
    "weekend": date_t(2026, 5, 2),
}
AGENT_NAMES = ["Random", "Greedy", "Historical", "Q-learning", "DQN"]


@st.cache_resource(show_spinner=False)
def _dqn_trained_n_vans() -> int:
    """Lees uit het checkpoint hoeveel vans de DQN-policy verwacht.

    obs_dim = 2 * n_vans + 1, dus n_vans = (input_dim - 1) // 2.
    """
    ckpt = torch.load(DQN_PATH, weights_only=False, map_location="cpu")
    return (int(ckpt["config"]["input_dim"]) - 1) // 2


# ---------- Cached resources ----------

@st.cache_resource(show_spinner="Forecaster laden (eenmalig per session)…")
def get_forecaster() -> ForecastService:
    return ForecastService()


@st.cache_resource(show_spinner="Replay-acties opbouwen (eenmalig per dag)…")
def get_replay_actions(target_date_iso: str, n_vans: int) -> np.ndarray:
    target_date = date_t.fromisoformat(target_date_iso)
    env = DispatcherEnv(date=target_date, n_vans=n_vans, seed=42, forecaster=get_forecaster())
    actions, _ = build_replay_actions(target_date, env, mode="stops")
    return actions


def _load_dqn(env: DispatcherEnv) -> DQNAgent:
    a = DQNAgent(env)
    ckpt = torch.load(DQN_PATH, weights_only=False)
    a.q_net.load_state_dict(ckpt["q_state_dict"])
    a.target_net.load_state_dict(ckpt["target_state_dict"])
    a.q_net.eval()
    return a


class _PrebuiltHistorical:
    """HistoricalAgent-vervanger die voorgebakken replay-acties hergebruikt."""

    name = "historical"

    def __init__(self, env: DispatcherEnv, actions: np.ndarray):
        self.env = env
        self._actions = actions
        self._step = 0

    def reset(self, seed: int | None = None) -> None:
        self._step = 0

    def select_action(self, obs=None, info=None):
        if self._step >= len(self._actions):
            return self.env._van_zones.copy()
        a = self._actions[self._step]
        self._step += 1
        return a


def _make_agent(name: str, env: DispatcherEnv, target_date: date_t):
    if name == "Random":
        return RandomAgent(env)
    if name == "Greedy":
        return GreedyAgent(env)
    if name == "Historical":
        actions = get_replay_actions(target_date.isoformat(), env.n_vans)
        return _PrebuiltHistorical(env, actions)
    if name == "Q-learning":
        return TabularQAgent.load(env, Q_TABLE_PATH)
    if name == "DQN":
        return _load_dqn(env)
    raise ValueError(name)


# ---------- Run-all (cached per param tuple) ----------

@st.cache_data(show_spinner="Alle agents draaien op dezelfde dag…")
def run_all_agents(dag_type: str, n_karren: int, seed: int = 42) -> pd.DataFrame:
    forecaster = get_forecaster()
    target_date = DAG_TYPE_TO_DATE[dag_type]
    # DQN's eerste-laag is fixed op de trained input_dim; bij andere n_vans
    # zou load_state_dict crashen. We slaan hem dan over en de UI toont een
    # warning. Andere 4 agents zijn n_vans-onafhankelijk.
    skip_dqn = n_karren != _dqn_trained_n_vans()
    rows = []
    for name in AGENT_NAMES:
        if name == "DQN" and skip_dqn:
            continue
        env = DispatcherEnv(date=target_date, n_vans=n_karren, seed=seed, forecaster=forecaster)

        def factory(e, d, _name=name):
            return _make_agent(_name, e, d)

        rows.append(evaluate_episode(factory, env, target_date, seed, name=name))
    return pd.DataFrame(rows)


# ---------- UI ----------

st.title("📊 Comparison")
target_date = DAG_TYPE_TO_DATE[params["dag_type"]]
st.caption(
    f"Vergelijk alle agents op **{target_date} ({params['dag_type']})** met "
    f"**{params['n_karren']} karren**. Resultaten worden gecached per (dag-type, n_karren); "
    "opnieuw klikken met dezelfde sidebar laadt instantly."
)

_dqn_n_vans = _dqn_trained_n_vans()
if params["n_karren"] != _dqn_n_vans:
    st.warning(
        f"⚠️ DQN is getraind op **{_dqn_n_vans} karren** (input-laag fixed) en wordt "
        f"bij {params['n_karren']} karren overgeslagen. De andere 4 agents zijn "
        "n_vans-onafhankelijk en draaien wél. Zet de slider op "
        f"{_dqn_n_vans} om DQN mee te nemen.",
        icon="🤖",
    )

run_clicked = st.button("▶ Run all agents", type="primary")

# Always trigger compute via the cached function — first call computes, repeats hit cache
if run_clicked or "comparison_df" in st.session_state:
    df = run_all_agents(params["dag_type"], params["n_karren"])
    st.session_state["comparison_df"] = df
else:
    st.info("Druk op **Run all agents** om de vergelijking te starten.", icon="🚦")
    st.stop()

df = st.session_state["comparison_df"]


# ---------- 1. Hero KPI ----------

historical_calls = int(df.loc[df["agent"] == "Historical", "n_sales_answered"].iloc[0])
best_row = df.loc[df["n_sales_answered"].idxmax()]
delta = int(best_row["n_sales_answered"]) - historical_calls

st.divider()
hero_l, hero_r = st.columns([2, 3], gap="large")
with hero_l:
    st.metric(
        label="Hoeveel calls extra t.o.v. echte trajecten?",
        value=(f"+{delta}" if delta >= 0 else f"{delta}"),
        delta=f"door agent {best_row['agent']}",
        delta_color="normal" if delta >= 0 else "inverse",
    )
with hero_r:
    if delta > 0:
        st.write(
            f"De **{best_row['agent']}**-agent zou op {target_date} "
            f"**{int(best_row['n_sales_answered'])}** calls hebben beantwoord, vs "
            f"**{historical_calls}** met de echte historische van-trajecten — "
            f"dat is **+{delta} extra calls**."
        )
    elif delta == 0:
        st.write(
            f"Beste agent ({best_row['agent']}) evenaart de Historical-replay van "
            f"{historical_calls} beantwoorde calls."
        )
    else:
        st.write(
            f"Geen enkele agent doet beter dan de Historical-replay van "
            f"{historical_calls} beantwoorde calls op deze dag (best: "
            f"{best_row['agent']} met {int(best_row['n_sales_answered'])})."
        )


# ---------- 2. Results table met highlights ----------

st.subheader("Resultaten-tabel")
display = df[
    ["agent", "pct_answered", "revenue_eur", "distance_km", "mean_response_min", "fairness_gini"]
].rename(
    columns={
        "pct_answered": "% answered",
        "revenue_eur": "Revenue (€)",
        "distance_km": "Distance (km)",
        "mean_response_min": "Response (min)",
        "fairness_gini": "Fairness Gini",
    }
)
styler = (
    display.style
    .format({
        "% answered": "{:.1f}",
        "Revenue (€)": "€{:,.0f}",
        "Distance (km)": "{:.1f}",
        "Response (min)": "{:.1f}",
        "Fairness Gini": "{:.3f}",
    })
    .highlight_max(subset=["% answered", "Revenue (€)"], color="#c8e6c9")
    .highlight_min(subset=["Distance (km)", "Response (min)", "Fairness Gini"], color="#c8e6c9")
)
st.dataframe(styler, use_container_width=True, hide_index=True)


# ---------- 3. Per-metric bar charts ----------

st.subheader("Per-metric vergelijking")
chart_cols = st.columns(4)
metric_specs: list[tuple[str, str, bool]] = [
    ("pct_answered", "% answered", True),
    ("revenue_eur", "Revenue (€)", True),
    ("distance_km", "Distance (km)", False),
    ("mean_response_min", "Response (min)", False),
]

for col, (col_name, title, higher_better) in zip(chart_cols, metric_specs):
    with col:
        bar_df = df[["agent", col_name]].copy()
        if higher_better:
            bar_df["best"] = bar_df[col_name] == bar_df[col_name].max()
        else:
            bar_df["best"] = bar_df[col_name] == bar_df[col_name].min()
        chart = (
            alt.Chart(bar_df)
            .mark_bar()
            .encode(
                x=alt.X("agent:N", sort=None, axis=alt.Axis(labelAngle=-30, title=None)),
                y=alt.Y(f"{col_name}:Q", title=title),
                color=alt.condition("datum.best", alt.value("#e8743c"), alt.value("#9aa1ad")),
                tooltip=["agent", alt.Tooltip(f"{col_name}:Q", format=".2f")],
            )
            .properties(height=240)
        )
        st.altair_chart(chart, use_container_width=True)


# ---------- 4. Efficiency frontier ----------

st.subheader("Efficiency frontier — omzet per gereden km")
st.caption(
    "Linksboven = ideaal (veel omzet, weinig km). Rechtsonder = inefficiënt. "
    "**X-as is log-schaal** zodat Random (vaak ~10× meer km dan de rest) niet "
    "alle andere agents tot één punt platdrukt."
)

# Guard tegen distance=0 op log-schaal (nooit echt nul, maar veilig).
scatter_df = df.assign(distance_km_plot=np.maximum(df["distance_km"], 0.1))

scatter = (
    alt.Chart(scatter_df)
    .mark_circle(size=700, opacity=0.9, stroke="white", strokeWidth=2)
    .encode(
        x=alt.X(
            "distance_km_plot:Q",
            title="Distance (km, log-schaal) — lager is beter",
            scale=alt.Scale(type="log", nice=False, padding=10),
        ),
        y=alt.Y(
            "revenue_eur:Q",
            title="Revenue (€) — hoger is beter",
            scale=alt.Scale(zero=False, padding=15),
        ),
        color=alt.Color(
            "agent:N",
            scale=alt.Scale(scheme="category10"),
            legend=alt.Legend(title="Agent", orient="right"),
        ),
        tooltip=[
            alt.Tooltip("agent:N"),
            alt.Tooltip("pct_answered:Q", title="% answered", format=".1f"),
            alt.Tooltip("revenue_eur:Q", title="Revenue", format="€,.0f"),
            alt.Tooltip("distance_km:Q", title="Distance", format=".1f"),
            alt.Tooltip("mean_response_min:Q", title="Response", format=".1f"),
        ],
    )
    .properties(height=420)
)
labels = (
    alt.Chart(scatter_df)
    .mark_text(align="left", baseline="middle", dx=18, fontSize=14, fontWeight="bold")
    .encode(
        x="distance_km_plot:Q",
        y="revenue_eur:Q",
        text="agent:N",
        color=alt.Color("agent:N", scale=alt.Scale(scheme="category10"), legend=None),
    )
)
st.altair_chart(scatter + labels, use_container_width=True)
