"""Fixtures for swinging unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(
    rows: int = 48,
    *,
    freq: str = "5min",
    start: str = "2024-01-01",
    price: float = 100.0,
    drift: float = 0.0,
) -> pd.DataFrame:
    """Return a regular OHLCV frame.

    Args:
        rows: Number of bars.
        freq: Pandas offset alias.
        start: UTC start timestamp.
        price: First close.
        drift: Close change per bar.

    Returns:
        Columns ``time``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """
    times = pd.date_range(start, periods=rows, freq=freq, tz="UTC")
    close = price + np.arange(rows, dtype=float) * drift
    opened = close - 0.05
    high = np.maximum(opened, close) + 0.15
    low = np.minimum(opened, close) - 0.15
    volume = np.full(rows, 10.0)
    return pd.DataFrame(
        {
            "time": times,
            "open": opened,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
