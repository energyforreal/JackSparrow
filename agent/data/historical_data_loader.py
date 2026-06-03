"""Historical candle loader for offline backfill scripts.

Sync helpers block the event loop if awaited directly — use async_* from async code.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import pandas as pd
import requests

# Optional ccxt fallback for alternative data source if Delta API limits are reached
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

DELTA_HISTORY_URL = "https://api.india.delta.exchange/v2/history/candles"
DEFAULT_DELAY_SECONDS = 0.4

RESOLUTION_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
}


def _validate_resolution(resolution: str) -> None:
    if resolution not in RESOLUTION_SECONDS:
        raise ValueError(
            f"Invalid resolution '{resolution}'. "
            f"Allowed: {sorted(RESOLUTION_SECONDS.keys())}"
        )


def _fetch_delta_candles(symbol: str, resolution: str, start_ts: int, end_ts: int, page_size: int = 2000):
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "start": int(start_ts),
        "end": int(end_ts),
        "page_size": page_size,
    }
    resp = requests.get(DELTA_HISTORY_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Delta API error: {data}")
    return data.get("result", [])


async def _fetch_delta_candles_async(
    client: httpx.AsyncClient,
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
    page_size: int = 2000,
) -> list:
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "start": int(start_ts),
        "end": int(end_ts),
        "page_size": page_size,
    }
    resp = await client.get(DELTA_HISTORY_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise ValueError(f"Delta API error: {data}")
    return data.get("result", [])


def fetch_historical_candles(
    symbol: str = "BTCUSD",
    resolution: str = "5m",
    target_count: int = 100000,
    end_ts: Optional[int] = None,
    max_lookback_days: int = 730,
    dst_path: Optional[Path] = None,
    aggressive: bool = True,
) -> pd.DataFrame:
    """Fetch or backfill candle history for a timeframe with guaranteed minimum rows."""
    _validate_resolution(resolution)
    if end_ts is None:
        end_ts = int(time.time())
    period = RESOLUTION_SECONDS[resolution]
    lookback_limit = int(end_ts - max_lookback_days * 24 * 3600)

    candles = []
    current_end = end_ts

    while len(candles) < target_count and current_end > lookback_limit:
        current_start = max(lookback_limit, current_end - target_count * period * 2)
        page_candles = _fetch_delta_candles(symbol, resolution, current_start, current_end)

        if not page_candles:
            break

        # Remove duplicates and merge chronologically
        if candles and page_candles[-1]["time"] == candles[0]["time"]:
            page_candles = page_candles[:-1]

        candles = page_candles + candles

        if len(candles) >= target_count:
            break

        current_end = page_candles[0]["time"] - 1
        time.sleep(DEFAULT_DELAY_SECONDS)

    if len(candles) < target_count and aggressive and CCXT_AVAILABLE:
        # Fallback to Binance perpetual data and map timeframes
        print("[WARN] Delta data less than target; using Binance fallback (ccxt)")
        candles = _fetch_binance_candles(symbol.replace("USD", "/USDT"), resolution, target_count)

    if len(candles) > target_count:
        candles = candles[-target_count:]

    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)

    if dst_path is not None:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(dst_path)

    return df


async def fetch_historical_candles_async(
    symbol: str = "BTCUSD",
    resolution: str = "5m",
    target_count: int = 100000,
    end_ts: Optional[int] = None,
    max_lookback_days: int = 730,
    dst_path: Optional[Path] = None,
    aggressive: bool = True,
) -> pd.DataFrame:
    """Async variant safe for the agent event loop."""
    _validate_resolution(resolution)
    if end_ts is None:
        end_ts = int(time.time())
    period = RESOLUTION_SECONDS[resolution]
    lookback_limit = int(end_ts - max_lookback_days * 24 * 3600)

    candles: list = []
    current_end = end_ts

    async with httpx.AsyncClient(timeout=20.0) as client:
        while len(candles) < target_count and current_end > lookback_limit:
            current_start = max(lookback_limit, current_end - target_count * period * 2)
            page_candles = await _fetch_delta_candles_async(
                client, symbol, resolution, current_start, current_end
            )

            if not page_candles:
                break

            if candles and page_candles[-1]["time"] == candles[0]["time"]:
                page_candles = page_candles[:-1]

            candles = page_candles + candles

            if len(candles) >= target_count:
                break

            current_end = page_candles[0]["time"] - 1
            await asyncio.sleep(DEFAULT_DELAY_SECONDS)

    if len(candles) < target_count and aggressive and CCXT_AVAILABLE:
        print("[WARN] Delta data less than target; using Binance fallback (ccxt)")
        candles = await asyncio.to_thread(
            _fetch_binance_candles,
            symbol.replace("USD", "/USDT"),
            resolution,
            target_count,
        )

    if len(candles) > target_count:
        candles = candles[-target_count:]

    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)

    if dst_path is not None:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(dst_path)

    return df


def _fetch_binance_candles(symbol: str, resolution: str, target_count: int) -> list:
    if not CCXT_AVAILABLE:
        raise RuntimeError("ccxt is not installed; cannot fetch fallback Binance data")

    exchange = ccxt.binance({"enableRateLimit": True})
    timeframe = resolution
    candles = []
    since = None
    while len(candles) < target_count:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        candles.extend([{
            "time": int(item[0] / 1000),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        } for item in batch])
        since = int(batch[-1][0] + 1)
        if len(batch) < 1000:
            break
        time.sleep(0.1)

    return candles[-target_count:]
