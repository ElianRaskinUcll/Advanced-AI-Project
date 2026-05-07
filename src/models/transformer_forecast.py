from __future__ import annotations

# IMPORTANT: torch must be imported BEFORE pandas on Windows. Importing pandas
# first causes "WinError 1114: DLL initialization routine failed" when torch
# loads its native libs because of a vendored-library conflict (likely MKL).
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

import math
import pickle
from copy import deepcopy
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

PROCESSED_DIR = Path("data/processed")
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / "transformer_v1.pt"
FIGURES_DIR = Path("reports/figures")
LOSS_PATH = FIGURES_DIR / "transformer_loss_curves.png"
ATTN_PATH = FIGURES_DIR / "transformer_attention.png"

SEED = 42
SEQ_LEN = 6
D_MODEL = 32
N_HEADS = 4
FF_DIM = 64
N_LAYERS = 2
LR = 1e-3
BATCH_SIZE = 256
MAX_EPOCHS = 50
PATIENCE = 5
VAL_FRACTION = 0.1

TIMESTEP_FEATURES = [
    "hour", "temperature", "precipitation", "sunshine",
    "zone_lat", "zone_lng", "demand",
    "day_type_holiday", "day_type_weekday", "day_type_weekend",
]


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 32):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2, dtype=torch.float32) *
                             (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1)]


class EncoderLayer(nn.Module):
    """Custom encoder layer that can return per-head attention weights."""

    def __init__(self, d_model: int, n_heads: int, ff_dim: int, dropout: float = 0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, ff_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(ff_dim, d_model),
            nn.Dropout(dropout),
        )
        self.ln2 = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor, return_attn: bool = False):
        a, w = self.attn(x, x, x, need_weights=return_attn, average_attn_weights=False)
        x = self.ln1(x + a)
        x = self.ln2(x + self.ff(x))
        return (x, w) if return_attn else x


class TransformerForecast(nn.Module):
    def __init__(self, feature_dim: int, d_model: int = D_MODEL, n_heads: int = N_HEADS,
                 ff_dim: int = FF_DIM, n_layers: int = N_LAYERS, seq_len: int = SEQ_LEN):
        super().__init__()
        self.input_proj = nn.Linear(feature_dim, d_model)
        self.pos_enc = PositionalEncoding(d_model, max_len=seq_len)
        self.layers = nn.ModuleList([
            EncoderLayer(d_model, n_heads, ff_dim) for _ in range(n_layers)
        ])
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor, return_attn: bool = False):
        x = self.input_proj(x)
        x = self.pos_enc(x)
        attns = []
        for layer in self.layers:
            if return_attn:
                x, w = layer(x, return_attn=True)
                attns.append(w)
            else:
                x = layer(x)
        out = self.head(x[:, -1, :]).squeeze(-1)
        return (out, attns) if return_attn else out


def build_sequences(df: pd.DataFrame, seq_len: int = SEQ_LEN
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each (zone, t) with t >= seq_len, build input window [t-seq_len, t-1]
    and label demand[t]. Returns (X, y, fold_of_label).
    """
    df = df.copy()
    dummies = pd.get_dummies(df["day_type"], prefix="day_type").astype("float32")
    for col in ["day_type_holiday", "day_type_weekday", "day_type_weekend"]:
        df[col] = dummies[col] if col in dummies.columns else 0.0
    df = df.sort_values(["h3_cell", "timestamp"]).reset_index(drop=True)

    X_chunks: list[np.ndarray] = []
    y_chunks: list[np.ndarray] = []
    fold_chunks: list[np.ndarray] = []
    feat_cols = TIMESTEP_FEATURES
    for _, g in df.groupby("h3_cell", sort=False):
        if len(g) < seq_len + 1:
            continue
        feat = g[feat_cols].to_numpy(dtype="float32")
        y_all = g["demand"].to_numpy(dtype="float32")
        f_all = g["fold"].to_numpy(dtype="int64")
        # Sliding windows via stride tricks: (n_windows, seq_len, n_feats)
        n_windows = len(g) - seq_len
        windows = np.lib.stride_tricks.sliding_window_view(feat, (seq_len, feat.shape[1]))[:, 0, :, :]
        X_chunks.append(windows[:n_windows])
        y_chunks.append(y_all[seq_len:seq_len + n_windows])
        fold_chunks.append(f_all[seq_len:seq_len + n_windows])
    X = np.concatenate(X_chunks, axis=0)
    y = np.concatenate(y_chunks, axis=0)
    folds = np.concatenate(fold_chunks, axis=0)
    return X, y, folds


def _scale(X_train: np.ndarray, X_others: list[np.ndarray]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Fit StandardScaler on training timesteps, apply to all arrays. Each array is (N, T, F)."""
    n_train, T, F = X_train.shape
    flat = X_train.reshape(-1, F)
    scaler = StandardScaler().fit(flat)
    X_train_s = scaler.transform(flat).reshape(n_train, T, F).astype("float32")
    others_s = []
    for X in X_others:
        n, _, _ = X.shape
        Xs = scaler.transform(X.reshape(-1, F)).reshape(n, T, F).astype("float32")
        others_s.append(Xs)
    return X_train_s, others_s


def _to_loader(X: np.ndarray, y: np.ndarray, batch_size: int, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(y))
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle)


