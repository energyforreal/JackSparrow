"""Forward-looking market labels for per-TF transformer training."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    CANDLE_FAMILY_DOJI,
    CONTINUOUS_LABEL_COLS,
    FUTURE_CANDLE_COL,
    PATH_LABEL_HORIZON_BARS,
    STRUCTURE_OUTCOME_COL,
    max_label_horizon_bars,
)

_EPS = 1e-9
_STRUCTURE_OUTCOME_RANGE = 0
_STRUCTURE_OUTCOME_CONT_LONG = 1
_STRUCTURE_OUTCOME_CONT_SHORT = 2
_STRUCTURE_OUTCOME_BREAKOUT = 3
_STRUCTURE_OUTCOME_FAILED_BREAK = 4
_STRUCTURE_OUTCOME_REVERSAL = 5


def _sign_nonzero(value: float) -> float:
    if not np.isfinite(value) or abs(value) <= _EPS:
        return 0.0
    return 1.0 if value > 0.0 else -1.0


def _structure_outcome_id(
    *,
    bias_now: float,
    bias_end: float,
    mfe: float,
    mae: float,
    fwd_failed: np.ndarray,
    fwd_bars_since_breakout: np.ndarray,
) -> int:
    """Priority: failed break, breakout, reversal, continuation, else range."""
    if fwd_failed.size and np.any(fwd_failed >= 0.5):
        return _STRUCTURE_OUTCOME_FAILED_BREAK
    if fwd_bars_since_breakout.size and np.any(fwd_bars_since_breakout <= 0.5):
        return _STRUCTURE_OUTCOME_BREAKOUT
    s0 = _sign_nonzero(bias_now)
    s1 = _sign_nonzero(bias_end)
    if s0 != 0.0 and s1 != 0.0 and s0 != s1:
        return _STRUCTURE_OUTCOME_REVERSAL
    if bias_end > 0.0 and float(mfe) > float(mae):
        return _STRUCTURE_OUTCOME_CONT_LONG
    if bias_end < 0.0 and float(mae) > float(mfe):
        return _STRUCTURE_OUTCOME_CONT_SHORT
    return _STRUCTURE_OUTCOME_RANGE


def compute_market_labels(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    mae_floor_atr_mult: float,
) -> pd.DataFrame:
    """Compute path/risk and forward-pattern labels on the native TF grid."""
    path_horizon = int(path_label_horizon_bars)
    max_horizon = max_label_horizon_bars(path_horizon)

    out_df = df.copy()
    n = len(out_df)
    close = out_df["close"].values
    high = out_df["high"].values
    low = out_df["low"].values
    open_px = out_df["open"].values
    atr = out_df["atr"].values
    volume = out_df["volume"].values
    has_oi = "open_interest" in out_df.columns
    oi = out_df["open_interest"].values if has_oi else np.full(n, np.nan)
    bias = (
        out_df["structure_bias"].to_numpy(dtype=np.float64)
        if "structure_bias" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    failed = (
        out_df["failed_break"].to_numpy(dtype=np.float64)
        if "failed_break" in out_df.columns
        else np.zeros(n, dtype=np.float64)
    )
    bars_bo = (
        out_df["bars_since_breakout"].to_numpy(dtype=np.float64)
        if "bars_since_breakout" in out_df.columns
        else np.full(n, np.inf)
    )
    candle_ids = (
        out_df[CANDLE_CLASS_COL].to_numpy(dtype=np.int64)
        if CANDLE_CLASS_COL in out_df.columns
        else np.zeros(n, dtype=np.int64)
    )

    path_cols = list(CONTINUOUS_LABEL_COLS)
    out: dict[str, np.ndarray] = {c: np.full(n, np.nan) for c in path_cols}
    structure_ids = np.full(n, np.nan)
    future_candle = np.full(n, np.nan)

    for i in range(n - max_horizon):
        entry = close[i]
        atr_i = float(atr[i]) if np.isfinite(atr[i]) else _EPS
        atr_i = max(atr_i, _EPS)

        fwd_close = close[i + 1 : i + path_horizon + 1]
        fwd_high = high[i + 1 : i + path_horizon + 1]
        fwd_low = low[i + 1 : i + path_horizon + 1]

        fwd_rets = np.log(fwd_close / np.concatenate(([entry], fwd_close[:-1])))
        out["future_volatility"][i] = fwd_rets.std()

        favorable = (fwd_high - entry) / entry
        adverse = (entry - fwd_low) / entry
        mfe_idx = int(np.argmax(favorable))
        out["mfe"][i] = favorable[mfe_idx]
        out["mae"][i] = adverse[int(np.argmax(adverse))]

        if out["mfe"][i] >= mae_floor_atr_mult * atr[i] / entry:
            out["drawdown_before_mfe"][i] = (
                adverse[: mfe_idx + 1].max() if mfe_idx > 0 else 0.0
            )

        out["trend_strength"][i] = abs(fwd_close[-1] - entry) / (atr_i)

        if has_oi and not np.isnan(oi[i]) and oi[i] != 0:
            out["future_oi_change_pct"][i] = (oi[i + path_horizon] - oi[i]) / (
                abs(oi[i]) + _EPS
            )
        past_start = max(0, i - path_horizon)
        past_vol_mean = volume[past_start : i + 1].mean()
        out["future_volume_change_pct"][i] = (
            volume[i + 1 : i + path_horizon + 1].mean() - past_vol_mean
        ) / (past_vol_mean + _EPS)

        move_atr = (close[i + 1] - close[i]) / atr_i
        body = float(close[i] - open_px[i])
        cid = int(candle_ids[i])
        if cid in CANDLE_FAMILY_DOJI or abs(body) <= _EPS:
            out["candle_follow_through_atr"][i] = abs(move_atr)
        else:
            out["candle_follow_through_atr"][i] = float(np.sign(body)) * move_atr

        end = i + path_horizon
        out["structure_delta"][i] = float(bias[end] - bias[i])
        future_candle[i] = float(candle_ids[i + 1])
        structure_ids[i] = float(
            _structure_outcome_id(
                bias_now=float(bias[i]),
                bias_end=float(bias[end]),
                mfe=float(out["mfe"][i]),
                mae=float(out["mae"][i]),
                fwd_failed=failed[i + 1 : i + path_horizon + 1],
                fwd_bars_since_breakout=bars_bo[i + 1 : i + path_horizon + 1],
            )
        )

    for col, values in out.items():
        out_df[col] = values
    out_df[STRUCTURE_OUTCOME_COL] = structure_ids
    out_df[FUTURE_CANDLE_COL] = future_candle
    return out_df


def trim_label_tail(
    df: pd.DataFrame,
    *,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> pd.DataFrame:
    """Drop rows without complete forward labels."""
    max_horizon = max_label_horizon_bars(path_label_horizon_bars)
    return df.iloc[: -(max_horizon + 1)].reset_index(drop=True)


def active_training_label_cols() -> tuple[str, ...]:
    return CONTINUOUS_LABEL_COLS


def label_nan_summary(df: pd.DataFrame) -> Dict[str, float]:
    """Per-label NaN rates for notebook diagnostics."""
    cols = [c for c in CONTINUOUS_LABEL_COLS if c in df.columns]
    if not cols:
        return {}
    return df[cols].isna().mean().round(4).to_dict()
