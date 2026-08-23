"""Tests for independent 10m construction and causal as-of alignment."""

from __future__ import annotations

import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import FUSION_INPUT_RESOLUTIONS
from feature_store.transformer_btcusd.mtf_frames import (
    assert_no_lookahead,
    bar_close_time,
    build_10m_ohlcv_from_5m,
    closed_bars_asof,
    fusion_frames_from_fetch,
)


def _ohlcv(times: pd.DatetimeIndex, high: float, low: float, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10.0,
        }
    )


def test_fusion_inputs_exclude_15m() -> None:
    assert "15m" not in FUSION_INPUT_RESOLUTIONS
    assert FUSION_INPUT_RESOLUTIONS == ("5m", "10m", "30m", "1h", "2h")


def test_10m_high_low_are_true_5m_extrema() -> None:
    times = pd.date_range("2024-01-01 10:00", periods=2, freq="5min", tz="UTC")
    df5 = pd.DataFrame(
        {
            "timestamp": times,
            "open": [100.0, 101.0],
            "high": [102.5, 103.0],
            "low": [99.0, 100.5],
            "close": [101.0, 102.0],
            "volume": [3.0, 4.0],
        }
    )
    df10 = build_10m_ohlcv_from_5m(df5)
    assert len(df10) == 1
    assert float(df10.iloc[0]["high"]) == 103.0
    assert float(df10.iloc[0]["low"]) == 99.0
    assert float(df10.iloc[0]["open"]) == 100.0
    assert float(df10.iloc[0]["close"]) == 102.0
    assert float(df10.iloc[0]["volume"]) == 7.0


def test_asof_excludes_unclosed_1h_bar() -> None:
    opens = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-01 09:00", tz="UTC"),
            pd.Timestamp("2024-01-01 10:00", tz="UTC"),
        ]
    )
    df1h = _ohlcv(opens, high=110.0, low=90.0, close=100.0)
    decision = pd.Timestamp("2024-01-01 10:17", tz="UTC")
    closed = closed_bars_asof(df1h, decision, resolution_minutes=60)
    assert len(closed) == 1
    assert closed.iloc[0]["time"] == pd.Timestamp("2024-01-01 09:00", tz="UTC")
    assert_no_lookahead(closed, decision, resolution_minutes=60)


def test_fusion_frames_builds_10m_when_missing() -> None:
    times5 = pd.date_range("2024-01-01", periods=12, freq="5min", tz="UTC")
    df5 = _ohlcv(times5, 101.0, 99.0, 100.0)
    df30 = _ohlcv(pd.date_range("2024-01-01", periods=2, freq="30min", tz="UTC"), 101.0, 99.0, 100.0)
    df1h = _ohlcv(pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC"), 101.0, 99.0, 100.0)
    df2h = _ohlcv(pd.date_range("2024-01-01", periods=2, freq="2h", tz="UTC"), 101.0, 99.0, 100.0)
    frames = fusion_frames_from_fetch(df5, df30, df1h, df2h)
    assert "10m" in frames
    assert not frames["10m"].empty
    assert "15m" not in frames


def test_bar_close_time_is_open_plus_tf() -> None:
    opens = pd.Series([pd.Timestamp("2024-01-01 10:00", tz="UTC")])
    close = bar_close_time(opens, 60).iloc[0]
    assert close == pd.Timestamp("2024-01-01 11:00", tz="UTC")
