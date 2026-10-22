"""v4 direction labels, causal patterns, and pipeline isolation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.forecast_30m.contract_v4 import FEATURE_COLUMNS, PATTERN_COLUMNS
from research.forecast_30m.features import add_features
from research.forecast_30m.labels import select_theta_class_floor, _score_theta_class_floor
from research.forecast_30m.validation import assert_outside_embargo


def _ohlcv(count: int, *, close: float = 100.0) -> pd.DataFrame:
    stamps = pd.date_range("2024-01-01", periods=count, freq="30min", tz="UTC")
    return pd.DataFrame(
        {
            "time": stamps,
            "open": np.full(count, close),
            "high": np.full(count, close + 1.0),
            "low": np.full(count, close - 1.0),
            "close": np.full(count, close),
            "volume": np.full(count, 10.0),
        }
    )


def test_pattern_flags_do_not_use_future_bars() -> None:
    frame = _ohlcv(80)
    frame["close"] = np.linspace(100.0, 120.0, 80)
    frame["open"] = frame["close"]
    frame["high"] = frame["close"] + 1.0
    frame["low"] = frame["close"] - 1.0
    original = add_features(frame, feature_columns=FEATURE_COLUMNS)
    changed = frame.copy()
    changed.loc[79, "high"] = 500.0
    changed.loc[79, "low"] = 1.0
    changed.loc[79, "close"] = 400.0
    alternate = add_features(changed, feature_columns=FEATURE_COLUMNS)
    columns = list(PATTERN_COLUMNS)
    pd.testing.assert_series_equal(
        original.loc[50, columns].astype(float),
        alternate.loc[50, columns].astype(float),
    )


def test_hammer_and_engulfing_use_only_current_and_previous_bar() -> None:
    frame = _ohlcv(10)
    frame.loc[5, "open"] = 100.0
    frame.loc[5, "close"] = 100.2
    frame.loc[5, "high"] = 100.3
    frame.loc[5, "low"] = 98.0
    frame.loc[4, "open"] = 101.0
    frame.loc[4, "close"] = 99.5
    frame.loc[4, "high"] = 101.2
    frame.loc[4, "low"] = 99.4
    frame.loc[6, "open"] = 101.0
    frame.loc[6, "close"] = 99.5
    frame.loc[6, "high"] = 101.2
    frame.loc[6, "low"] = 99.4
    frame.loc[7, "open"] = 99.4
    frame.loc[7, "close"] = 101.3
    frame.loc[7, "high"] = 101.4
    frame.loc[7, "low"] = 99.3
    featured = add_features(frame, feature_columns=FEATURE_COLUMNS)
    assert float(featured.loc[5, "hammer"]) == 1.0
    assert float(featured.loc[7, "bullish_engulfing"]) == 1.0


def test_theta_class_floor_ignores_cost_screens() -> None:
    simple = np.array([-0.02, -0.001, 0.02] * 40, dtype=np.float64)
    atr_pct = np.full(simple.shape, 0.01, dtype=np.float64)
    usable = np.ones(simple.shape, dtype=bool)
    row = _score_theta_class_floor(0.25, simple, atr_pct, usable)
    assert "bullish_mean_not_above_cost" not in row["fail_reasons"]
    assert "bearish_mean_not_below_cost" not in row["fail_reasons"]
    assert "neutral_band_below_cost" not in row["fail_reasons"]
    chosen = select_theta_class_floor(
        [
            {"theta": 0.25, "passed": False},
            {"theta": 0.40, "passed": True},
            {"theta": 0.75, "passed": True},
        ]
    )
    assert chosen["reason"] == "smallest_theta_meeting_class_floor"
    assert chosen["selected"]["theta"] == 0.40


def test_embargo_rows_cannot_enter_the_v4_fit() -> None:
    stamps = pd.date_range("2026-05-15 14:00", periods=10, freq="30min", tz="UTC")
    frame = pd.DataFrame({"time": stamps})
    with pytest.raises(RuntimeError, match="embargoed"):
        assert_outside_embargo(
            frame,
            pd.Timestamp("2026-05-15T14:00:00+00:00"),
            pd.Timestamp("2026-09-27T13:30:00+00:00"),
        )


def test_v4_pipeline_source_omits_barrier_and_tail_scoring() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "forecast_30m"
        / "pipeline_v4.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "take-profit" not in lowered
    assert "take_profit" not in lowered
    assert "stop-loss" not in lowered
    assert "stop_loss" not in lowered
    assert "confirmation" not in lowered
