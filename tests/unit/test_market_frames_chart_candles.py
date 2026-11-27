"""Shared OHLCV cache helpers used by the Market Analysis chart."""

from __future__ import annotations

import pandas as pd

from agent.core import market_frames


def test_ohlcv_frame_to_candles_and_cache_roundtrip() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [1_700_000_000, 1_700_000_900, 1_700_001_800],
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [10.0, 11.0, 12.0],
        }
    )
    market_frames._OHLCV_FRAME_CACHE["BTCUSD"] = {"15m": frame}
    try:
        cached = market_frames.get_cached_ohlcv_frame("BTCUSD", "15m")
        assert cached is not None
        candles = market_frames.ohlcv_frame_to_candles(cached, limit=2)
        assert len(candles) == 2
        assert candles[0]["timestamp"] == 1_700_000_900
        assert candles[1]["close"] == 3.2
        assert market_frames.get_cached_ohlcv_frame("BTCUSD", "1h") is None
    finally:
        market_frames._OHLCV_FRAME_CACHE.pop("BTCUSD", None)
