from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("data/raw/foubertai_export")
PROCESSED_DIR = Path("data/processed")
DATES = ("2026-04-30", "2026-05-01", "2026-05-02")
EVENTS_PATH = PROCESSED_DIR / "events.parquet"


def _read_tsv(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", encoding="utf-8", **kwargs)


def _concat_per_day(filename: str, **read_kwargs) -> pd.DataFrame:
    frames = [_read_tsv(RAW_DIR / d / filename, **read_kwargs) for d in DATES]
    return pd.concat(frames, ignore_index=True)


def load_shifts() -> pd.DataFrame:
    df = _concat_per_day(
        "01_shifts.tsv",
        parse_dates=["wd_start", "wd_stop", "shift_start", "shift_stop"],
        dtype={
            "wd_id": "int64",
            "emp_hash": "string",
            "shift_id": "int64",
            "icecream_van_id": "int64",
            "area_id": "Int64",
            "icecream_van_zone_id": "Int64",
        },
    )
    df["icecream_van_zone_id"] = df["icecream_van_zone_id"].astype("category")
    df["area_id"] = df["area_id"].astype("category")
    return df


def load_sales() -> pd.DataFrame:
    df = _concat_per_day(
        "02_sales.tsv",
        parse_dates=["datetime_start", "datetime_stop"],
        dtype={
            "sale_id": "int64",
            "shift_id": "int64",
            "icecream_van_id": "int64",
            "latitude_start": "float64",
            "longitude_start": "float64",
            "latitude_stop": "float64",
            "longitude_stop": "float64",
            "total_price_vati": "float64",
            "total_price_vate": "float64",
            "vat_totals": "string",
        },
    )
    return df


def load_sale_orders() -> pd.DataFrame:
    df = _concat_per_day(
        "03_sale_orders.tsv",
        parse_dates=["datetime"],
        dtype={
            "sale_order_id": "int64",
            "sale_id": "int64",
            "icecream_van_id": "int64",
            "menu_item_id": "int64",
            "name": "string",
            "price_vati": "float64",
            "vat_rate": "float64",
        },
    )
    df["name"] = df["name"].astype("category")
    return df


def load_menu_items() -> pd.DataFrame:
    df = _concat_per_day(
        "04_menu_items.tsv",
        dtype={
            "id": "int64",
            "menu_id": "int64",
            "name": "string",
            "price_vati": "float64",
            "vat_rate": "float64",
        },
    )
    df = df.drop_duplicates(subset=["id"], keep="first").reset_index(drop=True)
    df["name"] = df["name"].astype("category")
    return df


def load_reservations() -> pd.DataFrame:
    df = _concat_per_day(
        "06_reservations.tsv",
        parse_dates=["datetime_start", "datetime_stop"],
        dtype={
            "reservation_id": "int64",
            "icecream_van_id": "Int64",
            "icecream_van_schedule_id": "Int64",
            "menu_id": "Int64",
            "status": "string",
            "address_zipcode": "Int64",
            "address_city": "string",
            "address_country": "string",
            "latitude": "float64",
            "longitude": "float64",
            "travel_expense": "float64",
            "minimum_consumption": "float64",
            "callout_charge": "float64",
            "allow_non_payment": "Int64",
            "payment_per_person": "Int64",
            "nr_of_people": "Int64",
            "reservation_type": "string",
        },
    )
    df["status"] = df["status"].astype("category")
    df["reservation_type"] = df["reservation_type"].astype("category")
    df["address_city"] = df["address_city"].astype("category")
    df["address_country"] = df["address_country"].astype("category")
    return df


_NR_OF_PEOPLE_RANGES = {
    "1-2": 1.5,
    "3-4": 3.5,
    "5-6": 5.5,
    "7-8": 7.5,
    "9-10": 9.5,
    "10+": 10.0,
}


def _parse_nr_of_people_range(value: object) -> float:
    if pd.isna(value):
        return np.nan
    return _NR_OF_PEOPLE_RANGES.get(str(value), np.nan)


def load_calls() -> pd.DataFrame:
    df = _concat_per_day(
        "07_calls.tsv",
        parse_dates=["deadline", "created_at", "updated_at"],
        dtype={
            "call_id": "int64",
            "shift_id": "Int64",
            "icecream_van_id": "Int64",
            "latitude": "float64",
            "longitude": "float64",
            "latitude_gps": "float64",
            "longitude_gps": "float64",
            "nr_of_people": "string",
            "address_zipcode": "string",
            "address_city": "string",
            "address_country": "string",
            "was_close": "Int64",
        },
    )
    df["address_zipcode"] = pd.to_numeric(df["address_zipcode"], errors="coerce").astype("Int64")
    df["address_city"] = df["address_city"].astype("category")
    df["address_country"] = df["address_country"].astype("category")
    df["nr_of_people_num"] = df["nr_of_people"].map(_parse_nr_of_people_range).astype("float64")
    df["answered"] = df["shift_id"].notna()
    return df


def load_vans() -> pd.DataFrame:
    df = _concat_per_day(
        "08_vans.tsv",
        dtype={
            "id": "int64",
            "nr": "int64",
            "color_text": "string",
            "color_background": "string",
        },
    )
    df = df.drop_duplicates(subset=["id"], keep="first").reset_index(drop=True)
    return df


def load_gps() -> pd.DataFrame:
    frames = []
    for d in DATES:
        for path in sorted((RAW_DIR / d / "gps").glob("van_*.tsv")):
            df = _read_tsv(
                path,
                parse_dates=["created_at"],
                dtype={
                    "id": "int64",
                    "icecream_van_id": "int64",
                    "latitude": "float64",
                    "longitude": "float64",
                    "velocity": "float64",
                },
            )
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _events_from_shifts(shifts: pd.DataFrame) -> pd.DataFrame:
    duration_h = (shifts["shift_stop"] - shifts["shift_start"]).dt.total_seconds() / 3600.0
    starts = pd.DataFrame({
        "timestamp": shifts["shift_start"],
        "zone": shifts["icecream_van_zone_id"].astype("string"),
        "event_type": "shift_start",
        "van_id": shifts["icecream_van_id"].astype("Int64"),
        "value": duration_h.astype("float64"),
    })
    stops = pd.DataFrame({
        "timestamp": shifts["shift_stop"],
        "zone": shifts["icecream_van_zone_id"].astype("string"),
        "event_type": "shift_stop",
        "van_id": shifts["icecream_van_id"].astype("Int64"),
        "value": pd.Series([np.nan] * len(shifts), dtype="float64"),
    })
    return pd.concat([starts, stops], ignore_index=True)


def _events_from_sales(sales: pd.DataFrame, shifts: pd.DataFrame) -> pd.DataFrame:
    # Join sales + shifts to attach zone
    joined = sales.merge(
        shifts[["shift_id", "icecream_van_zone_id"]],
        on="shift_id",
        how="left",
        validate="many_to_one",
    )
    return pd.DataFrame({
        "timestamp": joined["datetime_start"],
        "zone": joined["icecream_van_zone_id"].astype("string"),
        "event_type": "sale",
        "van_id": joined["icecream_van_id"].astype("Int64"),
        "value": joined["total_price_vati"].astype("float64"),
    })


def _events_from_sale_orders(
    sale_orders: pd.DataFrame, sales: pd.DataFrame, shifts: pd.DataFrame
) -> pd.DataFrame:
    # Join sale_orders -> sales -> shifts to attach zone
    sales_with_zone = sales.merge(
        shifts[["shift_id", "icecream_van_zone_id"]],
        on="shift_id",
        how="left",
        validate="many_to_one",
    )
    joined = sale_orders.merge(
        sales_with_zone[["sale_id", "icecream_van_zone_id"]],
        on="sale_id",
        how="left",
        validate="many_to_one",
    )
    return pd.DataFrame({
        "timestamp": joined["datetime"],
        "zone": joined["icecream_van_zone_id"].astype("string"),
        "event_type": "sale_order",
        "van_id": joined["icecream_van_id"].astype("Int64"),
        "value": joined["price_vati"].astype("float64"),
    })


def _events_from_reservations(reservations: pd.DataFrame) -> pd.DataFrame:
    starts = pd.DataFrame({
        "timestamp": reservations["datetime_start"],
        "zone": reservations["address_zipcode"].astype("string"),
        "event_type": "reservation_start",
        "van_id": reservations["icecream_van_id"].astype("Int64"),
        "value": reservations["nr_of_people"].astype("float64"),
    })
    stops = pd.DataFrame({
        "timestamp": reservations["datetime_stop"],
        "zone": reservations["address_zipcode"].astype("string"),
        "event_type": "reservation_stop",
        "van_id": reservations["icecream_van_id"].astype("Int64"),
        "value": pd.Series([np.nan] * len(reservations), dtype="float64"),
    })
    return pd.concat([starts, stops], ignore_index=True)


def _events_from_calls(calls: pd.DataFrame) -> pd.DataFrame:
    event_type = np.where(calls["answered"], "call_answered", "call_missed")
    return pd.DataFrame({
        "timestamp": calls["created_at"],
        "zone": calls["address_zipcode"].astype("string"),
        "event_type": pd.Series(event_type, dtype="string"),
        "van_id": calls["icecream_van_id"].astype("Int64"),
        "value": calls["nr_of_people_num"].astype("float64"),
    })


def build_master_dataframe() -> pd.DataFrame:
    shifts = load_shifts()
    sales = load_sales()
    sale_orders = load_sale_orders()
    reservations = load_reservations()
    calls = load_calls()

    events = pd.concat(
        [
            _events_from_shifts(shifts),
            _events_from_sales(sales, shifts),
            _events_from_sale_orders(sale_orders, sales, shifts),
            _events_from_reservations(reservations),
            _events_from_calls(calls),
        ],
        ignore_index=True,
    )

    events["event_type"] = events["event_type"].astype("category")
    events = events.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    return events[["timestamp", "zone", "event_type", "van_id", "value"]]


if __name__ == "__main__":
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    events = build_master_dataframe()
    events.to_parquet(EVENTS_PATH, index=False)
    print(f"Wrote {len(events):,} events to {EVENTS_PATH}")
