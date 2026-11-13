"""Resampling and as-of alignment for CPR-MTF."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.cpr_mtf.bars import resample_ohlcv
from research.cpr_mtf.contract import SEQUENCE_CHANNELS, TIMEFRAMES, WINDOW_BARS
from research.cpr_mtf.windows import (
    eligible_ends,
    last_complete_index,
    prepare_timeframe,
    slice_window,
    window_suffixes,
)
from research.recognition_15m.bars import resample_completed_15m, synthetic_5m
from tests.unit.cpr_mtf_support import series_from_closes


def _flat_5m(start: str, periods: int, price: float = 100.0) -> pd.DataFrame:
    """Gap-free 5-minute bars with a constant close and a fixed wick."""
    level = np.full(periods, price, dtype=np.float64)
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq="5min", tz="UTC"),
            "open": level,
            "high": level + 1.0,
            "low": level - 1.0,
            "close": level + 0.25,
            "volume": np.full(periods, 10.0),
        }
    )


def test_fifteen_minute_resample_matches_the_recogniser() -> None:
    """The shared 15-minute bucket rule stays identical to recognition_15m."""
    source = synthetic_5m(6, start="2024-01-01T00:00:00Z")
    built = resample_ohlcv(source, "15m")
    reference = resample_completed_15m(source)
    pd.testing.assert_frame_equal(built, reference)


def test_partial_buckets_are_dropped_and_later_buckets_do_not_revise_them() -> None:
    """Unfinished 1-hour and 4-hour buckets are absent, and earlier bars stay fixed."""
    hour = _flat_5m("2024-01-01T00:00:00Z", 12)
    assert resample_ohlcv(hour.iloc[:-1], "1h").empty
    complete_hour = resample_ohlcv(hour, "1h")
    assert len(complete_hour) == 1
    assert complete_hour["time"].iloc[0] == pd.Timestamp("2024-01-01T00:00:00Z")

    four_hour = _flat_5m("2024-01-01T00:00:00Z", 48)
    assert resample_ohlcv(four_hour.iloc[:-1], "4h").empty
    complete = resample_ohlcv(four_hour, "4h")
    assert list(complete["time"]) == [pd.Timestamp("2024-01-01T00:00:00Z")]

    revised = four_hour.copy()
    revised.loc[revised.index[-1], "close"] = 999.0
    untouched = resample_ohlcv(revised, "4h")
    assert untouched.iloc[0]["open"] == complete.iloc[0]["open"]
    assert untouched.iloc[0]["close"] != complete.iloc[0]["close"]


def test_asof_clock_keeps_only_completed_higher_timeframe_bars() -> None:
    """At 10:15 the unfinished 10:00 hour and 08:00 4-hour bar stay out."""
    raw = _flat_5m("2024-06-01T00:00:00Z", 123)
    asof = pd.Timestamp("2024-06-01T10:15:00Z")
    bars = {timeframe: resample_ohlcv(raw, timeframe) for timeframe in TIMEFRAMES}
    assert bars["15m"]["time"].iloc[-1] == pd.Timestamp("2024-06-01T10:00:00Z")
    assert bars["1h"]["time"].iloc[-1] == pd.Timestamp("2024-06-01T09:00:00Z")
    assert bars["4h"]["time"].iloc[-1] == pd.Timestamp("2024-06-01T04:00:00Z")
    assert last_complete_index(bars["15m"], "15m", asof) == len(bars["15m"]) - 1
    assert last_complete_index(bars["1h"], "1h", asof) == len(bars["1h"]) - 1
    assert last_complete_index(bars["4h"], "4h", asof) == len(bars["4h"]) - 1
    assert pd.Timestamp("2024-06-01T08:00:00Z") not in set(bars["4h"]["time"])
    assert pd.Timestamp("2024-06-01T10:00:00Z") not in set(bars["1h"]["time"])


def test_suffixes_are_the_tail_of_the_192_bar_window() -> None:
    """48- and 96-bar views are suffixes of the stored 192-bar tensor."""
    rng = np.random.default_rng(4)
    closes = 100.0 + np.cumsum(rng.normal(0.0, 0.4, 320))
    prepared = prepare_timeframe(series_from_closes(closes), "15m")
    end = int(eligible_ends(len(prepared.frame))[-1])
    window = slice_window(prepared.matrix, end)
    suffixes = window_suffixes(window)
    assert window.shape == (WINDOW_BARS, len(SEQUENCE_CHANNELS))
    assert np.isfinite(window).all()
    assert np.array_equal(suffixes[48], window[-48:])
    assert np.array_equal(suffixes[96], window[-96:])
    assert np.array_equal(suffixes[192], window)
    assert "level_support_dist_atr" not in prepared.frame.columns


def test_package_does_not_call_the_noncausal_pattern_engine() -> None:
    """CPR-MTF keeps its own swing loop and does not import chart-rule features."""
    root = Path(__file__).resolve().parents[2] / "research" / "cpr_mtf"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "argrelextrema" not in text
        assert "chart_patterns" not in text
        assert "confirmed_swing_events" not in text
        assert "causal_level_channels" not in text
