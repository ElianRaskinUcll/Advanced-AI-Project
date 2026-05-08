from __future__ import annotations

import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error

PROCESSED_DIR = Path("data/processed")
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / "xgb_v1.pkl"
FIGURES_DIR = Path("reports/figures")
SHAP_PATH = FIGURES_DIR / "shap_xgb_v1.png"

NUMERIC_FEATURES = [
    "hour", "temperature", "precipitation", "sunshine",
    "demand_lag_1", "demand_lag_2", "demand_rolling_3h",
    "zone_lat", "zone_lng",
]
N_TRIALS = 30
SEED = 42


def _prepare_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    X = df[NUMERIC_FEATURES].copy()
    dummies = pd.get_dummies(df["day_type"], prefix="day_type").astype("float64")
    X = pd.concat([X, dummies], axis=1)
    y = df["demand"].to_numpy(dtype="float64")
    return X, y


def _make_regressor(params: dict) -> xgb.XGBRegressor:
    base = {
        "objective": "reg:absoluteerror",
        "tree_method": "hist",
        "random_state": SEED,
        "n_jobs": -1,
        "verbosity": 0,
    }
    return xgb.XGBRegressor(**{**base, **params})


def _cross_validate(X: pd.DataFrame, y: np.ndarray, folds: np.ndarray, params: dict) -> tuple[np.ndarray, list[dict]]:
    """Leave-one-day-out CV. Returns OOF predictions and per-fold metrics."""
    oof = np.zeros_like(y, dtype="float64")
    per_fold: list[dict] = []
    for k in sorted(np.unique(folds)):
        train_mask = folds != k
        test_mask = folds == k
        model = _make_regressor(params)
        model.fit(X[train_mask], y[train_mask])
        pred = model.predict(X[test_mask])
        oof[test_mask] = pred
        per_fold.append({
            "fold": int(k),
            "n_test": int(test_mask.sum()),
            "mae": float(mean_absolute_error(y[test_mask], pred)),
            "rmse": float(np.sqrt(mean_squared_error(y[test_mask], pred))),
        })
    return oof, per_fold


def train(df: pd.DataFrame, n_trials: int = N_TRIALS) -> dict:
    """Tune XGBoost on leave-one-day-out CV, then train final model on all data."""
    X, y = _prepare_xy(df)
    folds = df["fold"].to_numpy()

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        }
        oof, _ = _cross_validate(X, y, folds, params)
        return float(mean_absolute_error(y, oof))

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=SEED),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_model = _make_regressor(study.best_params)
    best_model.fit(X, y)

    return {
        "model": best_model,
        "feature_names": list(X.columns),
        "best_params": study.best_params,
        "best_cv_mae": float(study.best_value),
        "study": study,
    }


def predict(artifact: dict, df: pd.DataFrame) -> np.ndarray:
    X, _ = _prepare_xy(df)
    X = X[artifact["feature_names"]]
    return artifact["model"].predict(X)


def evaluate_per_day(df: pd.DataFrame, oof: np.ndarray) -> pd.DataFrame:
    rows = []
    for k in sorted(df["fold"].unique()):
        mask = df["fold"] == k
        actual = df.loc[mask, "demand"].to_numpy(dtype="float64")
        pred = oof[mask.to_numpy()]
        rows.append({
            "fold": int(k),
            "date": str(df.loc[mask, "date"].iloc[0]),
            "n_test": int(mask.sum()),
            "mae": float(mean_absolute_error(actual, pred)),
            "rmse": float(np.sqrt(mean_squared_error(actual, pred))),
        })
    return pd.DataFrame(rows)


def evaluate_per_zone_bucket(df: pd.DataFrame, oof: np.ndarray) -> pd.DataFrame:
    """Bucket zones by total observed demand into low/mid/high (terciles)."""
    df = df.copy()
    df["pred"] = oof
    zone_demand = df.groupby("h3_cell")["demand"].sum()
    bucket = pd.qcut(zone_demand.rank(method="first"), q=3, labels=["low", "mid", "high"])
    df["zone_bucket"] = df["h3_cell"].map(bucket.to_dict())
    rows = []
    for b in ["low", "mid", "high"]:
        sub = df[df["zone_bucket"] == b]
        if sub.empty:
            continue
        rows.append({
            "bucket": b,
            "n_zones": int(sub["h3_cell"].nunique()),
            "n_rows": int(len(sub)),
            "total_demand": int(sub["demand"].sum()),
            "mae": float(mean_absolute_error(sub["demand"], sub["pred"])),
            "rmse": float(np.sqrt(mean_squared_error(sub["demand"], sub["pred"]))),
        })
    return pd.DataFrame(rows)


def plot_shap(model: xgb.XGBRegressor, X: pd.DataFrame, path: Path,
              sample_size: int = 5000, seed: int = SEED) -> None:
    sample = X if len(X) <= sample_size else X.sample(sample_size, random_state=seed)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)

    plt.figure(figsize=(8, 6))
    shap.summary_plot(shap_values, sample, show=False, plot_size=None)
    fig = plt.gcf()
    fig.suptitle("SHAP feature importance — xgb_v1", y=1.02)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def save_artifact(artifact: dict, results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": artifact["model"],
        "feature_names": artifact["feature_names"],
        "best_params": artifact["best_params"],
        "best_cv_mae": artifact["best_cv_mae"],
        "results": results,
    }
    with path.open("wb") as f:
        pickle.dump(payload, f)


if __name__ == "__main__":
    df = pd.read_parquet(FEATURES_PATH)
    print(f"Features loaded: {df.shape}")

    artifact = train(df, n_trials=N_TRIALS)
    print(f"Optuna best CV MAE: {artifact['best_cv_mae']:.4f}  params: {artifact['best_params']}")

    X, y = _prepare_xy(df)
    folds = df["fold"].to_numpy()
    oof, _ = _cross_validate(X, y, folds, artifact["best_params"])

    per_day = evaluate_per_day(df, oof)
    per_bucket = evaluate_per_zone_bucket(df, oof)

    print("\nMAE / RMSE per held-out day:")
    print(per_day.to_string(index=False))
    print("\nMAE / RMSE per zone bucket (terciles by total demand):")
    print(per_bucket.to_string(index=False))

    plot_shap(artifact["model"], X, SHAP_PATH)
    print(f"\nSHAP plot: {SHAP_PATH}")

    save_artifact(
        artifact,
        results={"per_day": per_day, "per_bucket": per_bucket},
        path=MODEL_PATH,
    )
    print(f"Model artifact: {MODEL_PATH}")
