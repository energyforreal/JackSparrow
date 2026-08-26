"""Fusion labels: 0.5 ATR dead zone internally, 2-class BEAR/BULL for training.

Labels live on the 5m decision clock. Features at t are causal. Targets use
close[t+k] only. No MFE/MAE path heads. NEUTRAL is ignore_index (-1), not a class.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FUSION_DIR_COLS,
    FUSION_DIRECTION_NAMES,
    FUSION_EMBARGO_BARS,
    FUSION_HORIZON_BARS_5M,
    FUSION_HORIZON_KEYS,
    FUSION_IGNORE_INDEX,
    FUSION_RETIRED_DIR_COLS,
    HORIZON_DIR_ATR_WEAK,
    MAX_FUSION_HORIZON_BARS,
)


def _ensure_time(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    elif "timestamp" in out.columns:
        ts = out["timestamp"]
        if pd.api.types.is_numeric_dtype(ts):
            out["time"] = pd.to_datetime(ts, unit="s", utc=True)
        else:
            out["time"] = pd.to_datetime(ts, utc=True)
    else:
        raise ValueError("Label frame requires time or timestamp")
    return out.sort_values("time").reset_index(drop=True)


def three_class_direction(move: float, atr: float) -> int:
    """Map ATR-normalized close-to-close move to BEAR/NEUTRAL/BULL (0/1/2)."""
    ratio = float(move) / max(float(atr), 1e-9)
    if ratio >= float(HORIZON_DIR_ATR_WEAK):
        return 2
    if ratio <= -float(HORIZON_DIR_ATR_WEAK):
        return 0
    return 1


def three_class_to_train_label(class_id: float) -> int:
    """Map internal 3-class id to 2-class train id. NEUTRAL/NaN → ignore_index."""
    if not np.isfinite(class_id):
        return int(FUSION_IGNORE_INDEX)
    cid = int(class_id)
    if cid == 0:
        return 0
    if cid == 2:
        return 1
    return int(FUSION_IGNORE_INDEX)


def compute_fusion_horizon_labels(df5m: pd.DataFrame) -> pd.DataFrame:
    """Label +30m/+1h/+2h position on the 5m grid (internal 3-class 0/1/2).

    ``y_h`` at bar t uses ``close[t+k] - close[t]`` over ATR at t.
    The last ``MAX_FUSION_HORIZON_BARS`` rows are NaN (insufficient future).
    Training maps NEUTRAL to ignore_index via ``fusion_label_matrix``.
    """
    out = _ensure_time(df5m)
    n = len(out)
    close = out["close"].to_numpy(dtype=np.float64)
    if "atr" in out.columns:
        atr = out["atr"].to_numpy(dtype=np.float64)
    else:
        prev = np.concatenate([[close[0]], close[:-1]])
        tr = np.maximum(
            out["high"].to_numpy(dtype=np.float64) - out["low"].to_numpy(dtype=np.float64),
            np.maximum(np.abs(out["high"].to_numpy() - prev), np.abs(out["low"].to_numpy() - prev)),
        )
        atr = pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy(dtype=np.float64)
    max_k = int(MAX_FUSION_HORIZON_BARS)
    n_valid = max(n - max_k, 0)
    atr_valid = atr[:n_valid].copy()
    atr_valid = np.where(np.isfinite(atr_valid), atr_valid, 0.0)
    denom = np.maximum(atr_valid, 1e-9)
    weak = float(HORIZON_DIR_ATR_WEAK)
    for col, k in zip(FUSION_DIR_COLS, FUSION_HORIZON_BARS_5M):
        labels = np.full(n, np.nan, dtype=np.float64)
        if n_valid > 0:
            move = close[int(k) : int(k) + n_valid] - close[:n_valid]
            ratio = move / denom
            cls = np.ones(n_valid, dtype=np.float64)
            cls[ratio >= weak] = 2.0
            cls[ratio <= -weak] = 0.0
            labels[:n_valid] = cls
        out[col] = labels
    return out


def trim_fusion_label_tail(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the last 24 five-minute bars that cannot form a +2h label."""
    if len(df) <= int(MAX_FUSION_HORIZON_BARS):
        return df.iloc[0:0].copy()
    return df.iloc[: -int(MAX_FUSION_HORIZON_BARS)].reset_index(drop=True)


def fusion_label_matrix(df: pd.DataFrame) -> np.ndarray:
    """(n, 3) int64 train labels: BEAR=0, BULL=1, NEUTRAL/NaN=-1."""
    cols = list(FUSION_DIR_COLS)
    arr = df.loc[:, cols].to_numpy(dtype=np.float64)
    out = np.full(arr.shape, int(FUSION_IGNORE_INDEX), dtype=np.int64)
    finite = np.isfinite(arr)
    mapped = np.full(arr.shape, int(FUSION_IGNORE_INDEX), dtype=np.int64)
    mapped[arr == 0] = 0
    mapped[arr == 2] = 1
    out[finite] = mapped[finite]
    return out


def fusion_future_leak_cols() -> frozenset:
    """Columns that must never appear as model inputs."""
    return frozenset(FUSION_DIR_COLS) | frozenset(FUSION_RETIRED_DIR_COLS)


def embargo_bars() -> int:
    return int(FUSION_EMBARGO_BARS)


def direction_name(class_id: int) -> str:
    cid = int(class_id)
    if cid < 0:
        return "IGNORED"
    return FUSION_DIRECTION_NAMES.get(cid, "IGNORED")


def horizon_key_to_col() -> Dict[str, str]:
    return {key: f"{key}_dir" for key in FUSION_HORIZON_KEYS}


def label_class_mix(y: np.ndarray) -> Dict[str, Dict[str, float]]:
    """Per-horizon 2-class counts plus ignore rate for reports."""
    report: Dict[str, Dict[str, float]] = {}
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        col = y[:, j] if y.ndim == 2 else y
        n = int(len(col))
        ignored = int(np.sum(col < 0))
        counts: Dict[str, float] = {
            "BEAR": float(np.sum(col == 0)),
            "BULL": float(np.sum(col == 1)),
            "IGNORED": float(ignored),
            "ignore_rate": float(ignored) / float(max(n, 1)),
        }
        report[key] = counts
    return report


def valid_label_mask(y: np.ndarray) -> np.ndarray:
    """True where at least one horizon is a 2-class BEAR/BULL label."""
    if y.ndim == 1:
        return (y == 0) | (y == 1)
    return np.any((y == 0) | (y == 1), axis=1)


def split_hint() -> Tuple[int, int]:
    """(embargo_bars, max_horizon_bars) for purged splits."""
    return int(FUSION_EMBARGO_BARS), int(MAX_FUSION_HORIZON_BARS)
