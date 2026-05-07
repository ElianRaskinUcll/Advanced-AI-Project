from __future__ import annotations

import torch  # noqa: F401  # torch before pandas on Windows

from datetime import date as date_t

import numpy as np

from src.env.dispatcher_env import DispatcherEnv
from src.env.replay import build_replay_actions


class HistoricalAgent:
    """Replays the actual van trajectories from the historical data.

    Builds the per-step action sequence once (via shifts + GPS, with the
    stops-based snap from issue 3.4) and emits one row per `select_action`
    call. After the action stream is exhausted (end of operating window) it
    keeps every van in its current zone.
    """

    name = "historical"

    def __init__(self, env: DispatcherEnv, target_date: date_t):
        self.env = env
        self.target_date = target_date
        self._actions: np.ndarray | None = None
        self._step: int = 0

    def reset(self, seed: int | None = None) -> None:
        self._actions, _ = build_replay_actions(self.target_date, self.env, mode="stops")
        self._step = 0

    def select_action(self, obs: np.ndarray | None = None,
                      info: dict | None = None) -> np.ndarray:
        if self._actions is None:
            self.reset()
        if self._step >= len(self._actions):
            return self.env._van_zones.copy()
        action = self._actions[self._step]
        self._step += 1
        return action


if __name__ == "__main__":
    from datetime import date
    from src.env.forecast_service import ForecastService

    target = date(2026, 4, 30)
    forecaster = ForecastService()
    env = DispatcherEnv(date=target, n_vans=15, seed=42, forecaster=forecaster)
    agent = HistoricalAgent(env, target)
    obs, _ = env.reset(seed=42, options={"date": target})
    agent.reset(seed=42)
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, _, terminated, truncated, info = env.step(action)
    print(f"historical: calls={info['n_total_calls']} sales={info['n_total_sales']}")
