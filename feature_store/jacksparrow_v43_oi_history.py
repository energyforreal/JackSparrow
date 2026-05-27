"""Build v43 ticker/OI history frames from Delta ``OI:{symbol}`` candle pulls."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from agent.core.v43_oi_frames import TICKER_RING_COLUMNS


def oi_candles_to_ticker_frame(
    df_oi_candles: pd.DataFrame,
    *,
    df_mark: Optional[pd.DataFrame] = None,
    df_spot: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Convert ``OI:SYMBOL`` 5m candles (timestamp + close) to ``TICKER_RING_COLUMNS`` layout.

    ``close`` on OI candles is open-interest contracts. Optional ``df_mark`` / ``df_spot``
    (5m OHLCV with ``timestamp`` + ``close``) enrich ``mark_price`` / ``spot_price`` via
    as-of merge for basis-related microstructure inputs.
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

    return out[list(TICKER_RING_COLUMNS)].reset_index(drop=True)
