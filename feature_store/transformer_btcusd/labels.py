"""Forward-looking market labels for per-TF transformer training."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    PATH_LABEL_HORIZON_BARS,
    RETURN_COL,
    max_label_horizon_bars,
)


def compute_market_labels(
    df: pd.DataFrame,
    *,
    return_horizon_bars: int = 1,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    mae_floor_atr_mult: float,
) -> pd.DataFrame:
    """Compute single-bar return target and path/risk labels on native TF grid."""
    path_horizon = int(path_label_horizon_bars)
    ret_horizon = int(return_horizon_bars)
    max_horizon = max_label_horizon_bars(ret_horizon, path_horizon)

    out_df = df.copy()
    n = len(out_df)
    close = out_df["close"].values
    high = out_df["high"].values
    low = out_df["low"].values
    atr = out_df["atr"].values
    volume = out_df["volume"].values
    has_oi = "open_interest" in out_df.columns
    oi = out_df["open_interest"].values if has_oi else np.full(n, np.nan)

    path_cols = [
        "mfe",
        "mae",
        "future_volatility",
        "trend_strength",
        "drawdown_before_mfe",
        "future_oi_change_pct",
        "future_volume_change_pct",
    ]
    out: dict[str, np.ndarray] = {
        RETURN_COL: np.full(n, np.nan),
        **{c: np.full(n, np.nan) for c in path_cols},
    }

    for i in range(n - max_horizon):
        entry = close[i]

        if ret_horizon > 0 and i + ret_horizon < n:
            out[RETURN_COL][i] = (close[i + ret_horizon] - entry) / entry

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

        out["trend_strength"][i] = abs(fwd_close[-1] - entry) / (atr[i] + 1e-9)

        if has_oi and not np.isnan(oi[i]) and oi[i] != 0:
            out["future_oi_change_pct"][i] = (oi[i + path_horizon] - oi[i]) / (
                abs(oi[i]) + 1e-9
            )
        past_start = max(0, i - path_horizon)
        past_vol_mean = volume[past_start : i + 1].mean()
        out["future_volume_change_pct"][i] = (
            volume[i + 1 : i + path_horizon + 1].mean() - past_vol_mean
        ) / (past_vol_mean + 1e-9)

    for col, values in out.items():
        out_df[col] = values
    return out_df


def trim_label_tail(
    df: pd.DataFrame,
    *,
    return_horizon_bars: int = 1,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
) -> pd.DataFrame:
    """Drop rows without complete forward labels."""
    max_horizon = max_label_horizon_bars(return_horizon_bars, path_label_horizon_bars)
    return df.iloc[: -(max_horizon + 1)].reset_index(drop=True)


def active_training_label_cols() -> tuple[str, ...]:
    return CONTINUOUS_LABEL_COLS


def label_nan_summary(df: pd.DataFrame) -> Dict[str, float]:
    """Per-label NaN rates for notebook diagnostics."""
    cols = [c for c in CONTINUOUS_LABEL_COLS if c in df.columns]
    if not cols:
        return {}
    return df[cols].isna().mean().round(4).to_dict()
