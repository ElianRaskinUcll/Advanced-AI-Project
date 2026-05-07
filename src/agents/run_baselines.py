"""Smoke-runner for issue 4.1 DoD: run all 3 baselines on one day, no crash."""
from __future__ import annotations

import torch  # noqa: F401

from datetime import date

from src.agents.greedy_agent import GreedyAgent
from src.agents.historical_agent import HistoricalAgent
from src.agents.random_agent import RandomAgent
from src.env.dispatcher_env import DispatcherEnv
from src.env.forecast_service import ForecastService

TARGET_DATE = date(2026, 4, 30)


def run_one(agent_cls, forecaster, **kwargs):
    env = DispatcherEnv(date=TARGET_DATE, n_vans=15, seed=42, forecaster=forecaster)
    agent = agent_cls(env, **kwargs)
    obs, _ = env.reset(seed=42, options={"date": TARGET_DATE})
    agent.reset(seed=42)
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    n_steps = 0
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, reward, terminated, truncated, info = env.step(action)
        n_steps += 1
    return n_steps, info


if __name__ == "__main__":
    print("Loading shared forecaster...")
    forecaster = ForecastService()

    for cls, kwargs in [
        (RandomAgent, {}),
        (GreedyAgent, {}),
        (HistoricalAgent, {"target_date": TARGET_DATE}),
    ]:
        n_steps, info = run_one(cls, forecaster, **kwargs)
        print(f"  {cls.name:11s}: {n_steps} steps, "
              f"calls={info['n_total_calls']:4d}, sales={info['n_total_sales']:4d}")
