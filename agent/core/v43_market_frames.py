"""Fetch multi-timeframe OHLCV + funding DataFrames for JackSparrow v43."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import structlog

from agent.core.v43_oi_frames import fetch_oi_history
from agent.data.candle_validation import validate_candles
from agent.data.rolling_ohlcv_buffer import RollingOhlcvBufferRegistry
from agent.core.config import settings

logger = structlog.get_logger()

# Legacy module-level cache when no MarketDataManager registry is supplied.
_OHLCV_FRAME_CACHE: Dict[str, Dict[str, pd.DataFrame]] = {}
_LEGACY_BUFFER_REGISTRY = RollingOhlcvBufferRegistry()


def _legacy_registry_from_module_cache() -> RollingOhlcvBufferRegistry:
    """Sync legacy dict cache into registry for backward-compatible fetch paths."""
    reg = RollingOhlcvBufferRegistry()
    for sym, res_map in _OHLCV_FRAME_CACHE.items():
        for res, df in res_map.items():
            if df is not None and not df.empty:
                reg.put(sym, res, df)
    return reg


def _sync_module_cache_from_registry(
    registry: RollingOhlcvBufferRegistry,
    symbol: str,
    resolution: str,
) -> None:
    df = registry.get(symbol, resolution)
    if df is not None and not df.empty:
        _OHLCV_FRAME_CACHE.setdefault(symbol, {})[resolution] = df


async def _fetch_ohlcv_df(
    delta_client: Any,
    symbol: str,
    resolution: str,
    bar_seconds: int,
    n_candles: int,
    *,
    use_incremental_cache: bool = True,
    buffer_registry: Optional[RollingOhlcvBufferRegistry] = None,
) -> pd.DataFrame:
    """Fetch last ``n_candles`` bars ending now (incremental append when cached)."""
    registry = buffer_registry
    if registry is None:
        registry = _legacy_registry_from_module_cache()

    out = await registry.fetch_incremental(
        delta_client,
        symbol,
        resolution,
        n_candles,
        use_incremental_cache=use_incremental_cache,
    )
    if buffer_registry is None:
        _OHLCV_FRAME_CACHE.setdefault(symbol, {})[resolution] = out
    else:
        _sync_module_cache_from_registry(registry, symbol, resolution)
    return out


async def _fetch_funding_series(
    delta_client: Any,
    symbol: str,
    n1h: int,
    *,
    buffer_registry: Optional[RollingOhlcvBufferRegistry] = None,
) -> pd.DataFrame:
    """Fetch hourly funding proxy series; returns empty on failure."""
    fund_symbol = f"FUNDING:{symbol}"
    try:
        df_raw = await _fetch_ohlcv_df(
            delta_client,
            fund_symbol,
            "1h",
            3600,
            min(n1h, 500),
            buffer_registry=buffer_registry,
        )
        if not df_raw.empty and "close" in df_raw.columns:
            return df_raw.rename(columns={"close": "funding_rate"}).copy()
    except Exception as e:
        logger.warning(
            "v43_funding_fetch_failed",
            symbol=symbol,
            error=str(e),
        )
    return pd.DataFrame()


async def _fetch_oi_df(
    delta_client: Any,
    symbol: str,
    n_bars: int,
) -> pd.DataFrame:
    """Fetch OI snapshot history for ``symbol``; returns empty DataFrame on failure."""
    try:
        return await fetch_oi_history(delta_client, symbol, n_snapshots=n_bars)
    except Exception as e:
        logger.warning("v43_oi_frames_fetch_failed", symbol=symbol, error=str(e))
        return pd.DataFrame()


async def fetch_v43_market_frames(
    delta_client: Any,
    symbol: str,
    *,
    buffer_registry: Optional[RollingOhlcvBufferRegistry] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load 5m / 15m / 1h OHLCV, funding, ticker snapshots, and MARK candles for ``fe.transform``.

    Args:
        delta_client: ``DeltaExchangeClient`` with ``get_candles``.
        symbol: Underlying (e.g. ``BTCUSD``).

    Returns:
        Tuple ``(df5m, df15m, df1h, df_funding, df_oi, df_mark)``. Funding uses
        ``FUNDING:{symbol}`` at ``1h`` when available. ``df_oi`` is the expanded ticker
        ring buffer (OI + microstructure fields). ``df_mark`` is ``MARK:{symbol}`` 5m OHLCV.
    """
    n5 = int(getattr(settings, "jacksparrow_v43_candles_5m", 600) or 600)
    n15 = int(getattr(settings, "jacksparrow_v43_candles_15m", 400) or 400)
    n1h = int(getattr(settings, "jacksparrow_v43_candles_1h", 300) or 300)
    n_oi = int(getattr(settings, "jacksparrow_v43_candles_oi", 300) or 300)
    mark_symbol = f"MARK:{symbol}"

    df5m, df15m, df1h, df_funding, df_oi, df_mark = await asyncio.gather(
        _fetch_ohlcv_df(
            delta_client, symbol, "5m", 300, n5, buffer_registry=buffer_registry
        ),
        _fetch_ohlcv_df(
            delta_client, symbol, "15m", 900, n15, buffer_registry=buffer_registry
        ),
        _fetch_ohlcv_df(
            delta_client, symbol, "1h", 3600, n1h, buffer_registry=buffer_registry
        ),
        _fetch_funding_series(delta_client, symbol, n1h, buffer_registry=buffer_registry),
        _fetch_oi_df(delta_client, symbol, n_oi),
        _fetch_ohlcv_df(
            delta_client, mark_symbol, "5m", 300, n5, buffer_registry=buffer_registry
        ),
    )

    if df_funding.empty and not df_oi.empty and "predicted_funding_rate" in df_oi.columns:
        df_funding = (
            df_oi[["timestamp", "predicted_funding_rate"]]
            .rename(columns={"predicted_funding_rate": "funding_rate"})
            .copy()
        )
        logger.info(
            "v43_funding_from_oi_predicted_rate",
            symbol=symbol,
            rows=len(df_funding),
        )
    elif df_funding.empty and not df1h.empty:
        logger.warning(
            "v43_funding_zero_fill_fallback",
            symbol=symbol,
            message="Using 0.0 funding_rate — FUNDING fetch and OI predicted_funding_rate unavailable",
        )
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

    return df5m, df15m, df1h, df_funding, df_oi, df_mark


def v43_frames_summary(dfs: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    """Row counts for logging."""
    return {k: len(v) for k, v in dfs.items() if isinstance(v, pd.DataFrame)}


def closed_5m_bar_index(ohlcv: pd.DataFrame, bar_seconds: int = 300) -> int:
    """Monotonic UTC bar slot for the last *closed* 5m candle (``iloc[-2]``).

    Uses candle open time in epoch seconds, not ``len(df)-1`` inside a fixed rolling
    window (which stays ~599 and breaks v43 debounce).
    """
    if ohlcv is None or len(ohlcv) < 2 or "timestamp" not in ohlcv.columns:
        return 0
    ts = ohlcv["timestamp"].iloc[-2]
    try:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        epoch = int(t.timestamp())
    except (TypeError, ValueError, AttributeError):
        return 0
    return epoch // max(1, int(bar_seconds))
