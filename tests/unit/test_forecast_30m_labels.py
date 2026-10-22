"""Synthetic path tests for the 30-minute label engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.forecast_30m.contract import (
    AMBIGUOUS,
    BEARISH,
    BULLISH,
    EXPIRY,
    FEATURE_COLUMNS,
    NEUTRAL,
    SL_FIRST,
    TP_FIRST,
    UNLABELED,
)
from research.forecast_30m.features import add_features
from research.forecast_30m.labels import (
    attach_targets,
    classify_path,
    development_supervised_mask,
    select_barrier,
    select_theta,
)
from research.forecast_30m.integrity import bar_seconds, to_epoch_seconds
from research.forecast_30m.validation import assert_development_only, development_blocks


def _flat(count: int, *, close: float = 100.0) -> pd.DataFrame:
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


def test_same_bar_touch_is_ambiguous_not_a_stop() -> None:
    code = classify_path(
        np.array([103.0]),
        np.array([97.0]),
        102.0,
        98.0,
        short=False,
    )
    assert code == AMBIGUOUS


def test_signal_bar_cannot_trigger_a_barrier() -> None:
    frame = _flat(60)
    frame.loc[30, "high"] = 150.0
    frame.loc[30, "low"] = 50.0
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "long_path_code"]) == EXPIRY
    assert int(labeled.loc[30, "y_direction"]) == NEUTRAL


def test_long_take_profit_and_bullish_direction() -> None:
    frame = _flat(60)
    frame.loc[40, "high"] = 103.0
    frame.loc[40, "close"] = 102.5
    frame.loc[54, "close"] = 103.0
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "long_path_code"]) == TP_FIRST
    assert int(labeled.loc[30, "y_direction"]) == BULLISH
    assert float(labeled.loc[30, "long_tp_first_24"]) == 1.0


def test_stop_prints_before_profit() -> None:
    frame = _flat(60)
    frame.loc[40, "low"] = 97.0
    frame.loc[40, "high"] = 100.5
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "long_path_code"]) == SL_FIRST
    assert float(labeled.loc[30, "long_tp_first_24"]) == 0.0


def test_short_take_profit() -> None:
    frame = _flat(60)
    frame.loc[40, "low"] = 97.0
    frame.loc[40, "high"] = 100.0
    frame.loc[54, "close"] = 97.0
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "short_path_code"]) == TP_FIRST
    assert int(labeled.loc[30, "y_direction"]) == BEARISH
    assert np.isnan(labeled.loc[30, "long_tp_first_24"]) or float(
        labeled.loc[30, "long_tp_first_24"]
    ) == 0.0


def test_ambiguous_row_is_dropped_from_the_binary_head() -> None:
    frame = _flat(60)
    frame.loc[40, "high"] = 103.0
    frame.loc[40, "low"] = 97.0
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "long_path_code"]) == AMBIGUOUS
    assert np.isnan(labeled.loc[30, "long_tp_first_24"])


def test_gap_and_short_tail_stay_unlabeled() -> None:
    frame = _flat(60).drop(index=[45]).reset_index(drop=True)
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    signal = labeled.index[labeled["time"] == pd.Timestamp("2024-01-01 15:00:00", tz="UTC")][0]
    assert int(labeled.loc[signal, "y_direction"]) == UNLABELED
    short = attach_targets(_flat(20), theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert (short["y_direction"] == UNLABELED).all()


def test_horizon_that_touches_the_holdout_is_not_a_training_row() -> None:
    frame = _flat(80)
    epochs = to_epoch_seconds(frame["time"])
    holdout = int(epochs[60])
    mask = development_supervised_mask(
        epochs,
        holdout_start=holdout,
        bar_length=bar_seconds(),
        horizon_ok=np.ones(len(frame), dtype=bool),
    )
    assert bool(mask[35]) is True
    assert bool(mask[36]) is False
    assert bool(mask[60]) is False


def test_smallest_theta_that_covers_cost_is_kept() -> None:
    chosen = select_theta(
        [
            {"theta": 0.25, "passed": False, "return_gap": 0.2},
            {"theta": 0.75, "passed": True, "return_gap": 0.1},
            {"theta": 1.00, "passed": True, "return_gap": 0.9},
        ]
    )
    assert chosen["reason"] == "smallest_band_covering_cost"
    assert chosen["selected"]["theta"] == 0.75


def test_barrier_rule_keeps_the_least_negative_asymmetric_pair() -> None:
    chosen = select_barrier(
        [
            {
                "tp_mult": 2.0,
                "sl_mult": 2.0,
                "passed": True,
                "no_skill_expectancy": -0.0001,
            },
            {
                "tp_mult": 3.0,
                "sl_mult": 1.5,
                "passed": True,
                "no_skill_expectancy": -0.0004,
            },
            {
                "tp_mult": 3.0,
                "sl_mult": 2.0,
                "passed": True,
                "no_skill_expectancy": -0.0002,
            },
        ]
    )
    assert chosen["reason"] == "highest_no_skill_expectancy"
    assert chosen["selected"]["tp_mult"] == 3.0
    assert chosen["selected"]["sl_mult"] == 2.0


def test_symmetric_barrier_is_not_split_into_two_heads() -> None:
    chosen = select_barrier(
        [
            {
                "tp_mult": 3.0,
                "sl_mult": 3.0,
                "passed": True,
                "no_skill_expectancy": -0.0001,
            }
        ]
    )
    assert chosen["selected"] is None
    assert chosen["reason"] == "symmetric_barrier_is_one_path"


def test_future_close_does_not_change_an_earlier_feature() -> None:
    base = _flat(80)
    base["close"] = np.linspace(100.0, 120.0, 80)
    base["open"] = base["close"]
    base["high"] = base["close"] + 1.0
    base["low"] = base["close"] - 1.0
    original = add_features(base)
    changed = base.copy()
    changed.loc[79, "close"] = 500.0
    alternate = add_features(changed)
    pd.testing.assert_series_equal(
        original.loc[50, list(FEATURE_COLUMNS)].astype(float),
        alternate.loc[50, list(FEATURE_COLUMNS)].astype(float),
    )


def test_walk_forward_purge_uses_the_label_horizon() -> None:
    bars = np.arange(400, dtype=np.int64)
    blocks = development_blocks(bars)
    for fold in blocks["walk_forward"]:
        assert int(bars[fold["train"]].max()) + 24 < int(bars[fold["validation"]].min())
    assert int(bars[blocks["fit"]].max()) + 24 < int(bars[blocks["calibration"]].min())


def test_training_guard_rejects_a_holdout_timestamp() -> None:
    frame = _flat(5)
    try:
        assert_development_only(frame, pd.Timestamp("2024-01-01 00:30:00", tz="UTC"))
    except RuntimeError as exc:
        assert "holdout" in str(exc)
    else:
        raise AssertionError("holdout row was accepted")
