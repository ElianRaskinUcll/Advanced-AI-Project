from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BORNEM_LAT = 51.10
BORNEM_LNG = 4.24
START_DATE = "2026-04-30"
END_DATE = "2026-05-02"

PROCESSED_DIR = Path("data/processed")
CONTEXT_PATH = PROCESSED_DIR / "context.parquet"
FIGURES_DIR = Path("reports/figures")
PLOT_PATH = FIGURES_DIR / "context_temperature.png"

# Belgian public holidays for 2026 (covers any later expansion of the data window).
BELGIAN_HOLIDAYS = {
    date(2026, 1, 1),    # Nieuwjaar
    date(2026, 4, 6),    # Paasmaandag (Pasen 5/4/2026)
    date(2026, 5, 1),    # Dag van de Arbeid
    date(2026, 5, 14),   # O.L.H. Hemelvaart
    date(2026, 5, 25),   # Pinkstermaandag
    date(2026, 7, 21),   # Nationale feestdag
    date(2026, 8, 15),   # O.L.V. Hemelvaart
    date(2026, 11, 1),   # Allerheiligen
    date(2026, 11, 11),  # Wapenstilstand
    date(2026, 12, 25),  # Kerstmis
}


def fetch_weather(
    start: str = START_DATE,
    end: str = END_DATE,
    lat: float = BORNEM_LAT,
    lng: float = BORNEM_LNG,
) -> pd.DataFrame:
    """Fetch hourly temperature, precipitation and sunshine from Open-Meteo.

    Returns a DataFrame with columns timestamp, temperature, precipitation,
    sunshine. Timestamps are naive UTC, aligned with the dataset's event
    timestamps. Sunshine is in seconds per hour (0-3600).
    """
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lng,
        "start_date": start,
        "end_date": end,
        "hourly": "temperature_2m,precipitation,sunshine_duration",
        "timezone": "UTC",
    })
    url = f"https://archive-api.open-meteo.com/v1/archive?{params}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read())
    h = payload["hourly"]
    return pd.DataFrame({
        "timestamp": pd.to_datetime(h["time"]),
        "temperature": pd.Series(h["temperature_2m"], dtype="float64"),
        "precipitation": pd.Series(h["precipitation"], dtype="float64"),
        "sunshine": pd.Series(h["sunshine_duration"], dtype="float64"),
    })


def add_day_type(df: pd.DataFrame) -> pd.DataFrame:
    """Add a categorical day_type column: holiday > weekend > weekday."""
    out = df.copy()
    d = out["timestamp"].dt.date
    is_holiday = d.isin(BELGIAN_HOLIDAYS)
    is_weekend = out["timestamp"].dt.dayofweek >= 5
    out["day_type"] = pd.Categorical(
        np.where(is_holiday, "holiday",
                 np.where(is_weekend, "weekend", "weekday")),
        categories=["weekday", "weekend", "holiday"],
    )
    return out


def build_context() -> pd.DataFrame:
    df = fetch_weather()
    df = add_day_type(df)
    return df[["timestamp", "temperature", "precipitation", "sunshine", "day_type"]]


def write_outputs(df: pd.DataFrame) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CONTEXT_PATH, index=False)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df["timestamp"], df["temperature"], color="#cc3333")
    ax.set_xlabel("Tijd (UTC)")
    ax.set_ylabel("Temperatuur (°C)")
    ax.set_title("Temperatuur Bornem-regio, 30 apr — 2 mei 2026")
    ax.grid(True, alpha=0.3)
    for d in pd.to_datetime(["2026-05-01", "2026-05-02"]):
        ax.axvline(d, color="grey", linestyle=":", linewidth=0.8)
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    df = build_context()
    write_outputs(df)
    nan_count = int(df.isna().sum().sum())
    print(
        f"Context rows: {len(df)} | NaNs: {nan_count} | "
        f"day_type counts: {dict(df['day_type'].value_counts())} | "
        f"temp range: {df['temperature'].min():.1f}-{df['temperature'].max():.1f}°C"
    )
