"""Tests for paginated OHLCV fetch and production-public candle routing."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_fetch_mtf_uses_public_candle_client_not_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All OHLCV / MARK / FUNDING TFs must hit PublicCandleClient, not delta_client."""
    mf._OHLCV_FRAME_CACHE.clear()

    public_calls: List[Dict[str, Any]] = []
    delta_candle_calls: List[Any] = []

    async def public_get_candles(**kwargs: Any) -> Dict[str, Any]:
        public_calls.append(kwargs)
        # Enough bars for validation to pass lightly.
        end = int(kwargs["end"])
        bar_s = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200}.get(
            kwargs["resolution"], 3600
        )
        n = 80
        start = end - n * bar_s
        return {
            "result": {
                "candles": [_candle(start + i * bar_s, 100.0 + i * 0.01) for i in range(n)]
            }
        }

    public_client = MagicMock()
    public_client.base_url = "https://api.india.delta.exchange"
    public_client.get_candles = public_get_candles

    monkeypatch.setattr(mf, "get_public_candle_client", lambda: public_client)
    monkeypatch.setattr(mf.settings, "strict_candle_validation_enabled", False)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_5m", 60)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_15m", 60)
    monkeypatch.setattr(mf.settings, "transformer_candles_30m", 60)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_1h", 60)
    monkeypatch.setattr(mf.settings, "transformer_candles_2h", 60)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_oi", 10)

    async def fake_oi(*_a: Any, **_k: Any) -> Any:
        import pandas as pd

        return pd.DataFrame()

    monkeypatch.setattr(mf, "_fetch_oi_df", fake_oi)

    delta_client = AsyncMock()

    async def delta_get_candles(**kwargs: Any) -> Dict[str, Any]:
        delta_candle_calls.append(kwargs)
        return {"result": {"candles": []}}

    delta_client.get_candles = delta_get_candles

    df5, df15, df30, df1h, df2h, df_fund, _df_oi, df_mark = await mf.fetch_mtf_market_frames(
        delta_client, "BTCUSD"
    )

    assert delta_candle_calls == [], "testnet delta_client.get_candles must not be used"
    assert len(public_calls) >= 6  # 5m 15m 30m 1h 2h + MARK (+ FUNDING)
    resolutions = {c["resolution"] for c in public_calls}
    assert {"5m", "15m", "30m", "1h", "2h"}.issubset(resolutions)
    symbols = {c["symbol"] for c in public_calls}
    assert "BTCUSD" in symbols
    assert "MARK:BTCUSD" in symbols
    assert not df5.empty and not df15.empty and not df30.empty
    assert not df1h.empty and not df2h.empty
    assert not df_mark.empty


@pytest.mark.asyncio
async def test_fetch_v43_uses_public_candle_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mf._OHLCV_FRAME_CACHE.clear()
    public_calls: List[Dict[str, Any]] = []

    async def public_get_candles(**kwargs: Any) -> Dict[str, Any]:
        public_calls.append(kwargs)
        end = int(kwargs["end"])
        bar_s = {"5m": 300, "15m": 900, "1h": 3600}.get(kwargs["resolution"], 3600)
        n = 60
        start = end - n * bar_s
        return {
            "result": {
                "candles": [_candle(start + i * bar_s) for i in range(n)]
            }
        }

    public_client = MagicMock()
    public_client.base_url = "https://api.india.delta.exchange"
    public_client.get_candles = public_get_candles
    monkeypatch.setattr(mf, "get_public_candle_client", lambda: public_client)
    monkeypatch.setattr(mf.settings, "strict_candle_validation_enabled", False)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_5m", 50)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_15m", 50)
    monkeypatch.setattr(mf.settings, "jacksparrow_v43_candles_1h", 50)

    async def fake_oi(*_a: Any, **_k: Any) -> Any:
        import pandas as pd

        return pd.DataFrame()

    monkeypatch.setattr(mf, "_fetch_oi_df", fake_oi)

    delta_client = AsyncMock()
    delta_client.get_candles = AsyncMock(side_effect=AssertionError("delta candles"))

    await mf.fetch_v43_market_frames(delta_client, "BTCUSD")
    assert public_calls
    assert all(c.get("symbol") for c in public_calls)


def test_public_candle_client_default_base() -> None:
    client = mf.PublicCandleClient()
    assert "api.india.delta.exchange" in client.base_url
