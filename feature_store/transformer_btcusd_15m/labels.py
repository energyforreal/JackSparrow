"""Forward-looking market labels used during Colab training (not needed at inference)."""

from __future__ import annotations

from typing import Dict, Mapping

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd_15m.contract import (
    CONTINUOUS_LABEL_COLS,
    HORIZON_KEY_TO_RETURN_COL,
    HORIZON_RETURN_COLS,
    PATH_LABEL_HORIZON_BARS,
    RETURN_HORIZON_BARS,
    max_label_horizon_bars,
)


def compute_market_labels(
    df: pd.DataFrame,
    *,
    return_horizon_bars: Mapping[str, int] | None = None,
    path_label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    mae_floor_atr_mult: float,
) -> pd.DataFrame:
    """Compute multi-horizon return targets and path/risk labels."""
    horizons = dict(return_horizon_bars or RETURN_HORIZON_BARS)
    path_horizon = int(path_label_horizon_bars)
    max_horizon = max_label_horizon_bars(horizons, path_horizon)

    out_df = df.copy()
    n = len(out_df)
    close = out_df["close"].values
    high = out_df["high"].values
    low = out_df["low"].values
    atr = out_df["atr"].values
    volume = out_df["volume"].values
    has_oi = "open_interest" in out_df.columns
    oi = out_df["open_interest"].values if has_oi else np.full(n, np.nan)

    return_cols = [
        HORIZON_KEY_TO_RETURN_COL[key]
        for key in horizons
        if key in HORIZON_KEY_TO_RETURN_COL
    ]
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
        c: np.full(n, np.nan) for c in return_cols + path_cols
    }

    for i in range(n - max_horizon):
        entry = close[i]

        for hkey, hbars in horizons.items():
            col = HORIZON_KEY_TO_RETURN_COL.get(hkey)
            if col is None or hbars <= 0 or i + hbars >= n:
                continue
            out[col][i] = (close[i + hbars] - entry) / entry

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
    return_horizon_bars: Mapping[str, int] | None = None,
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
