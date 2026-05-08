"""Test that DispatcherEnv obeys the Gymnasium API contract.

Doel: gymnasium.utils.env_checker validates reset/step/spaces, plus we run a
short rollout to ensure no exceptions over a multi-step trajectory.
"""
import pytest

# Importing torch first avoids a pandas-vs-torch DLL conflict on Windows.
import torch  # noqa: F401

import numpy as np
from gymnasium.utils.env_checker import check_env

from src.env.dispatcher_env import DispatcherEnv
from src.env.forecast_service import ForecastService


@pytest.fixture(scope="module")
def env():
    """Shared env across tests; loading the forecaster is the slowest step."""
    forecaster = ForecastService()
    return DispatcherEnv(n_vans=3, seed=42, forecaster=forecaster)


def test_env_passes_gymnasium_checker(env):
    # check_env mutates state but our env reset is idempotent
    check_env(env, skip_render_check=True)


def test_random_rollout_advances_time(env):
    obs, info = env.reset(seed=0)
    assert obs.shape == env.observation_space.shape
    terminated = truncated = False
    n_steps = 0
    last_time = 0
    while not (terminated or truncated):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        assert info["time_min"] > last_time
        last_time = info["time_min"]
        n_steps += 1
    assert n_steps == 66, f"operating window 10:00-21:00 with 10-min step = 66 steps, got {n_steps}"


def test_action_validation(env):
    env.reset(seed=0)
    # Wrong shape
    with pytest.raises(ValueError, match="Action shape"):
        env.step(np.zeros(env.n_vans + 1, dtype=np.int64))
    # Out-of-range zone
    with pytest.raises(ValueError, match="zone index"):
        env.step(np.full(env.n_vans, env.n_zones, dtype=np.int64))
