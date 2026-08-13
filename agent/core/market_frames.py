"""Fetch multi-timeframe OHLCV + funding DataFrames for JackSparrow v43."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import structlog

from agent.core.oi_frames import fetch_oi_history
from agent.data.candle_validation import dataframe_from_delta_candles, validate_candles
from agent.core.config import settings

logger = structlog.get_logger()

# Incremental OHLCV cache: symbol -> resolution -> DataFrame (PERF-01)
_OHLCV_FRAME_CACHE: Dict[str, Dict[str, pd.DataFrame]] = {}
_INCREMENTAL_TAIL_BARS = 3
# Delta history/candles typically caps ~500 bars per request.
_DELTA_CANDLE_PAGE_BARS = 500


def _candle_timestamp_epoch(value: Any) -> Optional[int]:
    """Best-effort Unix seconds from a candle timestamp field."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return int(value)
        t = pd.Timestamp(value)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        return int(t.timestamp())
    except (TypeError, ValueError, AttributeError):
        return None


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


async def _fetch_ohlcv_paginated(
    delta_client: Any,
    symbol: str,
    resolution: str,
    bar_seconds: int,
    n_candles: int,
    end_ts: int,
) -> pd.DataFrame:
    """Fetch up to ``n_candles`` bars by walking start backward in ~500-bar pages."""
    need = max(1, int(n_candles))
    page_bars = _DELTA_CANDLE_PAGE_BARS
    frames: List[pd.DataFrame] = []
    cursor_end = int(end_ts)
    max_pages = max(2, (need // page_bars) + 3)
    seen_oldest: Optional[int] = None

    for _ in range(max_pages):
        start_ts = cursor_end - int(page_bars * bar_seconds * 1.05)
        if start_ts >= cursor_end:
            start_ts = cursor_end - max(1, bar_seconds)
        resp = await delta_client.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start_ts,
            end=cursor_end,
        )
        formatted = _parse_candles_response(resp)
        if not formatted:
            break
        page_df = dataframe_from_delta_candles(formatted)
        if page_df.empty:
            break
        frames.append(page_df)
        epochs = [
            e
            for e in (_candle_timestamp_epoch(v) for v in page_df["timestamp"].tolist())
            if e is not None
        ]
        if not epochs:
            break
        oldest = min(epochs)
        if seen_oldest is not None and oldest >= seen_oldest:
            break
        seen_oldest = oldest
        combined = (
            pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset=["timestamp"], keep="last")
            .sort_values("timestamp")
        )
        if len(combined) >= need:
            return combined.tail(need).reset_index(drop=True)
        cursor_end = oldest - 1

    if not frames:
        return pd.DataFrame()
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .tail(need)
        .reset_index(drop=True)
    )


async def _fetch_ohlcv_df(
    delta_client: Any,
    symbol: str,
    resolution: str,
    bar_seconds: int,
    n_candles: int,
    *,
    use_incremental_cache: bool = True,
) -> pd.DataFrame:
    """Fetch last ``n_candles`` bars ending now (incremental append when cached).

    Full history requests paginate past Delta's ~500-bar page limit so higher TFs
    (1h/2h) can satisfy ``scale_period(96) + window_len`` after feature ``dropna``.
    """
    from datetime import datetime, timezone

    end_ts = int(datetime.now(timezone.utc).timestamp())
    sym_cache = _OHLCV_FRAME_CACHE.setdefault(symbol, {})
    cached = sym_cache.get(resolution) if use_incremental_cache else None
    need = max(1, int(n_candles))

    # Incremental only when cache already has sufficient depth for the target window.
    can_incremental = (
        use_incremental_cache
        and cached is not None
        and not cached.empty
        and "timestamp" in cached.columns
        and len(cached) >= need
    )

    if can_incremental:
        start_ts = end_ts - int(_INCREMENTAL_TAIL_BARS * bar_seconds * 2)
        resp = await delta_client.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start_ts,
            end=end_ts,
        )
        formatted = _parse_candles_response(resp)
        fresh = dataframe_from_delta_candles(formatted)
        if fresh.empty:
            out = cached.tail(need).reset_index(drop=True)
        else:
            combined = (
                pd.concat([cached, fresh], ignore_index=True)
                .drop_duplicates(subset=["timestamp"], keep="last")
                .sort_values("timestamp")
            )
            out = combined.tail(need).reset_index(drop=True)
        sym_cache[resolution] = out
        return out

    out = await _fetch_ohlcv_paginated(
        delta_client,
        symbol,
        resolution,
        bar_seconds,
        need,
        end_ts,
    )
    if out.empty and cached is not None and not cached.empty:
        out = cached.tail(need).reset_index(drop=True)
    if not out.empty:
        sym_cache[resolution] = out
    return out


