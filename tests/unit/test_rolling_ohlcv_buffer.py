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
