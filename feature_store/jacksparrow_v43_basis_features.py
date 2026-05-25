"""Basis (mark vs spot) feature engineering for JackSparrow v43."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from agent.core.config import settings

_EPS = 1e-9
_BASIS_ZSCORE_WINDOW: int = 48
_BASIS_MOMENTUM_WINDOW: int = 6

BASIS_FEATURE_NAMES: tuple[str, ...] = (
    "basis",
    "basis_zscore",
    "basis_momentum",
)


def _align_series_to_primary(
    primary_df: pd.DataFrame,
    aux_df: Optional[pd.DataFrame],
    value_col: str,
) -> pd.Series:
    n = len(primary_df)
    z = pd.Series(0.0, index=range(n))
    if aux_df is None or aux_df.empty or value_col not in aux_df.columns:
        return z
    if "timestamp" not in primary_df.columns or "timestamp" not in aux_df.columns:
        return z
    try:
        prim_ts = pd.to_datetime(primary_df["timestamp"], utc=True)
        aux = aux_df.copy()
        aux["_ts"] = pd.to_datetime(aux["timestamp"], utc=True)
        aux_sorted = aux.sort_values("_ts")
        left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
        merged = pd.merge_asof(
            left,
            aux_sorted[["_ts", value_col]],
            left_on="ts",
            right_on="_ts",
            direction="backward",
        ).sort_values("_ord")
        return merged[value_col].fillna(0.0).reset_index(drop=True)
    except Exception:
        return z


def _basis_features_on_primary(
    primary_df: pd.DataFrame,
    df_mark: Optional[pd.DataFrame],
    df_ticker: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """Compute basis features aligned to ``primary_df`` (5m bars)."""
    n = len(primary_df)
    zero_df = pd.DataFrame(
        {
            "basis": np.zeros(n),
            "basis_zscore": np.zeros(n),
            "basis_momentum": np.zeros(n),
        },
        index=primary_df.index,
    )

    mark = _align_series_to_primary(primary_df, df_mark, "close")
    if mark.max() < _EPS and df_mark is not None and "close" in getattr(df_mark, "columns", []):
        mark = _align_series_to_primary(primary_df, df_mark, "close")

    spot = _align_series_to_primary(primary_df, df_ticker, "spot_price")
    if spot.max() < _EPS and "close" in primary_df.columns:
        spot = primary_df["close"].astype(float).reset_index(drop=True)

    if mark.max() < _EPS or spot.max() < _EPS:
        return zero_df

    basis = (mark - spot) / (spot.abs() + _EPS)
    basis = basis.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    w = int(getattr(settings, "jacksparrow_v43_basis_zscore_window", _BASIS_ZSCORE_WINDOW) or _BASIS_ZSCORE_WINDOW)
    b_s = pd.Series(basis.values)
    b_mu = b_s.rolling(w, min_periods=max(2, w // 4)).mean()
    b_std = b_s.rolling(w, min_periods=max(2, w // 4)).std().clip(lower=_EPS)
    basis_zscore = ((b_s - b_mu) / b_std).fillna(0.0).clip(-4.0, 4.0)

    h = _BASIS_MOMENTUM_WINDOW
    basis_lagged = b_s.shift(h).bfill().fillna(b_s)
    basis_momentum = (b_s - basis_lagged).fillna(0.0).clip(-0.05, 0.05)

    return pd.DataFrame(
        {
            "basis": basis.values,
            "basis_zscore": basis_zscore.values,
            "basis_momentum": basis_momentum.values,
        },
        index=primary_df.index,
    ).replace([np.inf, -np.inf], 0.0).fillna(0.0)
