from __future__ import annotations

import torch  # noqa: F401  # torch before pandas on Windows

import pickle
from datetime import date as date_t
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.agents.greedy_agent import GreedyAgent
from src.env.dispatcher_env import DAY_END_HOUR, DAY_START_HOUR, DispatcherEnv

MODELS_DIR = Path("models")
Q_TABLE_PATH = MODELS_DIR / "q_table.pkl"
FIGURES_DIR = Path("reports/figures")
REWARD_CURVE_PATH = FIGURES_DIR / "q_learning_reward.png"

# State binning — chosen small so the Q-table is tabular in the literal sense.
HOUR_BINS = [DAY_START_HOUR, 13, 16, 19, DAY_END_HOUR + 1]   # -> 4 bins
N_HOUR_BINS = len(HOUR_BINS) - 1
OPEN_CALLS_BINS = [0, 5, 15, 1_000_000]                       # -> 3 bins
N_OPEN_CALLS_BINS = len(OPEN_CALLS_BINS) - 1
N_STATES = N_HOUR_BINS * N_OPEN_CALLS_BINS                    # 12 states

# Four macro-actions (high-level options). Q learns which option to deploy in
# each state. This is the only way tabular Q makes sense here: the raw env
# action space is MultiDiscrete([n_zones] * n_vans) = ~10^45, untabularizable.
MACRO_NAMES = ["stay", "greedy", "forecast_top", "random"]
N_MACROS = len(MACRO_NAMES)


def _discretize(env: DispatcherEnv) -> int:
    h = env._time_minutes // 60
    h_bin = int(np.clip(np.searchsorted(HOUR_BINS, h, side="right") - 1, 0, N_HOUR_BINS - 1))
    open_n = sum(
        1 for c in env._sampled_calls
        if env._time_minutes - c["time_min"] <= 30
    )
    o_bin = int(np.clip(np.searchsorted(OPEN_CALLS_BINS, open_n, side="right") - 1,
                        0, N_OPEN_CALLS_BINS - 1))
    return h_bin * N_OPEN_CALLS_BINS + o_bin


def _macro_stay(env: DispatcherEnv, helpers: dict) -> np.ndarray:
    return env._van_zones.copy()


def _macro_greedy(env: DispatcherEnv, helpers: dict) -> np.ndarray:
    return helpers["greedy"].select_action()


def _macro_forecast_top(env: DispatcherEnv, helpers: dict) -> np.ndarray:
    """Send each van to one of the top-N forecasted zones at the current hour."""
    h = env._time_minutes // 60
    rated = sorted(
        ((env._forecast.get((z, h), 0.0), idx) for idx, z in enumerate(env.zones)),
        reverse=True,
    )
    top = [idx for _, idx in rated[: env.n_vans]]
    if len(top) < env.n_vans:
        top = (top + [0] * env.n_vans)[: env.n_vans]
    return np.array(top, dtype=np.int64)


def _macro_random(env: DispatcherEnv, helpers: dict) -> np.ndarray:
    return env.action_space.sample()


MACROS = [_macro_stay, _macro_greedy, _macro_forecast_top, _macro_random]


