"""Leakage, allow-list, and purge guards for CPR-MTF."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.cpr_mtf.__main__ import main, run_preview
from research.cpr_mtf.contract import (
    MODEL_CANDIDATE_FEATURES,
    PROPOSAL_ONLY_FIELDS,
    PURGE_BARS,
    SEQUENCE_CHANNELS,
)
from research.cpr_mtf.integrity import assert_causal_at, assert_feature_names
from research.cpr_mtf.splits import purged_split
from research.cpr_mtf.swings import swings_on_chart
from research.cpr_mtf.windows import prepare_timeframe
from tests.unit.cpr_mtf_support import piecewise_closes, series_from_closes


def test_sequence_allow_list_rejects_rule_flags_and_proposal_fields() -> None:
    """Pattern-rule names and proposal scores cannot enter the sequence tensor."""
    assert len(SEQUENCE_CHANNELS) == 20
    assert len(MODEL_CANDIDATE_FEATURES) == 22
    assert_feature_names(SEQUENCE_CHANNELS)
    for name in PROPOSAL_ONLY_FIELDS:
        assert name not in SEQUENCE_CHANNELS
        assert name not in MODEL_CANDIDATE_FEATURES
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(["close_atr", "chp_double_top"])
    with pytest.raises(ValueError, match="leak"):
        assert_feature_names(["candidate_type_proposal"])
    with pytest.raises(ValueError, match="allow-list"):
        assert_feature_names(["formation_width_bars"])


def test_future_bars_do_not_change_features_swings_or_candidates() -> None:
    """Scaling OHLC after ``t`` leaves the causal outputs at ``t`` unchanged."""
    closes = piecewise_closes(
        [
            (70, 100.0),
            (12, 120.0),
            (12, 100.0),
            (12, 120.0),
            (12, 100.0),
        ]
    )
    frame = series_from_closes(closes)
    assert_causal_at(frame, "15m", len(frame) - 5)


def test_partition_gap_is_the_four_hour_label_horizon() -> None:
    """Train, validation, and test stay 384 fifteen-minute bars apart."""
    split = purged_split(np.arange(20_000, dtype=np.int64))
    assert int(split["val"][0]) - int(split["train"][-1]) >= PURGE_BARS
    assert int(split["test"][0]) - int(split["val"][-1]) >= PURGE_BARS
    assert PURGE_BARS == 24 * 16


def test_chart_marks_only_swings_confirmed_inside_the_window(tmp_path: Path) -> None:
    """A pivot that is not yet confirmed is absent from the preview."""
    from research.cpr_mtf.plots import save_preview

    closes = 100.0 + np.cumsum(np.random.default_rng(1).normal(0.0, 0.3, 250))
    frame = series_from_closes(closes)
    prepared = prepare_timeframe(frame, "15m")
    asof = 220
    drawn = save_preview(
        prepared.frame,
        prepared.swings,
        [],
        asof,
        "15m",
        tmp_path / "preview.png",
    )
    assert (tmp_path / "preview.png").stat().st_size > 0
    assert drawn == swings_on_chart(prepared.swings, asof, asof - 191)
    assert all(swing.confirmation_index <= asof for swing in drawn)
    assert all(swing.pivot_index >= asof - 191 for swing in drawn)


def test_missing_parquet_exits_without_downloading(tmp_path: Path) -> None:
    """The preview command stops when the 5-minute file is absent."""
    status = main(["--source", str(tmp_path / "missing.parquet")])
    assert status == 1


def test_preview_writes_an_audit_for_a_complete_history(tmp_path: Path) -> None:
    """A history long enough for the 4-hour window produces one valid sample."""
    raw = _five_minute_walk(periods=240 * 48)
    audit = run_preview(raw, tmp_path, samples=1)
    assert audit["data_quality"] == "valid"
    assert audit["samples"][0]["windows"]["4h"] == [192, 20]
    assert list(tmp_path.glob("preview/*.png"))
    saved = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert saved["spec_version"] == audit["spec_version"]


def _five_minute_walk(periods: int) -> pd.DataFrame:
    """Deterministic 5-minute path with wicks, aligned to midnight UTC."""
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.15, periods))
    open_ = np.empty(periods, dtype=np.float64)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=periods, freq="5min", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) + 0.2,
            "low": np.minimum(open_, close) - 0.2,
            "close": close,
            "volume": np.full(periods, 4.0),
        }
    )
