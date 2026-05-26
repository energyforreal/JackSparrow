"""OI (Open Interest) feature engineering for JackSparrow v43."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

_EPS = 1e-9
_OI_ZSCORE_WINDOW: int = 48
_OI_CHANGE_WINDOW: int = 6

OI_FEATURE_NAMES: tuple[str, ...] = (
    "oi_zscore",
    "oi_change_6",
    "oi_price_divergence",
    "oi_acceleration",
    "oi_delta_z",
)


def _oi_features_on_primary(
    primary_df: pd.DataFrame,
    df_oi: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """Compute 4 OI-derived features aligned to ``primary_df`` (5m bars)."""
    n = len(primary_df)
    zero_df = pd.DataFrame(
        {
            "oi_zscore": np.zeros(n),
            "oi_change_6": np.zeros(n),
            "oi_price_divergence": np.zeros(n),
            "oi_acceleration": np.zeros(n),
            "oi_delta_z": np.zeros(n),
        },
        index=primary_df.index,
    )

    if df_oi is None or df_oi.empty or "oi_contracts" not in df_oi.columns:
        return zero_df

    try:
        prim_ts = pd.to_datetime(primary_df["timestamp"], utc=True)
        oi_copy = df_oi.copy()
        oi_copy["_ts"] = pd.to_datetime(oi_copy["timestamp"], utc=True)
        oi_sorted = oi_copy.sort_values("_ts")

        left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n)}).sort_values("ts")
        merged = pd.merge_asof(
            left,
            oi_sorted[["_ts", "oi_contracts"]],
            left_on="ts",
            right_on="_ts",
            direction="backward",
        ).sort_values("_ord")

        oi_series = merged["oi_contracts"].fillna(0.0).reset_index(drop=True)
    except Exception:
        return zero_df

    if oi_series.max() < _EPS:
        return zero_df

    oi = oi_series.values.astype(np.float64)
    oi_s = pd.Series(oi)
    w = _OI_ZSCORE_WINDOW
    oi_mu = oi_s.rolling(w, min_periods=max(2, w // 4)).mean()
    oi_std = oi_s.rolling(w, min_periods=max(2, w // 4)).std().clip(lower=_EPS)
    oi_zscore = ((oi_s - oi_mu) / oi_std).fillna(0.0).clip(-4.0, 4.0)

    h = _OI_CHANGE_WINDOW
    oi_lagged = oi_s.shift(h).bfill().fillna(oi_s)
    oi_change_6 = ((oi_s - oi_lagged) / (oi_lagged.abs() + _EPS)).fillna(0.0).clip(-0.05, 0.05)

    close = primary_df["close"].values.astype(np.float64)
    close_s = pd.Series(close)
    close_lagged = close_s.shift(h).bfill().fillna(close_s)
    ret_6 = ((close_s - close_lagged) / (close_lagged.abs() + _EPS)).fillna(0.0)

    oi_price_divergence = (
        np.sign(oi_change_6.values) * -np.sign(ret_6.values)
    ).astype(np.float32)
    oi_price_divergence = pd.Series(oi_price_divergence).fillna(0.0)
    oi_acceleration = oi_change_6.diff().fillna(0.0).clip(-0.02, 0.02)

    oi_delta_1 = oi_s.diff(1).fillna(0.0)
    oi_delta_mu = oi_delta_1.rolling(w, min_periods=max(2, w // 4)).mean()
    oi_delta_std = oi_delta_1.rolling(w, min_periods=max(2, w // 4)).std().clip(lower=_EPS)
    oi_delta_z = ((oi_delta_1 - oi_delta_mu) / oi_delta_std).fillna(0.0).clip(-4.0, 4.0)

    out = pd.DataFrame(
        {
            "oi_zscore": oi_zscore.values,
            "oi_change_6": oi_change_6.values,
            "oi_price_divergence": oi_price_divergence.values,
            "oi_acceleration": oi_acceleration.values,
            "oi_delta_z": oi_delta_z.values,
        },
        index=primary_df.index,
    )
    return out.replace([np.inf, -np.inf], 0.0).fillna(0.0)
