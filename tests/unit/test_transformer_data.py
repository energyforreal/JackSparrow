"""Tests for transformer training candle pagination and completeness."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.colab import transformer_data as td


def _candle(ts: int, close: float = 100.0) -> Dict[str, Any]:
    return {
        "time": ts,
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1.0,
    }


def _contiguous_bars(start_ts: int, n: int, bar_seconds: int) -> List[Dict[str, Any]]:
    return [_candle(start_ts + i * bar_seconds, close=100.0 + i) for i in range(n)]


class _NewestInRangeApi:
    """Fake Delta history API: newest ``cap`` bars in [start, end], newest-first."""

    def __init__(self, bars: List[Dict[str, Any]], cap: int) -> None:
        self.bars = sorted(bars, key=lambda r: int(r["time"]))
        self.cap = cap
        self.calls: List[Dict[str, int]] = []

    def get(self, url: str, params: Dict[str, Any], timeout: int = 30) -> Any:
        start = int(params["start"])
        end = int(params["end"])
        self.calls.append({"start": start, "end": end})
        in_range = [r for r in self.bars if start <= int(r["time"]) <= end]
        page = in_range[-self.cap :] if len(in_range) > self.cap else in_range
        page = list(reversed(page))
        return _FakeResponse({"success": True, "result": page})


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_fetch_candles_collects_all_bars_when_cap_below_window() -> None:
    bar = 60
    start_ts = 1_000_000
    n = 10
    bars = _contiguous_bars(start_ts, n, bar)
    end_ts = start_ts + n * bar
    api = _NewestInRangeApi(bars, cap=3)

    with patch.object(td.requests, "get", side_effect=api.get):
        with patch.object(td.time, "sleep"):
            df = td.fetch_candles(
                "BTCUSD",
                "1m",
                start_ts,
                end_ts,
                "https://api.india.delta.exchange",
                page_bars=8,
            )

    assert len(df) == n
    assert df["time"].is_monotonic_increasing
    assert len(api.calls) >= 2
    expected_times = [start_ts + i * bar for i in range(n)]
    got = [int(ts.timestamp()) for ts in df["time"]]
    assert got == expected_times


def test_fetch_candles_parses_result_candles_dict() -> None:
    bar = 60
    start_ts = 1_000_000
    bars = _contiguous_bars(start_ts, 3, bar)

    def fake_get(url: str, params: Dict[str, Any], timeout: int = 30) -> Any:
        return _FakeResponse({"success": True, "result": {"candles": bars}})

    with patch.object(td.requests, "get", side_effect=fake_get):
        with patch.object(td.time, "sleep"):
            df = td.fetch_candles(
                "BTCUSD",
                "1m",
                start_ts,
                start_ts + 3 * bar,
                "https://api.india.delta.exchange",
                page_bars=10,
            )
    assert len(df) == 3


def test_validate_ohlcv_completeness_ok_on_contiguous() -> None:
    bar = 300
    start = 1_700_000_000
    rows = _contiguous_bars(start, 20, bar)
    df = pd.DataFrame(rows)
    report = td.validate_ohlcv_completeness(df, "5m", symbol="BTCUSD")
    assert report["gaps"] == 0
    assert report["completeness"] == 1.0
    assert report["rows"] == 20


def test_validate_ohlcv_completeness_raises_on_sawtooth_gaps() -> None:
    bar = 300
    start = 1_700_000_000
    # 5 bars, skip 15, 5 bars — the 2000-window / 500-cap failure mode.
    kept = _contiguous_bars(start, 5, bar) + _contiguous_bars(start + 20 * bar, 5, bar)
    df = pd.DataFrame(kept)
    with pytest.raises(ValueError, match="completeness"):
        td.validate_ohlcv_completeness(df, "5m", min_completeness=0.95, symbol="BTCUSD")


def test_fetch_candles_retries_empty_then_stops() -> None:
    calls = {"n": 0}

    def fake_get(url: str, params: Dict[str, Any], timeout: int = 30) -> Any:
        calls["n"] += 1
        return _FakeResponse({"success": True, "result": []})

    with patch.object(td.requests, "get", side_effect=fake_get):
        with patch.object(td.time, "sleep"):
            with pytest.raises(RuntimeError, match="No candle data"):
                td.fetch_candles(
                    "BTCUSD",
                    "1m",
                    1_000_000,
                    1_000_000 + 10 * 60,
                    "https://api.india.delta.exchange",
                    page_bars=4,
                )
    assert calls["n"] == td.EMPTY_PAGE_RETRIES


def test_parse_candle_rows_ignores_non_dicts() -> None:
    rows = td._parse_candle_rows(
        {"success": True, "result": [{"time": 1, "close": 1}, "bad", {"open": 1}]}
    )
    assert len(rows) == 1
    assert rows[0]["time"] == 1