def train_one_fold(X_train: np.ndarray, y_train: np.ndarray,
                   X_val: np.ndarray, y_val: np.ndarray,
                   feature_dim: int, max_epochs: int = MAX_EPOCHS,
                   patience: int = PATIENCE, lr: float = LR, seed: int = SEED
                   ) -> tuple[TransformerForecast, dict]:
    torch.manual_seed(seed)
    model = TransformerForecast(feature_dim=feature_dim)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    train_loader = _to_loader(X_train, y_train, BATCH_SIZE, shuffle=True)
    val_loader = _to_loader(X_val, y_val, BATCH_SIZE, shuffle=False)

    history: dict[str, list[float]] = {"train_loss": [], "val_loss": [], "val_mae": []}
    best_mae = float("inf")
    best_state = None
    bad_epochs = 0

    for epoch in range(max_epochs):
        model.train()
        train_loss = 0.0
        n = 0
        for xb, yb in train_loader:
            opt.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()
            bs = xb.size(0)
            train_loss += loss.item() * bs
            n += bs
        train_loss /= n

        model.eval()
        val_preds, val_targets, vsum, vn = [], [], 0.0, 0
        with torch.no_grad():
            for xb, yb in val_loader:
                pred = model(xb)
                loss = loss_fn(pred, yb)
                bs = xb.size(0)
                vsum += loss.item() * bs
                vn += bs
                val_preds.append(pred.numpy())
                val_targets.append(yb.numpy())
        val_loss = vsum / vn
        val_pred = np.concatenate(val_preds)
        val_targ = np.concatenate(val_targets)
        val_mae = float(np.mean(np.abs(val_pred - val_targ)))

        history["train_loss"].append(float(train_loss))
        history["val_loss"].append(float(val_loss))
        history["val_mae"].append(val_mae)

        if val_mae < best_mae - 1e-6:
            best_mae = val_mae
            best_state = deepcopy(model.state_dict())
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    history["best_val_mae"] = best_mae
    history["epochs_run"] = len(history["train_loss"])
    return model, history


