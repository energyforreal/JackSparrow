"""Unit tests for RollingOhlcvBufferRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pandas as pd
import pytest

from agent.data.rolling_ohlcv_buffer import RollingOhlcvBufferRegistry


@pytest.mark.asyncio
async def test_fetch_incremental_merges_tail() -> None:
    reg = RollingOhlcvBufferRegistry()
    client = AsyncMock()

    base_ts = 1_700_000_000
    client.get_candles = AsyncMock(
        return_value={
            "result": [
                {
                    "time": base_ts + i * 300,
                    "open": 100 + i,
                    "high": 101 + i,
                    "low": 99 + i,
                    "close": 100.5 + i,
                    "volume": 10,
                }
                for i in range(5)
            ]
        }
    )

    df1 = await reg.fetch_incremental(client, "BTCUSD", "5m", 10)
    assert len(df1) == 5

    client.get_candles = AsyncMock(
        return_value={
            "result": [
                {
                    "time": base_ts + 4 * 300 + i * 300,
                    "open": 200 + i,
                    "high": 201 + i,
                    "low": 199 + i,
                    "close": 200.5 + i,
                    "volume": 11,
                }
                for i in range(2)
            ]
        }
    )
    df2 = await reg.fetch_incremental(client, "BTCUSD", "5m", 10, use_incremental_cache=True)
    assert len(df2) >= 5
    assert df2.iloc[-1]["close"] == pytest.approx(201.5)


def test_hydrate_from_store_seeds_buffer(tmp_path) -> None:
    from agent.data.candle_store import CandleStore

    store = CandleStore(storage_root=tmp_path)
    rows = [
        {
            "timestamp": 1_700_000_000 + i * 300,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
        }
        for i in range(20)
    ]
    store.append("BTCUSD", "5m", rows)
    reg = RollingOhlcvBufferRegistry()
    ok = reg.hydrate_from_store(store, "BTCUSD", "5m", 15)
    assert ok
    df = reg.get("BTCUSD", "5m")
    assert df is not None
    assert len(df) == 15


@pytest.mark.asyncio
async def test_fetch_incremental_does_not_shrink_buffer() -> None:
    """Small limit polls must not truncate a warmed buffer."""
    reg = RollingOhlcvBufferRegistry()
    client = AsyncMock()
    base_ts = 1_700_000_000

    async def _candles(*_args, **kwargs):
        start = kwargs.get("start", 0)
        end = kwargs.get("end", base_ts + 50 * 300)
        bar_seconds = 300
        count = max(1, (end - start) // bar_seconds)
        return {
            "result": [
                {
                    "time": base_ts + i * bar_seconds,
                    "open": 100 + i,
                    "high": 101 + i,
                    "low": 99 + i,
                    "close": 100.5 + i,
                    "volume": 10,
                }
                for i in range(min(count, 50))
            ]
        }

    client.get_candles = AsyncMock(side_effect=_candles)

    warmed = await reg.fetch_incremental(client, "BTCUSD", "5m", 50)
    assert len(warmed) == 50

    polled = await reg.fetch_incremental(client, "BTCUSD", "5m", 10)
    assert len(polled) == 50


@pytest.mark.asyncio
async def test_fetch_incremental_recovers_when_cache_smaller_than_request() -> None:
    """Requesting n_candles > cached length must bootstrap full window."""
    reg = RollingOhlcvBufferRegistry()
    client = AsyncMock()
    base_ts = 1_700_000_000

    client.get_candles = AsyncMock(
        return_value={
            "result": [
                {
                    "time": base_ts + i * 300,
                    "open": 100 + i,
                    "high": 101 + i,
                    "low": 99 + i,
                    "close": 100.5 + i,
                    "volume": 10,
                }
                for i in range(10)
            ]
        }
    )
    small = await reg.fetch_incremental(client, "BTCUSD", "5m", 10)
    assert len(small) == 10

    client.get_candles = AsyncMock(
        return_value={
            "result": [
                {
                    "time": base_ts + i * 300,
                    "open": 100 + i,
                    "high": 101 + i,
                    "low": 99 + i,
                    "close": 100.5 + i,
                    "volume": 10,
                }
                for i in range(40)
            ]
        }
    )
    expanded = await reg.fetch_incremental(client, "BTCUSD", "5m", 40)
    assert len(expanded) == 40


def test_to_formatted_candles() -> None:
    reg = RollingOhlcvBufferRegistry()
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([1_700_000_000, 1_700_000_300], unit="s", utc=True),
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [5.0, 6.0],
        }
    )
    reg.put("BTCUSD", "5m", df)
    candles = reg.to_formatted_candles("BTCUSD", "5m", 2)
    assert len(candles) == 2
    assert candles[-1]["close"] == pytest.approx(2.05)
