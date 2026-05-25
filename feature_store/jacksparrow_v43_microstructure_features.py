"""Orderbook / funding microstructure features for JackSparrow v43."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

_EPS = 1e-9
_PRED_FR_ZSCORE_WINDOW: int = 24

MICROSTRUCTURE_FEATURE_NAMES: tuple[str, ...] = (
    "bid_ask_imbalance",
    "spread_bps",
    "funding_x_oi",
    "funding_predicted_zscore",
)


def _align_ticker_column(
    primary_df: pd.DataFrame,
    df_ticker: Optional[pd.DataFrame],
    col: str,
) -> pd.Series:
    n = len(primary_df)
    z = pd.Series(0.0, index=range(n))
    if df_ticker is None or df_ticker.empty or col not in df_ticker.columns:
        return z
    if "timestamp" not in primary_df.columns or "timestamp" not in df_ticker.columns:
        return z
    try:
        prim_ts = pd.to_datetime(primary_df["timestamp"], utc=True)
        aux = df_ticker.copy()
        aux["_ts"] = pd.to_datetime(aux["timestamp"], utc=True)
        aux_sorted = aux.sort_values("_ts")
        left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
        merged = pd.merge_asof(
            left,
            aux_sorted[["_ts", col]],
            left_on="ts",
            right_on="_ts",
            direction="backward",
        ).sort_values("_ord")
        return merged[col].fillna(0.0).reset_index(drop=True)
    except Exception:
        return z


def _microstructure_features_on_primary(
    primary_df: pd.DataFrame,
    df_ticker: Optional[pd.DataFrame],
    funding_zscore: pd.Series,
    oi_zscore: pd.Series,
) -> pd.DataFrame:
    """Compute microstructure features aligned to ``primary_df``."""
    n = len(primary_df)
    zero_df = pd.DataFrame(
        {
            "bid_ask_imbalance": np.zeros(n),
            "spread_bps": np.zeros(n),
            "funding_x_oi": np.zeros(n),
            "funding_predicted_zscore": np.zeros(n),
        },
        index=primary_df.index,
    )

    bid_size = _align_ticker_column(primary_df, df_ticker, "bid_size")
    ask_size = _align_ticker_column(primary_df, df_ticker, "ask_size")
    best_bid = _align_ticker_column(primary_df, df_ticker, "best_bid")
    best_ask = _align_ticker_column(primary_df, df_ticker, "best_ask")
    mark_price = _align_ticker_column(primary_df, df_ticker, "mark_price")
    pred_fr = _align_ticker_column(primary_df, df_ticker, "predicted_funding_rate")

    denom = bid_size + ask_size + _EPS
    imbalance = ((bid_size - ask_size) / denom).clip(-1.0, 1.0).fillna(0.0)

    mp = mark_price.replace(0, np.nan).fillna((best_bid + best_ask) / 2.0).replace(0, np.nan)
    spread = best_ask - best_bid
    spread_bps = ((spread / (mp + _EPS)) * 10000.0).fillna(0.0).clip(0.0, 500.0)

    fz = funding_zscore.reset_index(drop=True).fillna(0.0)
    oz = oi_zscore.reset_index(drop=True).fillna(0.0)
    funding_x_oi = (fz * oz).clip(-16.0, 16.0)

    fr_s = pd.Series(pred_fr.values)
    w = _PRED_FR_ZSCORE_WINDOW
    fr_mu = fr_s.rolling(w, min_periods=max(2, w // 4)).mean()
    fr_std = fr_s.rolling(w, min_periods=max(2, w // 4)).std().clip(lower=_EPS)
    funding_predicted_zscore = ((fr_s - fr_mu) / fr_std).fillna(0.0).clip(-4.0, 4.0)

    if fr_s.abs().max() < _EPS:
        funding_predicted_zscore = pd.Series(0.0, index=range(n))

    return pd.DataFrame(
        {
            "bid_ask_imbalance": imbalance.values,
            "spread_bps": spread_bps.values,
            "funding_x_oi": funding_x_oi.values,
            "funding_predicted_zscore": funding_predicted_zscore.values,
        },
        index=primary_df.index,
    ).replace([np.inf, -np.inf], 0.0).fillna(0.0)
