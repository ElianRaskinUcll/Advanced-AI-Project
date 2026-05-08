from __future__ import annotations

import torch  # noqa: F401  # torch before pandas on Windows

import numpy as np

from src.env.dispatcher_env import DispatcherEnv


class RandomAgent:
    """Picks a uniformly random target zone for every van each step."""

    name = "random"

    def __init__(self, env: DispatcherEnv):
        self.env = env

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.env.action_space.seed(seed)

    def select_action(self, obs: np.ndarray | None = None,
                      info: dict | None = None) -> np.ndarray:
        return self.env.action_space.sample()


if __name__ == "__main__":
    from datetime import date
    from src.env.forecast_service import ForecastService

    forecaster = ForecastService()
    env = DispatcherEnv(date=date(2026, 4, 30), n_vans=15, seed=42, forecaster=forecaster)
    agent = RandomAgent(env)
    obs, _ = env.reset(seed=42)
    agent.reset(seed=42)
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, _, terminated, truncated, info = env.step(action)
    print(f"random: calls={info['n_total_calls']} sales={info['n_total_sales']}")
