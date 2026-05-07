from __future__ import annotations

from datetime import date
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from src.data.load import load_calls, load_sales

PROCESSED_DIR = Path("data/processed")
CONTEXT_PATH = PROCESSED_DIR / "context.parquet"
FEATURES_PATH = PROCESSED_DIR / "features.parquet"

H3_RESOLUTION = 9
DATES = [date(2026, 4, 30), date(2026, 5, 1), date(2026, 5, 2)]
DATE_TO_FOLD = {d: i for i, d in enumerate(DATES)}


def _assign_h3(lats: pd.Series, lngs: pd.Series, resolution: int = H3_RESOLUTION) -> list:
    cells = []
    for lat, lng in zip(lats, lngs):
        if pd.isna(lat) or pd.isna(lng):
            cells.append(None)
        else:
            cells.append(h3.latlng_to_cell(float(lat), float(lng), resolution))
    return cells


def _aggregate_demand(sales: pd.DataFrame, calls: pd.DataFrame) -> pd.DataFrame:
    """Count sales and calls per (h3_cell, hourly timestamp). Calls without
    coordinates and sales without start coords are dropped."""
    sales_df = pd.DataFrame({
        "h3_cell": _assign_h3(sales["latitude_start"], sales["longitude_start"]),
        "timestamp": sales["datetime_start"].dt.floor("h"),
    }).dropna(subset=["h3_cell"])
    n_sales = sales_df.groupby(["h3_cell", "timestamp"]).size().rename("n_sales")

    calls_df = pd.DataFrame({
        "h3_cell": _assign_h3(calls["latitude"], calls["longitude"]),
        "timestamp": calls["created_at"].dt.floor("h"),
    }).dropna(subset=["h3_cell"])
    n_calls = calls_df.groupby(["h3_cell", "timestamp"]).size().rename("n_calls")

    demand = pd.concat([n_sales, n_calls], axis=1).fillna(0).astype("int64")
    demand["demand"] = demand["n_sales"] + demand["n_calls"]
    return demand.reset_index()


def _build_grid(zones: list[str], hourly: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.MultiIndex.from_product(
        [zones, hourly], names=["h3_cell", "timestamp"]
    ).to_frame(index=False)


def build_features() -> pd.DataFrame:
    """Build the (zone, hour) feature matrix for forecasting.

    Returns one row per (h3_cell, hourly timestamp) covering every cell where
    a sale or call happened in the data window. Lag/rolling features use only
    strictly past demand values (no leakage of the current row's target).
    """
    sales = load_sales()
    calls = load_calls()
    context = pd.read_parquet(CONTEXT_PATH)

    demand = _aggregate_demand(sales, calls)
    zones = sorted(demand["h3_cell"].unique())
    hourly = pd.date_range(
        start=pd.Timestamp(DATES[0]),
        end=pd.Timestamp(DATES[-1]) + pd.Timedelta(hours=23),
        freq="h",
    )

    df = _build_grid(zones, hourly).merge(demand, on=["h3_cell", "timestamp"], how="left")
    df["n_sales"] = df["n_sales"].fillna(0).astype("int64")
    df["n_calls"] = df["n_calls"].fillna(0).astype("int64")
    df["demand"] = df["demand"].fillna(0).astype("int64")

    df["hour"] = df["timestamp"].dt.hour.astype("int64")
    df["date"] = df["timestamp"].dt.date
    df["fold"] = df["date"].map(DATE_TO_FOLD).astype("int64")

    ctx = context.copy()
    ctx["timestamp"] = ctx["timestamp"].dt.floor("h")
    df = df.merge(
        ctx[["timestamp", "temperature", "precipitation", "sunshine", "day_type"]],
        on="timestamp", how="left",
    )

    df = df.sort_values(["h3_cell", "timestamp"]).reset_index(drop=True)
    grouped = df.groupby("h3_cell", sort=False)["demand"]
    df["demand_lag_1"] = grouped.shift(1).fillna(0).astype("int64")
    df["demand_lag_2"] = grouped.shift(2).fillna(0).astype("int64")
    # Rolling mean over [t-3, t-1]: rolling on the lag-1 column ensures the
    # current hour is never included in its own predictor.
    df["demand_rolling_3h"] = (
        df.groupby("h3_cell", sort=False)["demand_lag_1"]
        .transform(lambda s: s.rolling(3, min_periods=1).mean())
        .fillna(0)
        .astype("float64")
    )

    centroids = {c: h3.cell_to_latlng(c) for c in zones}
    df["zone_lat"] = df["h3_cell"].map(lambda c: centroids[c][0]).astype("float64")
    df["zone_lng"] = df["h3_cell"].map(lambda c: centroids[c][1]).astype("float64")

    cols = [
        "h3_cell", "timestamp", "date", "fold",
        "hour", "day_type",
        "temperature", "precipitation", "sunshine",
        "demand_lag_1", "demand_lag_2", "demand_rolling_3h",
        "zone_lat", "zone_lng",
        "n_sales", "n_calls", "demand",
    ]
    return df[cols]


def leave_one_day_out_splits(df: pd.DataFrame):
    """Yield (train_idx, test_idx) pairs for leave-one-day-out CV.

    The fold column maps each date to a fixed integer; for fold k the test set
    is the rows of that day and the training set is everything else.
    """
    for k in sorted(df["fold"].unique()):
        test_idx = df.index[df["fold"] == k]
        train_idx = df.index[df["fold"] != k]
        yield train_idx, test_idx


if __name__ == "__main__":
    df = build_features()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(FEATURES_PATH, index=False)
    print(
        f"Wrote {len(df):,} rows x {len(df.columns)} cols to {FEATURES_PATH} | "
        f"zones={df['h3_cell'].nunique()} hours={df['timestamp'].nunique()} | "
        f"demand: total={df['demand'].sum()} nonzero_rows={int((df['demand']>0).sum())}"
    )
