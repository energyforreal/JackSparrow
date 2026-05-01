"""Strict candle validation."""

import pandas as pd
import pytest

from agent.data.candle_validation import (
    resolution_to_seconds,
    validate_candles,
    validate_delta_candle_rows,
)


def test_resolution_to_seconds() -> None:
    assert resolution_to_seconds("5m") == 300
    assert resolution_to_seconds("15m") == 900


def test_validate_candles_regular_spacing() -> None:
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    rows = []
    for i in range(60):
        ts = base + pd.Timedelta(minutes=5 * i)
        p = 100.0 + i * 0.1
        rows.append(
            {
                "timestamp": ts,
                "open": p,
                "high": p + 1,
                "low": p - 1,
                "close": p,
                "volume": 10.0,
            }
        )
    df = pd.DataFrame(rows)
    validate_candles(df, "5m", min_rows=50, allow_last_irregular=False)


def test_validate_candles_gap_raises() -> None:
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    rows = []
    for i in range(20):
        if i <= 10:
            ts = base + pd.Timedelta(minutes=5 * i)
        else:
            # Skip 30 minutes of expected 5m bars after bar 10
            ts = base + pd.Timedelta(minutes=5 * i + 30)
        p = 100.0 + i * 0.1
        rows.append(
            {
                "timestamp": ts,
                "open": p,
                "high": p + 1,
                "low": p - 1,
                "close": p,
                "volume": 10.0,
            }
        )
    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    with pytest.raises(ValueError, match="irregular"):
        validate_candles(df, "5m", min_rows=5, allow_last_irregular=False)


def test_validate_delta_candle_rows_seconds() -> None:
    t0 = 1700000000
    candles = []
    for i in range(80):
        p = 40000.0 + i
        candles.append(
            {
                "timestamp": t0 + i * 300,
                "open": p,
                "high": p + 2,
                "low": p - 2,
                "close": p + 0.5,
                "volume": 100.0,
            }
        )
    validate_delta_candle_rows(candles, "5m", min_rows=50, allow_last_irregular=True)
