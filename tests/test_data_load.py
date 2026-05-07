"""Smoke-tests voor de data-loaders.

Verifieert dat elk van de 8 loaders draait, niet-leeg is, de verwachte
sleutelkolommen heeft, en de juiste totaal-counts uit de README oplevert
(detecteert per-ongeluk-droppen-van-rows of schema-shifts).
"""
import pandas as pd
import pytest

from src.data.load import (
    load_calls,
    load_gps,
    load_menu_items,
    load_reservations,
    load_sales,
    load_sale_orders,
    load_shifts,
    load_vans,
)


def test_load_shifts_has_expected_columns():
    df = load_shifts()
    assert len(df) == 88, f"expected 88 shift rows (29+30+29), got {len(df)}"
    assert {"shift_id", "icecream_van_id", "shift_start", "shift_stop"}.issubset(df.columns)
    assert pd.api.types.is_datetime64_any_dtype(df["shift_start"])


def test_load_sales_total_matches_readme():
    df = load_sales()
    assert len(df) == 2219, f"expected 2219 sales (616+996+607), got {len(df)}"
    assert df["total_price_vati"].sum() > 0


def test_load_calls_has_answered_flag():
    df = load_calls()
    assert len(df) == 1766, f"expected 1766 calls (363+968+435), got {len(df)}"
    assert "answered" in df.columns
    # answered = shift_id is not NA. README cites ~67% miss-rate overall.
    miss_rate = 1 - df["answered"].mean()
    assert 0.5 < miss_rate < 0.8, f"miss rate {miss_rate:.2f} outside expected band"


def test_load_gps_has_velocity():
    df = load_gps()
    assert len(df) > 600_000, f"GPS should have >600k rows, got {len(df)}"
    assert {"icecream_van_id", "latitude", "longitude", "velocity", "created_at"}.issubset(df.columns)
    assert df["velocity"].min() >= 0


@pytest.mark.parametrize("loader,min_rows", [
    (load_sale_orders, 7000),
    (load_menu_items, 1),
    (load_reservations, 30),
    (load_vans, 10),
])
def test_other_loaders_smoke(loader, min_rows):
    df = loader()
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= min_rows
