"""v5 probability floor, fold expectancy, and confirmation embargo."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.forecast_30m.evaluation import (
    choose_direction_floor,
    direction_expectancy_fold_gate,
    one_position_direction_policy,
)
from research.forecast_30m.pipeline_v5 import _maybe_score_confirmation
from research.forecast_30m.validation import assert_outside_embargo


def _policy_frame(count: int, *, forward: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_index": np.arange(count, dtype=np.int64),
            "forward_return_24": np.full(count, forward, dtype=np.float64),
        }
    )


def _bullish_proba(count: int, *, confidence: float = 0.90) -> np.ndarray:
    proba = np.zeros((count, 3), dtype=np.float64)
    proba[:, 2] = confidence
    proba[:, 1] = (1.0 - confidence) / 2.0
    proba[:, 0] = (1.0 - confidence) / 2.0
    return proba


def test_probability_floor_keeps_a_profitable_rule() -> None:
    frame = _policy_frame(30, forward=0.02)
    choice = choose_direction_floor(
        frame,
        _bullish_proba(30),
        horizon_bars=1,
        min_trades=20,
    )
    assert choice["selected"] is not None
    assert choice["selected"]["expectancy"] > 0.0
    assert int(choice["selected"]["trades"]) >= 20


def test_probability_floor_rejects_a_losing_rule() -> None:
    frame = _policy_frame(30, forward=-0.02)
    choice = choose_direction_floor(
        frame,
        _bullish_proba(30),
        horizon_bars=1,
        min_trades=20,
    )
    assert choice["selected"] is None
    assert choice["reason"] == "no_positive_calibration_expectancy"


def test_probability_floor_rejects_a_thin_rule() -> None:
    frame = _policy_frame(8, forward=0.02)
    choice = choose_direction_floor(
        frame,
        _bullish_proba(8),
        horizon_bars=1,
        min_trades=20,
    )
    assert choice["selected"] is None
    assert choice["reason"] == "no_threshold_with_enough_trades"


def test_non_overlapping_trades_skip_a_busy_horizon() -> None:
    frame = _policy_frame(48, forward=0.01)
    stats = one_position_direction_policy(
        frame,
        _bullish_proba(48),
        threshold=0.35,
        horizon_bars=24,
    )
    assert int(stats["trades"]) == 2


def test_fold_expectancy_requires_two_wins() -> None:
    thin = direction_expectancy_fold_gate([0.01, -0.02, -0.01])
    passed = direction_expectancy_fold_gate([0.01, 0.02, -0.01])
    assert thin["passed"] is False
    assert thin["wins"] == 1
    assert passed["passed"] is True
    assert passed["wins"] == 2


def test_embargo_rows_cannot_enter_the_v5_fit() -> None:
    stamps = pd.date_range("2026-05-15 14:00", periods=10, freq="30min", tz="UTC")
    frame = pd.DataFrame({"time": stamps})
    with pytest.raises(RuntimeError, match="embargoed"):
        assert_outside_embargo(
            frame,
            pd.Timestamp("2026-05-15T14:00:00+00:00"),
            pd.Timestamp("2026-09-27T13:30:00+00:00"),
        )


def test_failed_gate_does_not_read_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise AssertionError("confirmation parquet was read")

    monkeypatch.setattr("research.forecast_30m.pipeline_v5.pd.read_parquet", boom)
    report = _maybe_score_confirmation(
        {"gate": {"passed": False, "reasons": ["expectancy_not_positive"]}},
        theta=0.50,
        snapshot_end=pd.Timestamp("2026-09-27T13:30:00+00:00"),
    )
    assert report["scored"] is False
    assert report["labels_read"] is False
    assert report["reason"] == "expectancy_not_positive"


def test_v5_pipeline_source_omits_optuna_and_lightgbm() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "forecast_30m"
        / "pipeline_v5.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "optuna" not in lowered
    assert "lightgbm" not in lowered
    assert "lgbm" not in lowered
