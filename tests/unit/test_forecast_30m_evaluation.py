"""Scoring rules that stop a flat or empty policy from looking successful."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.forecast_30m.contract import SL_FIRST, TP_FIRST
from research.forecast_30m.evaluation import choose_thresholds, gate4_passed, gate5_passed
from research.forecast_30m.models import _clock_only, _worse_on_two_folds


def _frame(path_code: int) -> pd.DataFrame:
    rows = []
    for offset in range(24):
        for step in range(20):
            rows.append(
                {
                    "bar_index": offset + 24 * step,
                    "tp_pct": 0.02,
                    "sl_pct": 0.01,
                    "forward_return_24": 0.0,
                    "long_path_code": path_code,
                    "short_path_code": path_code,
                }
            )
    return pd.DataFrame(rows)


def test_gate4_ignores_a_lift_below_the_minimum() -> None:
    thin = gate4_passed(
        [0.20, 0.20, 0.20],
        [0.21, 0.21, 0.21],
        higher_is_better=False,
        min_delta=0.02,
    )
    material = gate4_passed(
        [0.18, 0.18, 0.20],
        [0.21, 0.21, 0.21],
        higher_is_better=False,
        min_delta=0.02,
    )
    assert thin["passed"] is False
    assert thin["wins"] == 0
    assert material["passed"] is True
    assert material["wins"] == 2


def test_thresholds_reject_a_rule_that_loses_on_calibration() -> None:
    frame = _frame(SL_FIRST)
    choice = choose_thresholds(
        frame,
        long_probability=np.full(len(frame), 0.95),
        short_probability=np.full(len(frame), 0.05),
    )
    assert choice["selected"] is None
    assert choice["reason"] == "no_positive_calibration_expectancy"


def test_thresholds_keep_a_rule_with_positive_expectancy() -> None:
    frame = _frame(TP_FIRST)
    choice = choose_thresholds(
        frame,
        long_probability=np.full(len(frame), 0.95),
        short_probability=np.full(len(frame), 0.05),
    )
    assert choice["selected"] is not None
    assert choice["selected"]["median_expectancy"] > 0.0


def test_empty_phases_do_not_pull_expectancy_to_zero() -> None:
    frame = _frame(SL_FIRST)
    long_probability = np.zeros(len(frame), dtype=np.float64)
    short_probability = np.zeros(len(frame), dtype=np.float64)
    traded = frame["bar_index"].to_numpy(dtype=np.int64) % 24 < 11
    long_probability[traded] = 0.95
    short_probability[traded] = 0.05
    decision = gate5_passed(
        frame,
        {"long": long_probability, "short": short_probability},
        {"long_threshold": 0.45, "short_threshold": 0.45},
    )
    expectancy = decision["costs"]["1.0"]["expectancy"]
    assert expectancy is not None
    assert abs(expectancy + 0.012) < 1e-12
    assert decision["passed"] is False


def test_ablation_ignores_a_tiny_score_change() -> None:
    assert (
        _worse_on_two_folds(
            [0.20, 0.20, 0.20],
            [0.201, 0.201, 0.201],
            False,
            min_delta=0.01,
        )
        is False
    )
    assert (
        _worse_on_two_folds(
            [0.20, 0.20, 0.20],
            [0.22, 0.22, 0.201],
            False,
            min_delta=0.01,
        )
        is True
    )


def test_clock_columns_are_not_a_price_model() -> None:
    assert _clock_only(["hour_sin", "hour_cos", "dow_sin"]) is True
    assert _clock_only(["hour_sin", "return_1"]) is False
