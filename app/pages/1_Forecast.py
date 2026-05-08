"""Tab 1 — Forecast: heatmap + tijdslider + model-toggle + zone-curve.

Predictions worden gegenereerd door de getrainde XGBoost-, Transformer- en naïeve
modellen op basis van de sidebar-parameters (dag-type, temperatuur, neerslag).
Caching via st.cache_resource (modellen) + st.cache_data (predictions) houdt
elke param-wissel onder de 2-seconden DoD.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch  # noqa: F401  # torch before pandas on Windows

import pickle

import h3  # noqa: F401
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from app.sidebar import inject_css, render_sidebar
from src.models.transformer_forecast import (
    MODEL_PATH as TX_PATH,
    TIMESTEP_FEATURES,
    TransformerForecast,
    _build_sequences_with_meta,
)
from src.models.xgb_forecast import (
    MODEL_PATH as XGB_PATH,
    _prepare_xy,
)

st.set_page_config(page_title="Forecast — Foubert", page_icon="📈", layout="wide")
inject_css()
params = render_sidebar()

DAG_TYPE_TO_FOLD = {"werkdag": 0, "feestdag": 1, "weekend": 2}
DAG_TYPE_TO_DAYTYPE = {"werkdag": "weekday", "feestdag": "holiday", "weekend": "weekend"}
PRECIP_WHEN_RAINING = 2.0  # mm/h, representatief voor matige regen


# ---------- Loaders (resource cache: één keer per session) ----------

@st.cache_resource
def load_xgb():
    with open(XGB_PATH, "rb") as f:
        return pickle.load(f)


@st.cache_resource
def load_tx():
    ckpt = torch.load(TX_PATH, weights_only=False)
    cfg = ckpt["config"]
    model = TransformerForecast(
        feature_dim=len(TIMESTEP_FEATURES),
        d_model=cfg["d_model"],
        n_heads=cfg["n_heads"],
        ff_dim=cfg["ff_dim"],
        n_layers=cfg["n_layers"],
        seq_len=cfg["seq_len"],
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return (
        model,
        np.asarray(ckpt["scaler_mean"], dtype="float64"),
        np.asarray(ckpt["scaler_scale"], dtype="float64"),
    )


@st.cache_resource
def load_features() -> pd.DataFrame:
    return pd.read_parquet("data/processed/features.parquet")


@st.cache_resource
def load_sequences():
    return _build_sequences_with_meta(load_features())


# ---------- Predictions (data cache: per param-tuple) ----------

@st.cache_data(show_spinner=False)
def predict_xgb(dag_type: str, temperature: float, neerslag: bool) -> pd.DataFrame:
    df = load_features().copy()
    fold = DAG_TYPE_TO_FOLD[dag_type]
    sub = df[df["fold"] == fold].copy()
    sub["temperature"] = float(temperature)
    sub["precipitation"] = PRECIP_WHEN_RAINING if neerslag else 0.0
    sub["day_type"] = pd.Categorical(
        [DAG_TYPE_TO_DAYTYPE[dag_type]] * len(sub),
        categories=["weekday", "weekend", "holiday"],
    )
    art = load_xgb()
    X, _ = _prepare_xy(sub)
    X = X[art["feature_names"]]
    sub["pred"] = np.maximum(art["model"].predict(X), 0.0)
    return sub[["h3_cell", "timestamp", "hour", "pred"]].reset_index(drop=True)


@st.cache_data(show_spinner=False)
def predict_transformer(dag_type: str, temperature: float, neerslag: bool) -> pd.DataFrame:
    X_all, _, folds, meta = load_sequences()
    model, mean, scale = load_tx()
    fold = DAG_TYPE_TO_FOLD[dag_type]
    mask = folds == fold
    X_day = X_all[mask].copy().astype("float32")
    meta_day = meta[mask].reset_index(drop=True).copy()

    # TIMESTEP_FEATURES order:
    # 0=hour, 1=temperature, 2=precipitation, 3=sunshine,
    # 4=zone_lat, 5=zone_lng, 6=demand,
    # 7=day_type_holiday, 8=day_type_weekday, 9=day_type_weekend
    X_day[:, :, 1] = float(temperature)
    X_day[:, :, 2] = PRECIP_WHEN_RAINING if neerslag else 0.0
    target_dt = DAG_TYPE_TO_DAYTYPE[dag_type]
    X_day[:, :, 7] = float(target_dt == "holiday")
    X_day[:, :, 8] = float(target_dt == "weekday")
    X_day[:, :, 9] = float(target_dt == "weekend")

    n, T, F = X_day.shape
    Xs = (X_day.reshape(-1, F) - mean) / scale
    Xs = Xs.reshape(n, T, F).astype("float32")
    with torch.no_grad():
        chunks = []
        for i in range(0, n, 2048):
            chunks.append(model(torch.from_numpy(Xs[i : i + 2048])).numpy())
    out = np.maximum(np.concatenate(chunks), 0.0)
    meta_day["pred"] = out
    meta_day["hour"] = pd.to_datetime(meta_day["timestamp"]).dt.hour
    return meta_day[["h3_cell", "timestamp", "hour", "pred"]].reset_index(drop=True)


@st.cache_data(show_spinner=False)
def predict_naive(dag_type: str) -> pd.DataFrame:
    df = load_features().copy()
    fold = DAG_TYPE_TO_FOLD[dag_type]
    sub = df[df["fold"] == fold].copy()
    sub["pred"] = sub["demand_lag_1"].astype("float64")
    return sub[["h3_cell", "timestamp", "hour", "pred"]].reset_index(drop=True)


def predict_for(model_name: str, dag_type: str, temperature: float, neerslag: bool) -> pd.DataFrame:
    if model_name == "XGBoost":
        return predict_xgb(dag_type, temperature, neerslag)
    if model_name == "Transformer":
        return predict_transformer(dag_type, temperature, neerslag)
    return predict_naive(dag_type)


# ---------- Map rendering ----------

def make_layer(hour_df: pd.DataFrame, vmax: float | None = None) -> pdk.Layer:
    df = hour_df.copy()
    if vmax is None:
        vmax = max(float(df["pred"].max()), 1e-6)
    norm = (df["pred"] / vmax).clip(0, 1)
    df["fill_r"] = (240 - 20 * norm).round().astype(int).clip(0, 255)
    df["fill_g"] = (240 - 200 * norm).round().astype(int).clip(0, 255)
    df["fill_b"] = (220 - 120 * norm).round().astype(int).clip(0, 255)
    df["fill_a"] = (60 + 195 * norm).round().astype(int).clip(0, 255)
    df["pred_str"] = df["pred"].round(2).astype(str)
    return pdk.Layer(
        "H3HexagonLayer",
        data=df.to_dict("records"),
        get_hexagon="h3_cell",
        get_fill_color="[fill_r, fill_g, fill_b, fill_a]",
        line_width_min_pixels=0,
        pickable=True,
        auto_highlight=True,
        extruded=False,
        opacity=0.85,
    )


def make_deck(layer: pdk.Layer) -> pdk.Deck:
    return pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=51.10, longitude=4.24, zoom=9.5, pitch=0),
        map_provider=None,  # no API key needed
        tooltip={"text": "Zone: {h3_cell}\nVoorspelde demand: {pred_str}"},
    )


# ---------- Page layout ----------

st.title("📈 Forecast")
st.caption(
    f"dag-type **{params['dag_type']}** · temperatuur **{params['temperatuur']}°C** · "
    f"neerslag **{'aan' if params['neerslag'] else 'uit'}** · klik in de sidebar "
    f"om parameters te wijzigen."
)

ctrl_left, ctrl_right = st.columns([3, 2])
with ctrl_left:
    model_choice = st.radio(
        "Model",
        ["XGBoost", "Transformer", "Naïef", "Vergelijking"],
        horizontal=True,
        key="model_choice",
        help="Vergelijking toont XGBoost en Transformer naast elkaar.",
    )
with ctrl_right:
    hour = st.slider("Uur (UTC)", min_value=8, max_value=22, value=13, key="hour_slider")

dag_type = params["dag_type"]
temperatuur = params["temperatuur"]
neerslag = params["neerslag"]


def slice_hour(df: pd.DataFrame, h: int) -> pd.DataFrame:
    return df[df["hour"] == h]


if model_choice == "Vergelijking":
    pred_xgb = predict_for("XGBoost", dag_type, temperatuur, neerslag)
    pred_tx = predict_for("Transformer", dag_type, temperatuur, neerslag)
    vmax = max(pred_xgb["pred"].max(), pred_tx["pred"].max(), 1e-6)
    cmap_l, cmap_r = st.columns(2, gap="small")
    with cmap_l:
        st.subheader("XGBoost")
        st.pydeck_chart(make_deck(make_layer(slice_hour(pred_xgb, hour), vmax=vmax)))
        st.metric("Σ demand bij uur", f"{slice_hour(pred_xgb, hour)['pred'].sum():.1f}")
    with cmap_r:
        st.subheader("Transformer")
        st.pydeck_chart(make_deck(make_layer(slice_hour(pred_tx, hour), vmax=vmax)))
        st.metric("Σ demand bij uur", f"{slice_hour(pred_tx, hour)['pred'].sum():.1f}")
else:
    pred_df = predict_for(model_choice, dag_type, temperatuur, neerslag)
    hour_df = slice_hour(pred_df, hour)
    st.pydeck_chart(make_deck(make_layer(hour_df)))
    m1, m2, m3 = st.columns(3)
    m1.metric("Σ demand bij uur", f"{hour_df['pred'].sum():.1f}")
    m2.metric("Aantal actieve zones", f"{(hour_df['pred'] > 0.05).sum()}")
    m3.metric("Hoogste cel-waarde", f"{hour_df['pred'].max():.2f}")

st.divider()
st.subheader("Vraag over de dag — gekozen zone")
st.caption(
    "Pydeck ondersteunt geen native click-event, dus selecteer hier expliciet "
    "een zone uit de top-30 (gerangschikt op piek-demand)."
)

if model_choice == "Vergelijking":
    top_zones = (
        pred_xgb.groupby("h3_cell")["pred"].max()
        .add(pred_tx.groupby("h3_cell")["pred"].max(), fill_value=0)
        .nlargest(30).index.tolist()
    )
else:
    top_zones = pred_df.groupby("h3_cell")["pred"].max().nlargest(30).index.tolist()

if top_zones:
    chosen = st.selectbox("Zone (top-30 op piek-demand)", top_zones, index=0)
    if model_choice == "Vergelijking":
        a = pred_xgb[pred_xgb.h3_cell == chosen][["hour", "pred"]].rename(columns={"pred": "XGBoost"})
        b = pred_tx[pred_tx.h3_cell == chosen][["hour", "pred"]].rename(columns={"pred": "Transformer"})
        merged = a.merge(b, on="hour", how="outer").set_index("hour").sort_index()
    else:
        merged = (
            pred_df[pred_df.h3_cell == chosen][["hour", "pred"]]
            .rename(columns={"pred": model_choice})
            .set_index("hour").sort_index()
        )
    st.line_chart(merged, height=260)
else:
    st.info("Geen zones met voorspelde demand voor deze parameters — pas de sidebar aan.")
