"""v3 next-open fill, CUSUM events, embargo, and confirmation guards."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.forecast_30m.contract import EXPIRY, SL_FIRST, TP_FIRST, UNLABELED
from pathlib import Path

from research.forecast_30m.evaluation import (
    always_in_expectancy,
    circular_block_bootstrap_means,
    confirmation_gate,
    probability_quintiles,
    ranking_statistical_gate,
)
from research.forecast_30m.integrity import bar_seconds, to_epoch_seconds
from research.forecast_30m.labels import (
    _path_with_fill_gap,
    attach_targets,
    cusum_event_mask,
    development_supervised_mask,
)
from research.forecast_30m.pipeline_v3 import _maybe_score_confirmation
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
    confirmation_mask,
)
def _flat(count: int, *, close: float = 100.0, start: str = "2024-01-01") -> pd.DataFrame:
    stamps = pd.date_range(start, periods=count, freq="30min", tz="UTC")
    return pd.DataFrame(
        {
            "time": stamps,
            "open": np.full(count, close),
            "high": np.full(count, close + 0.5),
            "low": np.full(count, close - 0.5),
            "close": np.full(count, close),
            "volume": np.full(count, 10.0),
        }
    )


def test_next_open_fill_ignores_the_signal_bar() -> None:
    frame = _flat(60)
    frame.loc[30, "high"] = 150.0
    frame.loc[30, "low"] = 50.0
    frame.loc[31, "open"] = 100.0
    frame.loc[31, "high"] = 103.0
    labeled = attach_targets(
        frame,
        theta=None,
        tp_mult=None,
        sl_mult=None,
        entry="next_open",
        tp_pct_fixed=0.02,
        sl_pct_fixed=0.01,
    )
    assert int(labeled.loc[30, "long_path_code"]) == TP_FIRST
    assert float(labeled.loc[30, "tp_pct"]) == pytest.approx(0.02)
    assert labeled.loc[30, "entry_rule"] == "next_open"


def test_next_open_gap_through_the_stop_is_a_stop() -> None:
    code = _path_with_fill_gap(
        98.0,
        np.array([104.0]),
        np.array([97.0]),
        102.0,
        99.0,
        short=False,
    )
    assert code == SL_FIRST


def test_close_entry_stays_the_default() -> None:
    frame = _flat(60)
    frame.loc[30, "high"] = 150.0
    labeled = attach_targets(frame, theta=0.5, tp_mult=1.0, sl_mult=1.0)
    assert int(labeled.loc[30, "long_path_code"]) == EXPIRY
    assert labeled.loc[30, "entry_rule"] == "close"


def test_event_mask_leaves_non_events_unlabeled() -> None:
    frame = _flat(60)
    frame.loc[31, "high"] = 103.0
    mask = np.zeros(len(frame), dtype=bool)
    mask[30] = True
    labeled = attach_targets(
        frame,
        theta=None,
        tp_mult=None,
        sl_mult=None,
        entry="next_open",
        tp_pct_fixed=0.02,
        sl_pct_fixed=0.01,
        event_mask=mask,
    )
    assert int(labeled.loc[30, "long_path_code"]) == TP_FIRST
    assert int(labeled.loc[29, "long_path_code"]) == UNLABELED
    assert int(labeled.loc[31, "long_path_code"]) == UNLABELED


def test_cusum_fires_only_past_two_percent() -> None:
    close = np.array([100.0, 100.0 * np.exp(0.019), 100.0 * np.exp(0.019)])
    quiet = cusum_event_mask(close, threshold=0.02)
    assert bool(quiet[1]) is False
    assert bool(quiet[2]) is False
    jump = np.array([100.0, 100.0 * np.exp(0.021)])
    fired = cusum_event_mask(jump, threshold=0.02)
    assert bool(fired[0]) is False
    assert bool(fired[1]) is True
    stacked = np.array([100.0, 100.0 * np.exp(0.011), 100.0 * np.exp(0.022)])
    cumulative = cusum_event_mask(stacked, threshold=0.02)
    assert bool(cumulative[1]) is False
    assert bool(cumulative[2]) is True


def test_embargo_rows_cannot_enter_the_fit() -> None:
    frame = _flat(80)
    epochs = to_epoch_seconds(frame["time"])
    embargo_start = pd.Timestamp(int(epochs[40]), unit="s", tz="UTC")
    embargo_end = pd.Timestamp(int(epochs[60]), unit="s", tz="UTC")
    mask = development_supervised_mask(
        epochs,
        holdout_start=int(epochs[40]),
        bar_length=bar_seconds(),
        horizon_ok=np.ones(len(frame), dtype=bool),
    )
    train = frame.loc[mask].copy()
    assert_development_only(train, embargo_start)
    assert_outside_embargo(train, embargo_start, embargo_end)
    embargoed = frame.iloc[40:50].copy()
    with pytest.raises(RuntimeError, match="embargoed"):
        assert_outside_embargo(embargoed, embargo_start, embargo_end)
    with pytest.raises(RuntimeError, match="holdout"):
        assert_development_only(embargoed, embargo_start)
    confirm = confirmation_mask(epochs, confirmation_start=int(epochs[60]))
    assert bool(confirm[60]) is False
    assert bool(confirm[61]) is True


def test_bootstrap_rejects_a_zero_series() -> None:
    zeros = np.zeros(200, dtype=np.float64)
    means = circular_block_bootstrap_means(zeros, block_length=48, draws=200, seed=42)
    assert float(np.quantile(means, 0.05)) == pytest.approx(0.0)
    decision = confirmation_gate(
        zeros,
        zeros,
        trades=20,
        expectancy=0.01,
        profit_factor=2.0,
        max_drawdown=-0.01,
        block_length=48,
        draws=200,
        seed=42,
        alpha=0.05,
    )
    assert decision["passed"] is False
    assert "bootstrap_not_above_zero" in decision["reasons"]


def test_confirmation_labels_are_not_scored_when_development_fails() -> None:
    candles = _flat(80)
    confirmation = candles.iloc[61:].copy()
    confirmation["bar_index"] = np.arange(61, 80, dtype=np.int64)
    confirmation["tp_pct"] = 0.02
    confirmation["sl_pct"] = 0.01
    confirmation["forward_return_24"] = 0.05
    confirmation["long_path_code"] = TP_FIRST
    confirmation["short_path_code"] = UNLABELED
    report = _maybe_score_confirmation(
        {"gate": {"passed": False, "reasons": ["expectancy_not_positive"]}},
        confirmation,
        candles,
        snapshot_end=pd.Timestamp(candles.loc[60, "time"]),
    )
    assert report["scored"] is False
    assert report["labels_read"] is False
    assert report["reason"] == "expectancy_not_positive"


def test_probability_quintiles_put_better_outcomes_in_the_top_bin() -> None:
    probability = np.array([0.05, 0.08, 0.15, 0.18, 0.45, 0.48, 0.72, 0.75, 0.91, 0.96])
    realized = np.array([-0.012, -0.012, -0.010, -0.010, 0.0, 0.0, 0.010, 0.010, 0.018, 0.018])
    rows = probability_quintiles(probability, realized, bins=5)
    assert len(rows) == 5
    assert rows[0]["mean_realized"] < rows[-1]["mean_realized"]


def test_always_in_expectancy_is_net_of_cost() -> None:
    frame = pd.DataFrame(
        {
            "long_path_code": [TP_FIRST, SL_FIRST],
            "short_path_code": [SL_FIRST, TP_FIRST],
            "tp_pct": [0.02, 0.02],
            "sl_pct": [0.01, 0.01],
            "forward_return_24": [0.0, 0.0],
        }
    )
    stats = always_in_expectancy(frame, cost=0.002)
    # One TP at +1.8% and one stop at -1.2% on each side.
    assert stats["long"] == pytest.approx(0.003)
    assert stats["short"] == pytest.approx(0.003)
    assert stats["average"] == pytest.approx(0.003)


def test_ranking_brier_gate_needs_two_folds() -> None:
    thin = ranking_statistical_gate([0.20, 0.21, 0.22], [0.20, 0.21, 0.22])
    wins = ranking_statistical_gate([0.18, 0.18, 0.22], [0.20, 0.21, 0.22])
    assert thin["passed"] is False
    assert wins["passed"] is True
    assert wins["wins"] == 2


def test_ranking_pipeline_does_not_read_confirmation_labels() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "forecast_30m"
        / "pipeline_v3_ranking.py"
    ).read_text(encoding="utf-8")
    assert "dataset_confirmation" not in source
    assert "phase5_confirmation" not in source
    assert "labels_read" not in source
