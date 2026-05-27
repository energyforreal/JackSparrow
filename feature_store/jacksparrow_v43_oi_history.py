"""Build v43 ticker/OI history frames from Delta ``OI:{symbol}`` candle pulls."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from agent.core.v43_oi_frames import TICKER_RING_COLUMNS


def align_ticker_frame_to_primary(
    primary_df: pd.DataFrame,
    df_ticker: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """Align ticker/OI rows to primary 5m ``timestamp`` via merge_asof (backward)."""
    empty = pd.DataFrame(columns=list(TICKER_RING_COLUMNS))
    if df_ticker is None or df_ticker.empty:
        return empty
    if "timestamp" not in primary_df.columns or "timestamp" not in df_ticker.columns:
        return empty

    n = len(primary_df)
    prim_ts = pd.to_datetime(primary_df["timestamp"], utc=True)
    aux = df_ticker.copy()
    aux["_ts"] = pd.to_datetime(aux["timestamp"], utc=True)
    aux = aux.sort_values("_ts").drop_duplicates(subset=["_ts"], keep="last")

    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
    cols = [c for c in TICKER_RING_COLUMNS if c in aux.columns and c != "timestamp"]
    if not cols:
        return empty

    merged = pd.merge_asof(
        left,
        aux[["_ts"] + cols],
        left_on="ts",
        right_on="_ts",
        direction="backward",
    ).sort_values("_ord")

    out = pd.DataFrame({"timestamp": prim_ts.values})
    for col in cols:
        out[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0).values
    for col in TICKER_RING_COLUMNS:
        if col not in out.columns:
            out[col] = 0.5 if col == "taker_buy_ratio" else 0.0
    return out[list(TICKER_RING_COLUMNS)]


def oi_candles_to_ticker_frame(
    df_oi_candles: pd.DataFrame,
    *,
    df_mark: Optional[pd.DataFrame] = None,
    df_spot: Optional[pd.DataFrame] = None,
    align_to: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Convert ``OI:SYMBOL`` 5m candles (timestamp + close) to ``TICKER_RING_COLUMNS`` layout.

    ``close`` on OI candles is open-interest contracts. Optional ``df_mark`` / ``df_spot``
    (5m OHLCV with ``timestamp`` + ``close``) enrich ``mark_price`` / ``spot_price`` via
    as-of merge. When ``align_to`` is set (primary 5m OHLCV), output rows match its timestamps.
    """
    empty = pd.DataFrame(columns=list(TICKER_RING_COLUMNS))
    if df_oi_candles is None or df_oi_candles.empty:
        return empty

    work = df_oi_candles.copy()
    if "timestamp" not in work.columns:
        if "time" in work.columns:
            work["timestamp"] = pd.to_datetime(work["time"], unit="s", utc=True)
        else:
            return empty
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    oi_col = "oi_contracts"
    if oi_col not in work.columns:
        if "close" in work.columns:
            work[oi_col] = pd.to_numeric(work["close"], errors="coerce")
        else:
            return empty

    out = pd.DataFrame(
        {
            "timestamp": work["timestamp"],
            "oi_contracts": pd.to_numeric(work[oi_col], errors="coerce").fillna(0.0),
            "oi_value_usd": (
                pd.to_numeric(work["oi_value_usd"], errors="coerce").fillna(0.0)
                if "oi_value_usd" in work.columns
                else 0.0
            ),
            "taker_buy_ratio": 0.5,
            "mark_price": 0.0,
            "spot_price": 0.0,
            "best_bid": 0.0,
            "best_ask": 0.0,
            "bid_size": 0.0,
            "ask_size": 0.0,
            "price_band_upper": 0.0,
            "price_band_lower": 0.0,
            "predicted_funding_rate": 0.0,
        }
    )

    def _asof_price(aux: Optional[pd.DataFrame], value_col: str, target: str) -> None:
        if aux is None or aux.empty or "timestamp" not in aux.columns:
            return
        if value_col not in aux.columns and "close" not in aux.columns:
            return
        src = aux.copy()
        src["timestamp"] = pd.to_datetime(src["timestamp"], utc=True)
        src = src.sort_values("timestamp")
        col = value_col if value_col in src.columns else "close"
        left = out[["timestamp"]].sort_values("timestamp")
        merged = pd.merge_asof(
            left,
            src[["timestamp", col]].rename(columns={"timestamp": "_ts", col: target}),
            left_on="timestamp",
            right_on="_ts",
            direction="backward",
        )
        out[target] = merged[target].fillna(0.0).values

    _asof_price(df_mark, "close", "mark_price")
    _asof_price(df_spot, "close", "spot_price")
    if float(out["spot_price"].max()) < 1e-9 and df_mark is not None:
        _asof_price(df_mark, "close", "spot_price")

    out = out[list(TICKER_RING_COLUMNS)].reset_index(drop=True)
    if align_to is not None and not align_to.empty and "timestamp" in align_to.columns:
        return align_ticker_frame_to_primary(align_to, out)
    return out


def oi_feature_matrix_diagnostics(df_feat: pd.DataFrame) -> dict[str, float]:
    """Std dev of OI feature columns (0 => likely alignment failure)."""
    oi_cols = (
        "oi_zscore",
        "oi_change_6",
        "oi_price_divergence",
        "oi_acceleration",
        "oi_delta_z",
    )
    diag: dict[str, float] = {}
    for col in oi_cols:
        if col not in df_feat.columns:
            diag[f"{col}_std"] = 0.0
            continue
        s = pd.to_numeric(df_feat[col], errors="coerce").fillna(0.0)
        diag[f"{col}_std"] = float(s.std())
    return diag
