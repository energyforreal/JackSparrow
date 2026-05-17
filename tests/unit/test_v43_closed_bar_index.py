"""Tests for UTC-based v43 closed-bar index."""

from __future__ import annotations

import pandas as pd

from agent.core.v43_market_frames import closed_5m_bar_index


def test_closed_5m_bar_index_advances_with_time() -> None:
    ts0 = pd.Timestamp("2026-05-15 10:00:00", tz="UTC")
    ts1 = pd.Timestamp("2026-05-15 10:05:00", tz="UTC")
    ts2 = pd.Timestamp("2026-05-15 10:10:00", tz="UTC")
    df_a = pd.DataFrame(
        {
            "timestamp": [ts0, ts1, ts2],
            "close": [1.0, 2.0, 3.0],
        }
    )
    df_b = pd.DataFrame(
        {
            "timestamp": [ts0, ts1, ts2, pd.Timestamp("2026-05-15 10:15:00", tz="UTC")],
            "close": [1.0, 2.0, 3.0, 4.0],
        }
    )
    idx_a = closed_5m_bar_index(df_a)
    idx_b = closed_5m_bar_index(df_b)
    assert idx_b == idx_a + 1


def test_closed_5m_bar_index_independent_of_window_length() -> None:
    ts = pd.Timestamp("2026-05-15 12:00:00", tz="UTC")
    short = pd.DataFrame({"timestamp": [ts - pd.Timedelta(minutes=5), ts], "close": [1.0, 2.0]})
    long = pd.DataFrame(
        {
            "timestamp": [ts - pd.Timedelta(minutes=5 * i) for i in range(600, -1, -1)],
            "close": [1.0] * 601,
        }
    )
    assert closed_5m_bar_index(short) == closed_5m_bar_index(long)