def cross_validate(X: np.ndarray, y: np.ndarray, folds: np.ndarray,
                   seed: int = SEED) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Leave-one-day-out: for each fold k, train on others, predict on k.
    Returns OOF predictions, per-fold metrics, per-fold training histories.
    """
    rng = np.random.default_rng(seed)
    oof = np.full_like(y, np.nan, dtype="float32")
    metrics: list[dict] = []
    histories: list[dict] = []
    for k in sorted(np.unique(folds)):
        train_mask = folds != k
        test_mask = folds == k

        X_tr_full = X[train_mask]
        y_tr_full = y[train_mask]
        # Carve out val set for early stopping (random within train)
        n_tr = len(X_tr_full)
        idx = rng.permutation(n_tr)
        n_val = int(n_tr * VAL_FRACTION)
        val_idx, tr_idx = idx[:n_val], idx[n_val:]
        X_tr, y_tr = X_tr_full[tr_idx], y_tr_full[tr_idx]
        X_val, y_val = X_tr_full[val_idx], y_tr_full[val_idx]
        X_te, y_te = X[test_mask], y[test_mask]

        X_tr_s, (X_val_s, X_te_s) = _scale(X_tr, [X_val, X_te])

        model, hist = train_one_fold(
            X_tr_s, y_tr, X_val_s, y_val, feature_dim=X.shape[2], seed=seed,
        )
        model.eval()
        with torch.no_grad():
            preds = []
            for xb, _ in _to_loader(X_te_s, y_te, BATCH_SIZE, shuffle=False):
                preds.append(model(xb).numpy())
            te_pred = np.concatenate(preds)
        oof[test_mask] = te_pred
        metrics.append({
            "fold": int(k),
            "n_test": int(test_mask.sum()),
            "mae": float(mean_absolute_error(y_te, te_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_te, te_pred))),
            "epochs_run": int(hist["epochs_run"]),
            "best_val_mae": float(hist["best_val_mae"]),
        })
        histories.append(hist)
    return oof, metrics, histories


def evaluate_per_zone_bucket(df: pd.DataFrame, sequences_idx: pd.DataFrame,
                             oof: np.ndarray) -> pd.DataFrame:
    """Buckets zones by total observed demand. sequences_idx must have h3_cell + demand of label hour."""
    seq_df = sequences_idx.copy()
    seq_df["pred"] = oof
    zone_demand = df.groupby("h3_cell")["demand"].sum()
    bucket = pd.qcut(zone_demand.rank(method="first"), q=3, labels=["low", "mid", "high"])
    seq_df["zone_bucket"] = seq_df["h3_cell"].map(bucket.to_dict())
    rows = []
    for b in ["low", "mid", "high"]:
        sub = seq_df[seq_df["zone_bucket"] == b]
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


def plot_loss_curves(histories: list[dict], path: Path) -> None:
    n = len(histories)
    fig, axes = plt.subplots(1, n, figsize=(4.5 * n, 4), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, hist, k in zip(axes, histories, range(n)):
        epochs = range(1, len(hist["train_loss"]) + 1)
        ax.plot(epochs, hist["train_loss"], label="train MSE", color="#1f77b4")
        ax.plot(epochs, hist["val_loss"], label="val MSE", color="#ff7f0e")
        ax.plot(epochs, hist["val_mae"], label="val MAE", color="#2ca02c", linestyle="--")
        ax.set_title(f"fold {k}")
        ax.set_xlabel("epoch"); ax.grid(True, alpha=0.3)
        if k == 0:
            ax.set_ylabel("loss")
        ax.legend(fontsize=8)
    fig.suptitle("Training/validation loss per fold")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_attention(model: TransformerForecast, X_sample: np.ndarray, path: Path) -> None:
    model.eval()
    with torch.no_grad():
        x = torch.from_numpy(X_sample[:1])  # (1, T, F)
        _, attns = model(x, return_attn=True)
    # attns: list[n_layers] of (1, n_heads, T, T)
    n_layers = len(attns)
    n_heads = attns[0].shape[1]
    fig, axes = plt.subplots(n_layers, n_heads, figsize=(2.5 * n_heads, 2.5 * n_layers), squeeze=False)
    for li, w in enumerate(attns):
        w_np = w[0].numpy()  # (heads, T, T)
        for hi in range(n_heads):
            ax = axes[li][hi]
            im = ax.imshow(w_np[hi], cmap="viridis", vmin=0, vmax=w_np.max())
            ax.set_title(f"L{li+1} H{hi+1}", fontsize=9)
            ax.set_xticks(range(SEQ_LEN), [f"t-{SEQ_LEN-i}" for i in range(SEQ_LEN)], fontsize=7)
            ax.set_yticks(range(SEQ_LEN), [f"t-{SEQ_LEN-i}" for i in range(SEQ_LEN)], fontsize=7)
    fig.suptitle("Attention weights — first sequence in test set")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def predict(model: TransformerForecast, X: np.ndarray, scaler: StandardScaler) -> np.ndarray:
    n, T, F = X.shape
    Xs = scaler.transform(X.reshape(-1, F)).reshape(n, T, F).astype("float32")
    model.eval()
    out = []
    with torch.no_grad():
        for xb, _ in _to_loader(Xs, np.zeros(n, dtype="float32"), BATCH_SIZE, shuffle=False):
            out.append(model(xb).numpy())
    return np.concatenate(out)


def save_artifact(model: TransformerForecast, scaler: StandardScaler,
                  metrics_df: pd.DataFrame, bucket_df: pd.DataFrame,
                  histories: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": model.state_dict(),
        "scaler_mean": scaler.mean_,
        "scaler_scale": scaler.scale_,
        "feature_names": TIMESTEP_FEATURES,
        "config": {
            "seq_len": SEQ_LEN, "d_model": D_MODEL, "n_heads": N_HEADS,
            "ff_dim": FF_DIM, "n_layers": N_LAYERS,
        },
        "results": {
            "per_day": metrics_df.to_dict(orient="records"),
            "per_bucket": bucket_df.to_dict(orient="records"),
            "histories": histories,
        },
    }, path)


def _build_sequences_with_meta(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """Same as build_sequences but also returns a DataFrame with h3_cell + label timestamp + label demand."""
    df = df.copy()
    dummies = pd.get_dummies(df["day_type"], prefix="day_type").astype("float32")
    for col in ["day_type_holiday", "day_type_weekday", "day_type_weekend"]:
        df[col] = dummies[col] if col in dummies.columns else 0.0
    df = df.sort_values(["h3_cell", "timestamp"]).reset_index(drop=True)

    X_chunks, y_chunks, fold_chunks, meta_chunks = [], [], [], []
    for cell, g in df.groupby("h3_cell", sort=False):
        if len(g) < SEQ_LEN + 1:
            continue
        feat = g[TIMESTEP_FEATURES].to_numpy(dtype="float32")
        y_all = g["demand"].to_numpy(dtype="float32")
        f_all = g["fold"].to_numpy(dtype="int64")
        ts_all = g["timestamp"].to_numpy()
        n_windows = len(g) - SEQ_LEN
        windows = np.lib.stride_tricks.sliding_window_view(feat, (SEQ_LEN, feat.shape[1]))[:, 0, :, :]
        X_chunks.append(windows[:n_windows])
        y_chunks.append(y_all[SEQ_LEN:SEQ_LEN + n_windows])
        fold_chunks.append(f_all[SEQ_LEN:SEQ_LEN + n_windows])
        meta_chunks.append(pd.DataFrame({
            "h3_cell": cell,
            "timestamp": ts_all[SEQ_LEN:SEQ_LEN + n_windows],
            "demand": y_all[SEQ_LEN:SEQ_LEN + n_windows],
            "fold": f_all[SEQ_LEN:SEQ_LEN + n_windows],
        }))
    X = np.concatenate(X_chunks, axis=0)
    y = np.concatenate(y_chunks, axis=0)
    folds = np.concatenate(fold_chunks, axis=0)
    meta = pd.concat(meta_chunks, ignore_index=True)
    return X, y, folds, meta


if __name__ == "__main__":
    df = pd.read_parquet(FEATURES_PATH)
    print(f"Features: {df.shape}")

    X, y, folds, meta = _build_sequences_with_meta(df)
    print(f"Sequences: {X.shape}  labels: {y.shape}  folds: {dict(zip(*np.unique(folds, return_counts=True)))}")

    oof, metrics, histories = cross_validate(X, y, folds)
    metrics_df = pd.DataFrame(metrics)
    date_map = {0: "2026-04-30", 1: "2026-05-01", 2: "2026-05-02"}
    metrics_df["date"] = metrics_df["fold"].map(date_map)
    print("\nMAE / RMSE per held-out day:")
    print(metrics_df[["fold", "date", "n_test", "epochs_run", "mae", "rmse"]].to_string(index=False))

    bucket_df = evaluate_per_zone_bucket(df, meta, oof)
    print("\nMAE / RMSE per zone bucket:")
    print(bucket_df.to_string(index=False))

    plot_loss_curves(histories, LOSS_PATH)
    print(f"\nLoss curves: {LOSS_PATH}")

    # Train final model on ALL sequences (no held-out fold) for the saved artifact + attention plot
    rng = np.random.default_rng(SEED)
    n_total = len(X)
    perm = rng.permutation(n_total)
    n_val = int(n_total * VAL_FRACTION)
    val_idx, tr_idx = perm[:n_val], perm[n_val:]
    X_tr, y_tr = X[tr_idx], y[tr_idx]
    X_val_, y_val_ = X[val_idx], y[val_idx]
    X_tr_s, (X_val_s,) = _scale(X_tr, [X_val_])
    final_model, _ = train_one_fold(
        X_tr_s, y_tr, X_val_s, y_val_, feature_dim=X.shape[2], seed=SEED,
    )

    flat = X_tr.reshape(-1, X.shape[2])
    final_scaler = StandardScaler().fit(flat)

    sample_idx = int(np.argmax(meta["demand"].to_numpy() > 0))
    X_sample = X[sample_idx:sample_idx + 1]
    X_sample_s = final_scaler.transform(X_sample.reshape(-1, X.shape[2])).reshape(1, SEQ_LEN, X.shape[2]).astype("float32")
    plot_attention(final_model, X_sample_s, ATTN_PATH)
    print(f"Attention plot: {ATTN_PATH}")

    save_artifact(final_model, final_scaler, metrics_df, bucket_df, histories, MODEL_PATH)
    print(f"Model artifact: {MODEL_PATH}")
