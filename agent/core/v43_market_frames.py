"""Fetch multi-timeframe OHLCV + funding DataFrames for JackSparrow v43."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import structlog

from agent.data.candle_validation import dataframe_from_delta_candles, validate_candles
from agent.core.config import settings

logger = structlog.get_logger()


def _normalize_delta_candles(raw: List[dict[str, Any]]) -> List[dict[str, Any]]:
    """Normalize Delta ``history/candles`` rows to candle_validation format."""
    out: List[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        ts = c.get("time")
        if ts is None:
            continue
        out.append(
            {
                "timestamp": ts,
                "open": float(c.get("open", 0) or 0),
                "high": float(c.get("high", 0) or 0),
                "low": float(c.get("low", 0) or 0),
                "close": float(c.get("close", 0) or 0),
                "volume": float(c.get("volume", 0) or 0),
            }
        )
    return out


def _parse_candles_response(resp: Any) -> List[dict[str, Any]]:
    candles: List[dict[str, Any]] = []
    if isinstance(resp, dict):
        result = resp.get("result")
        if isinstance(result, dict):
            candles = result.get("candles", []) or []
        elif isinstance(result, list):
            candles = result
    elif isinstance(resp, list):
        candles = resp
    return _normalize_delta_candles([c for c in candles if isinstance(c, dict)])


async def _fetch_ohlcv_df(
    delta_client: Any,
    symbol: str,
    resolution: str,
    bar_seconds: int,
    n_candles: int,
) -> pd.DataFrame:
    """Fetch last ``n_candles`` bars ending now."""
    from datetime import datetime, timezone

    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - int(n_candles * bar_seconds * 1.05)
    resp = await delta_client.get_candles(
        symbol=symbol,
        resolution=resolution,
        start=start_ts,
        end=end_ts,
    )
    formatted = _parse_candles_response(resp)
    return dataframe_from_delta_candles(formatted)


async def fetch_v43_market_frames(
    delta_client: Any,
    symbol: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load 5m / 15m / 1h OHLCV and hourly funding-like series for ``fe.transform``.

    Args:
        delta_client: ``DeltaExchangeClient`` with ``get_candles``.
        symbol: Underlying (e.g. ``BTCUSD``).

    Returns:
        Tuple ``(df5m, df15m, df1h, df_funding)``. Funding uses ``FUNDING:{symbol}``
        at ``1h`` when available; otherwise zeros aligned to ``df1h`` index.
    """
    n5 = int(getattr(settings, "jacksparrow_v43_candles_5m", 600) or 600)
    n15 = int(getattr(settings, "jacksparrow_v43_candles_15m", 400) or 400)
    n1h = int(getattr(settings, "jacksparrow_v43_candles_1h", 300) or 300)

    df5m = await _fetch_ohlcv_df(delta_client, symbol, "5m", 300, n5)
    df15m = await _fetch_ohlcv_df(delta_client, symbol, "15m", 900, n15)
    df1h = await _fetch_ohlcv_df(delta_client, symbol, "1h", 3600, n1h)

    df_funding = pd.DataFrame()
    fund_symbol = f"FUNDING:{symbol}"
    try:
        df_raw = await _fetch_ohlcv_df(
            delta_client, fund_symbol, "1h", 3600, min(n1h, 500)
        )
        if not df_raw.empty and "close" in df_raw.columns:
            df_funding = df_raw.rename(columns={"close": "funding_rate"}).copy()
    except Exception as e:
        logger.warning(
            "v43_funding_fetch_failed",
            symbol=symbol,
            error=str(e),
        )

    if df_funding.empty and not df1h.empty:
        df_funding = pd.DataFrame(
            {
                "timestamp": df1h["timestamp"].values,
                "funding_rate": 0.0,
            }
        )

    strict = bool(getattr(settings, "strict_candle_validation_enabled", True))
    min_rows_cfg = int(getattr(settings, "strict_candle_validation_min_rows", 50) or 50)
    if strict:
        for df, res in (
            (df5m, "5m"),
            (df15m, "15m"),
            (df1h, "1h"),
        ):
            if len(df) < 2:
                continue
            need = min(min_rows_cfg, len(df))
            try:
                validate_candles(
                    df,
                    res,
                    min_rows=max(2, need),
                    allow_last_irregular=True,
                )
            except ValueError as e:
                logger.warning(
                    "v43_candle_validation_failed",
                    resolution=res,
                    rows=len(df),
                    error=str(e),
                )

    return df5m, df15m, df1h, df_funding


def v43_frames_summary(dfs: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    """Row counts for logging."""
    return {k: len(v) for k, v in dfs.items() if isinstance(v, pd.DataFrame)}
