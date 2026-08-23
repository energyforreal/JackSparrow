"""3-class BULL / NEUTRAL / BEAR labels for fused multi-horizon forecasts.

Labels live on the 5m decision clock. Features at t are causal. Targets use
close[t+k] only. No MFE/MAE path heads.
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


def compute_fusion_horizon_labels(df5m: pd.DataFrame) -> pd.DataFrame:
    """Label +10m/+30m/+1h/+2h position on the 5m grid.

    ``y_h`` at bar t uses ``close[t+k] - close[t]`` over ATR at t.
    The last ``MAX_FUSION_HORIZON_BARS`` rows are NaN (insufficient future).
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
    for col in FUSION_DIR_COLS:
        out[col] = np.nan
    max_k = int(MAX_FUSION_HORIZON_BARS)
    for i in range(n):
        if i + max_k >= n:
            break
        a = float(atr[i]) if np.isfinite(atr[i]) else 0.0
        for col, k in zip(FUSION_DIR_COLS, FUSION_HORIZON_BARS_5M):
            move = float(close[i + int(k)] - close[i])
            out.iat[i, out.columns.get_loc(col)] = float(three_class_direction(move, a))
    return out


def trim_fusion_label_tail(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the last 24 five-minute bars that cannot form a +2h label."""
    if len(df) <= int(MAX_FUSION_HORIZON_BARS):
        return df.iloc[0:0].copy()
    return df.iloc[: -int(MAX_FUSION_HORIZON_BARS)].reset_index(drop=True)


def fusion_label_matrix(df: pd.DataFrame) -> np.ndarray:
    """(n, 4) int64 labels aligned with FUSION_HORIZON_KEYS. NaN → -1."""
    cols = list(FUSION_DIR_COLS)
    arr = df.loc[:, cols].to_numpy(dtype=np.float64)
    out = np.full(arr.shape, -1, dtype=np.int64)
    finite = np.isfinite(arr)
    out[finite] = arr[finite].astype(np.int64)
    return out


def fusion_future_leak_cols() -> frozenset:
    """Columns that must never appear as model inputs."""
    return frozenset(FUSION_DIR_COLS)


def embargo_bars() -> int:
    return int(FUSION_EMBARGO_BARS)


def direction_name(class_id: int) -> str:
    return FUSION_DIRECTION_NAMES.get(int(class_id), "NEUTRAL")


def horizon_key_to_col() -> Dict[str, str]:
    return {key: f"{key}_dir" for key in FUSION_HORIZON_KEYS}


def label_class_mix(y: np.ndarray) -> Dict[str, Dict[str, int]]:
    """Per-horizon class counts for reports."""
    report: Dict[str, Dict[str, int]] = {}
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        col = y[:, j] if y.ndim == 2 else y
        counts = {name: 0 for name in FUSION_DIRECTION_NAMES.values()}
        for cid, name in FUSION_DIRECTION_NAMES.items():
            counts[name] = int(np.sum(col == int(cid)))
        report[key] = counts
    return report


def valid_label_mask(y: np.ndarray) -> np.ndarray:
    """True where every horizon label is in {0,1,2}."""
    if y.ndim == 1:
        return (y >= 0) & (y <= 2)
    return np.all((y >= 0) & (y <= 2), axis=1)


def split_hint() -> Tuple[int, int]:
    """(embargo_bars, max_horizon_bars) for purged splits."""
    return int(FUSION_EMBARGO_BARS), int(MAX_FUSION_HORIZON_BARS)
