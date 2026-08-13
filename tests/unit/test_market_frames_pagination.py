"""Tests for paginated OHLCV fetch past Delta ~500-bar pages."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from agent.core import market_frames as mf


def _candle(ts: int, close: float = 100.0) -> Dict[str, Any]:
    return {
        "time": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
    }


@pytest.mark.asyncio
async def test_fetch_ohlcv_paginates_until_n_candles() -> None:
    mf._OHLCV_FRAME_CACHE.clear()
    bar_seconds = 3600
    end_ts = 1_700_000_000
    page1_start = end_ts - 500 * bar_seconds
    page2_start = page1_start - 500 * bar_seconds

    # Page 1: newest 500 bars; page 2: older 300 → total 800 after dedupe.
    page1 = [_candle(page1_start + i * bar_seconds) for i in range(500)]
    page2 = [_candle(page2_start + i * bar_seconds) for i in range(300)]

    calls: List[Dict[str, Any]] = []

    async def fake_get_candles(**kwargs: Any) -> Dict[str, Any]:
        calls.append(kwargs)
        end = int(kwargs["end"])
        # Newest window first, then older history as cursor walks backward.
        if end >= end_ts - bar_seconds:
            return {"result": {"candles": page1}}
        return {"result": {"candles": page2}}

    client = AsyncMock()
    client.get_candles = fake_get_candles

    out = await mf._fetch_ohlcv_paginated(
        client, "BTCUSD", "1h", bar_seconds, 800, end_ts
    )

    assert len(calls) >= 2
    assert len(out) == 800
    assert "timestamp" in out.columns