async def _fetch_funding_series(
    delta_client: Any,
    symbol: str,
    n1h: int,
) -> pd.DataFrame:
    """Fetch hourly funding proxy series; returns empty on failure."""
    fund_symbol = f"FUNDING:{symbol}"
    try:
        df_raw = await _fetch_ohlcv_df(
            delta_client, fund_symbol, "1h", 3600, min(n1h, 500)
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


async def fetch_mtf_market_frames(
    delta_client: Any,
    symbol: str,
) -> Tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Load 5m/15m/30m/1h/2h OHLCV, funding, OI, and MARK candles.

    Returns:
        Tuple ``(df5m, df15m, df30m, df1h, df2h, df_funding, df_oi, df_mark)``.
    """
    n5 = int(getattr(settings, "jacksparrow_v43_candles_5m", 600) or 600)
    n15 = int(getattr(settings, "jacksparrow_v43_candles_15m", 500) or 500)
    n30 = int(getattr(settings, "transformer_candles_30m", 800) or 800)
    n1h = int(getattr(settings, "jacksparrow_v43_candles_1h", 1400) or 1400)
    n2h = int(getattr(settings, "transformer_candles_2h", 2600) or 2600)
    n_oi = int(getattr(settings, "jacksparrow_v43_candles_oi", 300) or 300)
    mark_symbol = f"MARK:{symbol}"

    (
        df5m,
        df15m,
        df30m,
        df1h,
        df2h,
        df_funding,
        df_oi,
        df_mark,
    ) = await asyncio.gather(
        _fetch_ohlcv_df(delta_client, symbol, "5m", 300, n5),
        _fetch_ohlcv_df(delta_client, symbol, "15m", 900, n15),
        _fetch_ohlcv_df(delta_client, symbol, "30m", 1800, n30),
        _fetch_ohlcv_df(delta_client, symbol, "1h", 3600, n1h),
        _fetch_ohlcv_df(delta_client, symbol, "2h", 7200, n2h),
        _fetch_funding_series(delta_client, symbol, n1h),
        _fetch_oi_df(delta_client, symbol, n_oi),
        _fetch_ohlcv_df(delta_client, mark_symbol, "5m", 300, n5),
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
            (df30m, "30m"),
            (df1h, "1h"),
            (df2h, "2h"),
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

    return df5m, df15m, df30m, df1h, df2h, df_funding, df_oi, df_mark


async def fetch_v43_market_frames(
    delta_client: Any,
    symbol: str,
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
    n15 = int(getattr(settings, "jacksparrow_v43_candles_15m", 500) or 500)
    n1h = int(getattr(settings, "jacksparrow_v43_candles_1h", 1400) or 1400)
    n_oi = int(getattr(settings, "jacksparrow_v43_candles_oi", 300) or 300)
    mark_symbol = f"MARK:{symbol}"

    df5m, df15m, df1h, df_funding, df_oi, df_mark = await asyncio.gather(
        _fetch_ohlcv_df(delta_client, symbol, "5m", 300, n5),
        _fetch_ohlcv_df(delta_client, symbol, "15m", 900, n15),
        _fetch_ohlcv_df(delta_client, symbol, "1h", 3600, n1h),
        _fetch_funding_series(delta_client, symbol, n1h),
        _fetch_oi_df(delta_client, symbol, n_oi),
        _fetch_ohlcv_df(delta_client, mark_symbol, "5m", 300, n5),
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