class TabularQAgent:
    """Tabular Q-learning over hand-coded state bins and 4 macro-actions."""

    name = "q_learning"

    def __init__(self, env: DispatcherEnv, alpha: float = 0.3, gamma: float = 0.95):
        self.env = env
        self.alpha = alpha
        self.gamma = gamma
        self.q = np.zeros((N_STATES, N_MACROS), dtype=np.float64)
        self._helpers = {"greedy": _GreedyShim(env)}
        self._eps = 0.0  # set during training

    def reset(self, seed: int | None = None) -> None:
        self._eps = 0.0  # eval mode by default

    def select_action(self, obs: np.ndarray | None = None,
                      info: dict | None = None) -> np.ndarray:
        state = _discretize(self.env)
        if self._eps > 0 and np.random.random() < self._eps:
            macro_idx = int(np.random.randint(N_MACROS))
        else:
            macro_idx = int(np.argmax(self.q[state]))
        return MACROS[macro_idx](self.env, self._helpers)

    def train(self, dates: list[date_t], n_episodes: int = 60,
              eps_start: float = 1.0, eps_min: float = 0.05,
              eps_decay: float = 0.94, seed: int = 42) -> list[float]:
        rng = np.random.default_rng(seed)
        history: list[float] = []
        macro_counts = np.zeros(N_MACROS, dtype=np.int64)

        for ep in range(n_episodes):
            self._eps = max(eps_min, eps_start * (eps_decay ** ep))
            target_date = dates[ep % len(dates)]
            self.env.reset(seed=int(rng.integers(0, 1_000_000)),
                           options={"date": target_date})
            prev_sales = 0
            ep_reward = 0.0
            terminated = truncated = False
            while not (terminated or truncated):
                state = _discretize(self.env)
                if rng.random() < self._eps:
                    macro_idx = int(rng.integers(0, N_MACROS))
                else:
                    macro_idx = int(np.argmax(self.q[state]))
                macro_counts[macro_idx] += 1
                env_action = MACROS[macro_idx](self.env, self._helpers)
                _obs, _, term, trunc, info = self.env.step(env_action)
                terminated, truncated = term, trunc
                # Reward = sales added this step. Env reward is still 0.
                new_sales = info["n_total_sales"]
                reward = new_sales - prev_sales
                prev_sales = new_sales
                ep_reward += reward
                next_state = _discretize(self.env)
                td = reward + self.gamma * np.max(self.q[next_state]) - self.q[state, macro_idx]
                self.q[state, macro_idx] += self.alpha * td
            history.append(ep_reward)

        self._eps = 0.0
        self._macro_counts = macro_counts
        return history

    def save(self, path: Path = Q_TABLE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({
                "q": self.q,
                "alpha": self.alpha,
                "gamma": self.gamma,
                "macro_names": MACRO_NAMES,
                "n_states": N_STATES,
            }, f)

    @classmethod
    def load(cls, env: DispatcherEnv, path: Path = Q_TABLE_PATH) -> "TabularQAgent":
        with path.open("rb") as f:
            d = pickle.load(f)
        agent = cls(env, alpha=d["alpha"], gamma=d["gamma"])
        agent.q = d["q"]
        return agent


class _GreedyShim:
    """Thin wrapper so the greedy macro can call GreedyAgent.select_action()
    without rebuilding centroids on every step."""

    def __init__(self, env: DispatcherEnv):
        self._inner = GreedyAgent(env)

    def select_action(self) -> np.ndarray:
        return self._inner.select_action()


def plot_reward_curve(history: list[float], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(range(1, len(history) + 1), history, color="#1f77b4", marker="o", linewidth=1.5)
    # Rolling mean for trend
    window = max(1, len(history) // 10)
    if len(history) >= window * 2:
        rolling = np.convolve(history, np.ones(window) / window, mode="valid")
        ax.plot(range(window, window + len(rolling)), rolling,
                color="#d62728", linewidth=2, label=f"rolling mean (w={window})")
        ax.legend()
    ax.set_xlabel("Episode")
    ax.set_ylabel("Total reward (= sales)")
    ax.set_title("Tabular Q-learning — reward per episode")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def _evaluate(agent, env, target_date: date_t, seed: int = 42) -> dict:
    obs, _ = env.reset(seed=seed, options={"date": target_date})
    agent.reset(seed=seed)
    info = {"n_total_calls": 0, "n_total_sales": 0}
    terminated = truncated = False
    while not (terminated or truncated):
        action = agent.select_action(obs)
        obs, _, terminated, truncated, info = env.step(action)
    return info


if __name__ == "__main__":
    from src.agents.random_agent import RandomAgent
    from src.env.forecast_service import ForecastService

    train_dates = [date_t(2026, 4, 30), date_t(2026, 5, 1)]
    test_date = date_t(2026, 5, 2)

    print("Loading shared forecaster...")
    forecaster = ForecastService()
    env = DispatcherEnv(date=train_dates[0], n_vans=15, seed=42, forecaster=forecaster)

    agent = TabularQAgent(env)
    print(f"Training Q-agent: {N_STATES} states x {N_MACROS} macros, "
          f"on {train_dates}, test on {test_date}")
    history = agent.train(dates=train_dates, n_episodes=60)
    agent.save()
    plot_reward_curve(history, REWARD_CURVE_PATH)

    print(f"Q-table:\n{agent.q.round(2)}")
    print(f"macro picks during training: "
          f"{dict(zip(MACRO_NAMES, agent._macro_counts.tolist()))}")

    # Evaluate on test day
    q_info = _evaluate(agent, env, test_date, seed=999)
    rand_info = _evaluate(RandomAgent(env), env, test_date, seed=999)
    print(f"\nTest day {test_date}:")
    print(f"  Q-agent : sales={q_info['n_total_sales']:4d}  calls={q_info['n_total_calls']:4d}")
    print(f"  Random  : sales={rand_info['n_total_sales']:4d}  calls={rand_info['n_total_calls']:4d}")
    delta = q_info["n_total_sales"] - rand_info["n_total_sales"]
    print(f"  Q vs random sales delta: {delta:+d} "
          f"({'PASS' if delta > 0 else 'FAIL'} DoD)")
