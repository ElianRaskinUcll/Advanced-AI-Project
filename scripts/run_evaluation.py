"""Issue 5.1 DoD: één commando dat alle metrics voor de fiche genereert.

Run: python scripts/run_evaluation.py
Output: results/eval_summary.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ isn't on sys.path by default when invoked via "python scripts/X.py";
# add the project root so `src.*` imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch  # noqa: F401  # torch first on Windows

import time
from datetime import date as date_t

import pandas as pd

from src.agents.dqn import DQNAgent, MODEL_PATH as DQN_PATH
from src.agents.greedy_agent import GreedyAgent
from src.agents.historical_agent import HistoricalAgent
from src.agents.q_learning import Q_TABLE_PATH, TabularQAgent
from src.agents.random_agent import RandomAgent
from src.env.dispatcher_env import DispatcherEnv
from src.env.forecast_service import ForecastService
from src.eval.metrics import evaluate_episode

DATES = [date_t(2026, 4, 30), date_t(2026, 5, 1), date_t(2026, 5, 2)]
N_SEEDS = 5
RESULTS_DIR = Path("results")
OUTPUT_PATH = RESULTS_DIR / "eval_summary.csv"


def load_dqn(env: DispatcherEnv) -> DQNAgent:
    agent = DQNAgent(env)
    ckpt = torch.load(DQN_PATH, weights_only=False)
    agent.q_net.load_state_dict(ckpt["q_state_dict"])
    agent.target_net.load_state_dict(ckpt["target_state_dict"])
    agent.q_net.eval()
    return agent


AGENT_FACTORIES = {
    "random":     lambda env, d: RandomAgent(env),
    "greedy":     lambda env, d: GreedyAgent(env),
    "historical": lambda env, d: HistoricalAgent(env, d),
    "q_learning": lambda env, d: TabularQAgent.load(env, Q_TABLE_PATH),
    "dqn":        lambda env, d: load_dqn(env),
}


def main() -> None:
    print(f"Loading shared forecaster ...")
    forecaster = ForecastService()
    env = DispatcherEnv(date=DATES[0], n_vans=15, seed=42, forecaster=forecaster)
    print(f"env: n_zones={env.n_zones} n_vans={env.n_vans}")
    print(f"Running {len(AGENT_FACTORIES)} agents x {len(DATES)} days x {N_SEEDS} seeds = "
          f"{len(AGENT_FACTORIES)*len(DATES)*N_SEEDS} episodes\n")

    rows = []
    t0 = time.time()
    for name, factory in AGENT_FACTORIES.items():
        for d in DATES:
            for seed in range(N_SEEDS):
                rows.append(evaluate_episode(factory, env, d, seed=seed, name=name))
            print(f"  {name:11s} on {d}: done ({time.time()-t0:.0f}s elapsed)", flush=True)
    df = pd.DataFrame(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nWrote {len(df)} rows to {OUTPUT_PATH}")

    summary = df.groupby("agent").agg(
        pct_answered_mean=("pct_answered", "mean"),
        revenue_eur_mean=("revenue_eur", "mean"),
        distance_km_mean=("distance_km", "mean"),
        mean_response_min_mean=("mean_response_min", "mean"),
        fairness_gini_mean=("fairness_gini", "mean"),
        neglected_zones_pct_mean=("neglected_zones_pct", "mean"),
    ).round(2).sort_values("revenue_eur_mean", ascending=False)
    print("\nAggregated summary (mean over all dates × seeds):")
    print(summary.to_string())


if __name__ == "__main__":
    main()
