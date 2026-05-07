from __future__ import annotations

import torch  # noqa: F401  # torch before pandas on Windows

from datetime import date as date_t
from typing import Any, Callable

import h3
import numpy as np

from src.env.dispatcher_env import (
    DAY_START_HOUR,
    TIME_STEP_MINUTES,
    DispatcherEnv,
)

EARTH_R = 6_371_000.0
MEAN_SALE_VALUE_EUR = 14.0  # uit EDA: ~€31k / 2.219 sales
NEGLECTED_DEMAND_THRESHOLD = 5  # zone telt mee voor fairness als >= 5 demand events op de dag


def pct_calls_answered(info: dict) -> float:
    """% van demand-events dat als sale werd gerealiseerd. Calls = unanswered demand.

    Onder onze model-aanname: total_demand = sales + calls. % answered = sales / total.
    """
    sales = info.get("n_total_sales", 0)
    calls = info.get("n_total_calls", 0)
    total = sales + calls
    return 100.0 * sales / total if total else 0.0


def total_revenue_eur(info: dict) -> float:
    return info.get("n_total_sales", 0) * MEAN_SALE_VALUE_EUR


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1 = np.radians(lat1); p2 = np.radians(lat2)
    dl = np.radians(lng2 - lng1); dp = p2 - p1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


def total_distance_km(actions_history: list[np.ndarray], env: DispatcherEnv) -> float:
    """Som van haversine-afstanden per kar over alle zone-overgangen tijdens de dag."""
    if len(actions_history) < 2:
        return 0.0
    centroids = np.array([h3.cell_to_latlng(z) for z in env.zones], dtype="float64")
    A = np.stack(actions_history)  # (T, n_vans)
    total = 0.0
    for v in range(A.shape[1]):
        zones = A[:, v]
        for t in range(1, len(zones)):
            if zones[t] != zones[t - 1]:
                la1, lo1 = centroids[zones[t - 1]]
                la2, lo2 = centroids[zones[t]]
                total += _haversine_m(la1, lo1, la2, lo2)
    return total / 1000.0


def mean_response_min(env: DispatcherEnv, actions_history: list[np.ndarray]) -> float:
    """Gemiddeld aantal minuten tussen call-creatie en eerste van-aankomst in die zone.

    Calls die nooit een van zien tellen niet mee. NaN als geen enkele call beantwoord werd.
    """
    times: list[float] = []
    for c in env._sampled_calls:
        ct = c["time_min"]; cz = c["zone_idx"]
        for step, action in enumerate(actions_history):
            step_t = DAY_START_HOUR * 60 + step * TIME_STEP_MINUTES
            if step_t < ct:
                continue
            if (action == cz).any():
                times.append(step_t - ct)
                break
    return float(np.mean(times)) if times else float("nan")


def _gini(values: np.ndarray) -> float:
    """Gini coefficient over een lijst niet-negatieve waarden. 0 = perfect gelijk, ~1 = ongelijk."""
    x = np.sort(np.asarray(values, dtype="float64"))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    return (2.0 * np.sum((np.arange(1, n + 1)) * x) / (n * x.sum())) - (n + 1) / n


def fairness_gini(env: DispatcherEnv) -> float:
    """Gini coefficient van service-rate per demand-zone.

    Definitie: voor elke (zone, dag) met demand >= NEGLECTED_DEMAND_THRESHOLD,
    bereken service_rate = sales_in_zone / demand_in_zone. Gini = 0 betekent
    elke zone gekregen dezelfde fractie van zijn demand bediend; hogere Gini =
    sommige zones zwaar onderbedient.
    """
    sales_per_zone: dict[int, int] = {}
    demand_per_zone: dict[int, int] = {}
    for s in env._sampled_sales:
        z = s["zone_idx"]
        sales_per_zone[z] = sales_per_zone.get(z, 0) + 1
        demand_per_zone[z] = demand_per_zone.get(z, 0) + 1
    for c in env._sampled_calls:
        z = c["zone_idx"]
        demand_per_zone[z] = demand_per_zone.get(z, 0) + 1

    rates: list[float] = []
    for z, dem in demand_per_zone.items():
        if dem < NEGLECTED_DEMAND_THRESHOLD:
            continue
        rates.append(sales_per_zone.get(z, 0) / dem)
    if not rates:
        return 0.0
    return _gini(np.asarray(rates))


def neglected_zones_pct(env: DispatcherEnv) -> float:
    """% van demand-zones (>= NEGLECTED_DEMAND_THRESHOLD demand events) waar 0 sales gebeurden."""
    sales_per_zone: dict[int, int] = {}
    demand_per_zone: dict[int, int] = {}
    for s in env._sampled_sales:
        z = s["zone_idx"]
        sales_per_zone[z] = sales_per_zone.get(z, 0) + 1
        demand_per_zone[z] = demand_per_zone.get(z, 0) + 1
    for c in env._sampled_calls:
        z = c["zone_idx"]
        demand_per_zone[z] = demand_per_zone.get(z, 0) + 1
    qualifying = [z for z, d in demand_per_zone.items() if d >= NEGLECTED_DEMAND_THRESHOLD]
    if not qualifying:
        return 0.0
    neglected = sum(1 for z in qualifying if sales_per_zone.get(z, 0) == 0)
    return 100.0 * neglected / len(qualifying)


def evaluate_episode(agent_factory: Callable, env: DispatcherEnv,
                     target_date: date_t, seed: int, name: str
                     ) -> dict[str, Any]:
    """Run één episode en geef alle metrics terug als dict-row."""
    agent = agent_factory(env, target_date)
    obs, _ = env.reset(seed=seed, options={"date": target_date})
    agent.reset(seed=seed)
    actions_history: list[np.ndarray] = []
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    while not (terminated or truncated):
        action = agent.select_action(obs)
        actions_history.append(np.asarray(action, dtype=np.int64).copy())
        obs, _, terminated, truncated, info = env.step(action)
    return {
        "agent": name,
        "date": target_date.isoformat(),
        "seed": seed,
        "n_calls_unanswered": info["n_total_calls"],
        "n_sales_answered": info["n_total_sales"],
        "pct_answered": round(pct_calls_answered(info), 2),
        "revenue_eur": round(total_revenue_eur(info), 2),
        "distance_km": round(total_distance_km(actions_history, env), 2),
        "mean_response_min": round(mean_response_min(env, actions_history), 2),
        "fairness_gini": round(fairness_gini(env), 4),
        "neglected_zones_pct": round(neglected_zones_pct(env), 2),
    }
