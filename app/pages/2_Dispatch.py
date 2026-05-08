"""Tab 2 — Dispatch: agent kiezen, één dag uitspelen, vans + calls op kaart.

Twee fasen:
1. Compute — eerst draait de hele dag in de Gym-env (66 steps, ~3 sec) en
   wordt per step (van-posities, nieuwe calls, sales, log-events) bewaard in
   st.session_state.
2. Playback — placeholders worden frame-per-frame ververst met time.sleep()
   tussen renders. Pause/play via session_state-flag; de loop checkt 'm
   tussen elke step.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch  # noqa: F401  # torch before pandas on Windows

from datetime import date as date_t

import h3
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from app.sidebar import inject_css, render_sidebar, require_files
from src.agents.dqn import DQNAgent, MODEL_PATH as DQN_PATH
from src.agents.greedy_agent import GreedyAgent
from src.agents.historical_agent import HistoricalAgent
from src.agents.q_learning import Q_TABLE_PATH, TabularQAgent
from src.agents.random_agent import RandomAgent
from src.env.dispatcher_env import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    TIME_STEP_MINUTES,
    DispatcherEnv,
)
from src.env.forecast_service import ForecastService

st.set_page_config(page_title="Dispatch — Foubert", page_icon="🚐", layout="wide")
inject_css()
params = render_sidebar()
require_files("models/transformer_v1.pt", "models/q_table.pkl", "models/dqn_v1.pt")

DAG_TYPE_TO_DATE = {
    "werkdag": date_t(2026, 4, 30),
    "feestdag": date_t(2026, 5, 1),
    "weekend": date_t(2026, 5, 2),
}
RESPONSE_THRESHOLD_MIN = 30
MEAN_SALE_VALUE_EUR = 14.0


# ---------- Resource loaders ----------

@st.cache_resource(show_spinner="Forecaster laden (eenmalig per session)…")
def get_forecaster() -> ForecastService:
    return ForecastService()


@st.cache_resource
def get_zone_centroids(_zones: tuple[str, ...]) -> np.ndarray:
    return np.array([h3.cell_to_latlng(z) for z in _zones], dtype="float64")


def load_dqn(env: DispatcherEnv) -> DQNAgent:
    agent = DQNAgent(env)
    ckpt = torch.load(DQN_PATH, weights_only=False)
    agent.q_net.load_state_dict(ckpt["q_state_dict"])
    agent.target_net.load_state_dict(ckpt["target_state_dict"])
    agent.q_net.eval()
    return agent


def make_agent(name: str, env: DispatcherEnv, target_date: date_t):
    if name == "Random":
        return RandomAgent(env)
    if name == "Greedy":
        return GreedyAgent(env)
    if name == "Historical":
        return HistoricalAgent(env, target_date)
    if name == "Q-learning":
        return TabularQAgent.load(env, Q_TABLE_PATH)
    if name == "DQN":
        return load_dqn(env)
    raise ValueError(f"Unknown agent {name}")


# ---------- Trajectory compute ----------

def step_time_to_hhmm(t_min: int) -> str:
    return f"{t_min // 60:02d}:{t_min % 60:02d}"


def run_full_day(agent_name: str, target_date: date_t, n_vans: int, seed: int) -> dict:
    """Run env for one day with chosen agent. Return per-step trajectory dict."""
    forecaster = get_forecaster()
    env = DispatcherEnv(date=target_date, n_vans=n_vans, seed=seed, forecaster=forecaster)
    agent = make_agent(agent_name, env, target_date)
    obs, _ = env.reset(seed=seed, options={"date": target_date})
    agent.reset(seed=seed)

    n_steps = (DAY_END_HOUR - DAY_START_HOUR) * 60 // TIME_STEP_MINUTES
    van_zones_history = np.zeros((n_steps, n_vans), dtype=np.int64)
    new_calls_per_step: list[list[dict]] = []
    new_sales_per_step: list[list[dict]] = []
    info_history: list[dict] = []

    prev_calls_n = 0
    prev_sales_n = 0
    terminated = truncated = False
    step = 0
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, _, terminated, truncated, info = env.step(action)
        van_zones_history[step] = action[: n_vans]
        new_calls_per_step.append(env._sampled_calls[prev_calls_n:].copy())
        new_sales_per_step.append(env._sampled_sales[prev_sales_n:].copy())
        prev_calls_n = len(env._sampled_calls)
        prev_sales_n = len(env._sampled_sales)
        info_history.append(info)
        step += 1
        if step >= n_steps:
            break

    # Classify each call: answered if same-zone van within RESPONSE_THRESHOLD_MIN
    classified: list[dict] = []
    for c in env._sampled_calls:
        ct, cz = c["time_min"], c["zone_idx"]
        answered_at = None
        for s in range(n_steps):
            step_t = DAY_START_HOUR * 60 + s * TIME_STEP_MINUTES
            if step_t < ct:
                continue
            if step_t > ct + RESPONSE_THRESHOLD_MIN:
                break
            if (van_zones_history[s] == cz).any():
                answered_at = step_t
                break
        classified.append({**c, "answered_at": answered_at,
                            "status": "answered" if answered_at is not None else "missed"})

    # Cumulative counts
    answered_cum = np.zeros(n_steps, dtype=np.int64)
    missed_cum = np.zeros(n_steps, dtype=np.int64)
    sales_cum = np.array([info["n_total_sales"] for info in info_history], dtype=np.int64)
    for c in classified:
        if c["status"] == "answered":
            s = (c["answered_at"] - DAY_START_HOUR * 60) // TIME_STEP_MINUTES
            if 0 <= s < n_steps:
                answered_cum[s:] += 1
        else:
            # mark missed at created_time + threshold
            t_miss = c["time_min"] + RESPONSE_THRESHOLD_MIN
            s = (t_miss - DAY_START_HOUR * 60) // TIME_STEP_MINUTES
            if 0 <= s < n_steps:
                missed_cum[s:] += 1
            elif s >= n_steps:
                missed_cum[-1] += 1

    return {
        "agent_name": agent_name,
        "date": target_date.isoformat(),
        "n_steps": n_steps,
        "n_vans": n_vans,
        "zones": list(env.zones),
        "van_zones_history": van_zones_history,
        "new_calls_per_step": new_calls_per_step,
        "new_sales_per_step": new_sales_per_step,
        "classified_calls": classified,
        "answered_cum": answered_cum,
        "missed_cum": missed_cum,
        "sales_cum": sales_cum,
    }


# ---------- Map rendering ----------

def render_frame(traj: dict, step: int, centroids: np.ndarray) -> pdk.Deck:
    n_vans = traj["n_vans"]
    van_zones_now = traj["van_zones_history"][step]
    van_pts = pd.DataFrame({
        "lat": centroids[van_zones_now][:, 0],
        "lng": centroids[van_zones_now][:, 1],
        "kar": [f"kar {i+1}" for i in range(n_vans)],
    })

    # Calls visible: created at-or-before now, status known
    now_min = DAY_START_HOUR * 60 + step * TIME_STEP_MINUTES
    visible_calls = []
    for c in traj["classified_calls"]:
        if c["time_min"] > now_min:
            continue
        # Show call until answered_at (then keep green for 2 steps as fade-out)
        # or until created+threshold (then mark red)
        if c["status"] == "answered":
            if c["answered_at"] is not None and now_min > c["answered_at"] + 20:
                continue  # fade out after 20 min
            color = [70, 200, 100] if c["answered_at"] is not None and now_min >= c["answered_at"] else [255, 200, 60]
        else:
            if now_min > c["time_min"] + 90:
                continue  # remove old missed calls after 90 min
            color = [220, 60, 60] if now_min >= c["time_min"] + RESPONSE_THRESHOLD_MIN else [255, 200, 60]
        visible_calls.append({
            "lat": float(centroids[c["zone_idx"]][0]),
            "lng": float(centroids[c["zone_idx"]][1]),
            "color_r": color[0], "color_g": color[1], "color_b": color[2],
            "nr": str(c.get("nr_of_people", "?")),
        })

    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=visible_calls,
            get_position="[lng, lat]",
            get_fill_color="[color_r, color_g, color_b, 200]",
            get_radius=160,
            pickable=True,
            stroked=False,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=van_pts.to_dict("records"),
            get_position="[lng, lat]",
            get_fill_color=[40, 110, 220, 255],
            get_radius=220,
            pickable=True,
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
        ),
    ]
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=51.10, longitude=4.24, zoom=10, pitch=0),
        map_provider=None,
        tooltip={"text": "{kar}{nr}"},
    )


def build_log_lines(traj: dict, up_to_step: int, max_lines: int = 30) -> list[str]:
    """Genereer event-log: nieuwe calls + answered + missed events, gesorteerd op tijd."""
    events: list[tuple[int, str]] = []
    for s in range(up_to_step + 1):
        t_min = DAY_START_HOUR * 60 + s * TIME_STEP_MINUTES
        for c in traj["new_calls_per_step"][s]:
            events.append((c["time_min"], f"{step_time_to_hhmm(c['time_min'])} 📞 nieuwe call in zone {c['zone_idx']} ({c.get('nr_of_people','?')} pers)"))
        for sale in traj["new_sales_per_step"][s]:
            events.append((sale["time_min"], f"{step_time_to_hhmm(sale['time_min'])} 💰 sale in zone {sale['zone_idx']}"))
    # answered/missed events
    now_min = DAY_START_HOUR * 60 + up_to_step * TIME_STEP_MINUTES
    for c in traj["classified_calls"]:
        if c["status"] == "answered" and c["answered_at"] is not None and c["answered_at"] <= now_min:
            events.append((c["answered_at"], f"{step_time_to_hhmm(c['answered_at'])} ✅ call zone {c['zone_idx']} beantwoord"))
        elif c["status"] == "missed" and c["time_min"] + RESPONSE_THRESHOLD_MIN <= now_min:
            events.append((c["time_min"] + RESPONSE_THRESHOLD_MIN, f"{step_time_to_hhmm(c['time_min']+RESPONSE_THRESHOLD_MIN)} ❌ call zone {c['zone_idx']} gemist"))

    events.sort(key=lambda x: x[0])
    return [line for _, line in events[-max_lines:]]


# ---------- Page UI ----------

st.title("🚐 Dispatch")
st.caption("Speel een hele dag af met de gekozen agent en zie waar de karren rijden.")

ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 1])
with ctrl1:
    agent_name = st.selectbox(
        "Agent",
        ["Random", "Greedy", "Historical", "Q-learning", "DQN"],
        index=3, key="dispatch_agent",
    )
with ctrl2:
    sim_date = DAG_TYPE_TO_DATE[params["dag_type"]]
    st.metric("Dag", f"{sim_date} ({params['dag_type']})")
with ctrl3:
    run_clicked = st.button("▶ Run simulation", type="primary", use_container_width=True)

# Initialize session state
for k, default in [("trajectory", None), ("step_idx", 0), ("playing", False)]:
    if k not in st.session_state:
        st.session_state[k] = default

if run_clicked:
    st.session_state.trajectory = run_full_day(
        agent_name, sim_date, n_vans=params["n_karren"], seed=42,
    )
    st.session_state.step_idx = 0
    st.session_state.playing = True

traj = st.session_state.trajectory
if traj is None:
    st.info("Selecteer een agent en druk op **Run simulation** om de dag uit te spelen.", icon="🚦")
    st.stop()

# Counters strip
n_steps = traj["n_steps"]
step_idx = int(st.session_state.step_idx)
step_idx = max(0, min(step_idx, n_steps - 1))

now_min = DAY_START_HOUR * 60 + step_idx * TIME_STEP_MINUTES
sales_now = int(traj["sales_cum"][step_idx])
answered_now = int(traj["answered_cum"][step_idx])
missed_now = int(traj["missed_cum"][step_idx])
revenue_now = sales_now * MEAN_SALE_VALUE_EUR

c1, c2, c3, c4 = st.columns(4)
counter_phs = [c.empty() for c in (c1, c2, c3, c4)]
counter_phs[0].metric("⏱️ Tijd", step_time_to_hhmm(now_min))
counter_phs[1].metric("✅ Beantwoorde calls", answered_now)
counter_phs[2].metric("❌ Gemiste calls", missed_now)
counter_phs[3].metric("💰 Omzet (EUR)", f"{revenue_now:,.0f}")

map_col, log_col = st.columns([3, 1], gap="medium")
map_ph = map_col.empty()
log_ph = log_col.empty()
log_col.caption("Activity log (laatste 30)")

# Initial render
zone_centroids = get_zone_centroids(tuple(traj["zones"]))
map_ph.pydeck_chart(render_frame(traj, step_idx, zone_centroids))
log_ph.text("\n".join(build_log_lines(traj, step_idx)))

# Playback controls
ctl1, ctl2, ctl3, ctl4 = st.columns([2, 1, 1, 4])
with ctl1:
    new_step = st.slider("Step", min_value=0, max_value=n_steps - 1, value=step_idx, key="step_slider")
    if new_step != step_idx and not st.session_state.playing:
        st.session_state.step_idx = new_step
        st.rerun()
with ctl2:
    if st.button("⏸ Pauze" if st.session_state.playing else "▶ Verder",
                 use_container_width=True, key="play_btn"):
        st.session_state.playing = not st.session_state.playing
        st.rerun()
with ctl3:
    if st.button("⏮ Reset", use_container_width=True, key="reset_btn"):
        st.session_state.step_idx = 0
        st.session_state.playing = False
        st.rerun()
with ctl4:
    speed = st.slider("Snelheid (× real-time)", 1, 60, 30, key="speed_slider")

# Auto-play loop: render frames in-place, advance step_idx
if st.session_state.playing and step_idx < n_steps - 1:
    # Real-time = 600 wall sec per step (10 min sim per step). 60× = 10 wall sec/step.
    # Practical mapping: speed=1 → 1.0s, speed=60 → 0.05s/step.
    delay = max(0.05, 1.0 / speed)
    for s in range(step_idx + 1, n_steps):
        if not st.session_state.get("playing"):
            break
        time.sleep(delay)
        # Update counters
        now_min = DAY_START_HOUR * 60 + s * TIME_STEP_MINUTES
        counter_phs[0].metric("⏱️ Tijd", step_time_to_hhmm(now_min))
        counter_phs[1].metric("✅ Beantwoorde calls", int(traj["answered_cum"][s]))
        counter_phs[2].metric("❌ Gemiste calls", int(traj["missed_cum"][s]))
        counter_phs[3].metric("💰 Omzet (EUR)", f"{int(traj['sales_cum'][s]) * MEAN_SALE_VALUE_EUR:,.0f}")
        # Update map + log
        map_ph.pydeck_chart(render_frame(traj, s, zone_centroids))
        log_ph.text("\n".join(build_log_lines(traj, s)))
        st.session_state.step_idx = s
    # At end of loop, mark not-playing
    if st.session_state.step_idx >= n_steps - 1:
        st.session_state.playing = False
