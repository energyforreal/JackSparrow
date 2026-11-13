"""Shared candle builders for CPR-MTF unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.cpr_mtf.candidates import Candidate
from research.cpr_mtf.contract import MODEL_CANDIDATE_FEATURES


def piecewise_closes(segments: list[tuple[int, float]], start: float = 100.0) -> np.ndarray:
    """Interpolate ``segments`` of ``(bar_count, end_price)`` after ``start``."""
    values = [start]
    current = start
    for bars, end in segments:
        if bars < 1:
            raise ValueError("segment length must be positive")
        for step in range(1, bars + 1):
            values.append(current + (end - current) * step / bars)
        current = end
    return np.asarray(values, dtype=np.float64)


def series_from_closes(
    closes: np.ndarray,
    *,
    wick: float = 0.2,
    volume: float = 10.0,
    freq: str = "15min",
    start: str = "2024-01-01T00:00:00Z",
) -> pd.DataFrame:
    """Build valid OHLC rows from a close path."""
    close = np.asarray(closes, dtype=np.float64)
    open_ = np.empty_like(close)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=len(close), freq=freq, tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(close), volume, dtype=np.float64),
        }
    )


def manual_candidate(**overrides: object) -> Candidate:
    """Candidate with horizontal boundaries, for label tests that skip generation."""
    features = np.zeros(len(MODEL_CANDIDATE_FEATURES), dtype=np.float64)
    values: dict[str, object] = {
        "candidate_id": "15m|rectangle|2024-01-01T00:00:00Z|2024-01-01T01:00:00Z",
        "timeframe": "15m",
        "pattern": "rectangle",
        "direction": "neutral",
        "rule_score": 0.5,
        "geometry_kind": "swing",
        "swing_confirmation_indices": (1, 2),
        "first_confirmation_index": 1,
        "last_confirmation_index": 2,
        "first_pivot_index": 0,
        "last_pivot_index": 2,
        "upper_price_at_asof": 100.0,
        "lower_price_at_asof": 90.0,
        "upper_slope": 0.0,
        "lower_slope": 0.0,
        "atr": 1.0,
        "origin_close": 95.0,
        "start_time": pd.Timestamp("2024-01-01T00:00:00Z"),
        "asof_time": pd.Timestamp("2024-01-02T00:00:00Z"),
        "features": features,
    }
    values.update(overrides)
    return Candidate(**values)
