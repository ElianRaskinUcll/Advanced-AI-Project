from __future__ import annotations

import torch  # noqa: F401  # torch before pandas on Windows

import h3
import numpy as np

from src.env.dispatcher_env import DispatcherEnv

EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat = p2 - p1
    dlng = np.radians(lng2 - lng1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


class GreedyAgent:
    """Sends the nearest free van to each open (recent) call.

    "Open" call = sampled call with age <= OPEN_CALL_WINDOW_MIN. Greedy
    matching: pick the (van, call) pair with smallest distance, assign, remove
    both from pool, repeat. Vans not assigned to a call remain at their
    current zone.
    """

    name = "greedy"
    OPEN_CALL_WINDOW_MIN = 30

    def __init__(self, env: DispatcherEnv):
        self.env = env
        self._zone_centroids = np.array(
            [h3.cell_to_latlng(z) for z in env.zones], dtype="float64"
        )

    def reset(self, seed: int | None = None) -> None:
        pass  # stateless

    def select_action(self, obs: np.ndarray | None = None,
                      info: dict | None = None) -> np.ndarray:
        env = self.env
        action = env._van_zones.copy()  # default: keep current zone

        free_van_idx = np.where(~env._van_busy)[0]
        if len(free_van_idx) == 0:
            return action

        now = env._time_minutes
        open_calls = [
            c for c in env._sampled_calls
            if now - c["time_min"] <= self.OPEN_CALL_WINDOW_MIN
        ]
        if not open_calls:
            return action

        # Unique call zones (one van per zone is enough; further calls in same
        # zone are served by the same van)
        seen = set()
        unique_calls = []
        for c in open_calls:
            if c["zone_idx"] not in seen:
                seen.add(c["zone_idx"])
                unique_calls.append(c)
        if not unique_calls:
            return action

        van_centroids = self._zone_centroids[env._van_zones[free_van_idx]]
        call_zone_idx = np.array([c["zone_idx"] for c in unique_calls], dtype=np.int64)
        call_centroids = self._zone_centroids[call_zone_idx]

        # Pairwise distance (n_free_vans, n_calls)
        vlat, vlng = van_centroids[:, 0:1], van_centroids[:, 1:2]
        clat, clng = call_centroids[None, :, 0], call_centroids[None, :, 1]
        dist = _haversine_m(vlat, vlng, clat, clng)

        used_van = np.zeros(len(free_van_idx), dtype=bool)
        used_call = np.zeros(len(unique_calls), dtype=bool)
        while True:
            masked = np.where(used_van[:, None] | used_call[None, :], np.inf, dist)
            if not np.isfinite(masked).any():
                break
            i, j = np.unravel_index(np.argmin(masked), masked.shape)
            van_idx = int(free_van_idx[i])
            action[van_idx] = call_zone_idx[j]
            used_van[i] = True
            used_call[j] = True
        return action


if __name__ == "__main__":
    from datetime import date
    from src.env.forecast_service import ForecastService

    forecaster = ForecastService()
    env = DispatcherEnv(date=date(2026, 4, 30), n_vans=15, seed=42, forecaster=forecaster)
    agent = GreedyAgent(env)
    obs, _ = env.reset(seed=42)
    agent.reset(seed=42)
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, _, terminated, truncated, info = env.step(action)
    print(f"greedy: calls={info['n_total_calls']} sales={info['n_total_sales']}")
