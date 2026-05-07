"""Unit-tests voor src/eval/metrics.py — geen env-runs, alleen pure functies."""
import math

import numpy as np

from src.eval.metrics import (
    MEAN_SALE_VALUE_EUR,
    _gini,
    _haversine_m,
    pct_calls_answered,
    total_revenue_eur,
)


def test_pct_calls_answered_basic():
    assert pct_calls_answered({"n_total_sales": 0, "n_total_calls": 0}) == 0.0
    assert pct_calls_answered({"n_total_sales": 50, "n_total_calls": 50}) == 50.0
    assert pct_calls_answered({"n_total_sales": 100, "n_total_calls": 0}) == 100.0


def test_total_revenue_uses_mean_sale_value():
    assert total_revenue_eur({"n_total_sales": 10}) == 10 * MEAN_SALE_VALUE_EUR
    assert total_revenue_eur({"n_total_sales": 0}) == 0.0


def test_haversine_known_distance():
    """Bornem -> Antwerpen-centrum is roughly 25 km in a straight line."""
    bornem = (51.10, 4.24)
    antwerpen = (51.22, 4.40)
    d = _haversine_m(*bornem, *antwerpen)
    assert 15_000 < d < 30_000, f"unexpected distance {d:.0f} m"
    # Same point -> 0
    assert _haversine_m(51.0, 4.0, 51.0, 4.0) < 1e-6


def test_gini_perfect_equality_is_zero():
    assert _gini(np.array([1.0, 1.0, 1.0, 1.0])) == 0.0


def test_gini_perfect_inequality_approaches_one():
    # All wealth in one bucket -> gini -> (n-1)/n
    g = _gini(np.array([0.0, 0.0, 0.0, 10.0]))
    assert math.isclose(g, 0.75, rel_tol=1e-6)


def test_gini_handles_empty_or_zero():
    assert _gini(np.array([])) == 0.0
    assert _gini(np.array([0.0, 0.0])) == 0.0
