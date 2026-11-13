"""Engine A candidates include rejects and neutrals."""

from __future__ import annotations

from research.swinging.contract import FORBIDDEN_FEATURE_COLUMNS
from research.swinging.setups import generate_setups, screen_indices
from tests.unit.swinging_fixtures import make_ohlcv


def test_screen_keeps_a_neutral_sample() -> None:
    frame = make_ohlcv(40)
    indexes = screen_indices(frame, warmup=20, neutral_stride=4, lookback=10)
    assert indexes
    assert indexes[0] >= 20


def test_generate_setups_keeps_non_winners_and_feature_columns() -> None:
    frame = make_ohlcv(48, drift=0.2)
    setups = generate_setups(frame, "5m", indexes=[36])
    assert not setups.empty
    assert set(setups["status"]).issubset({"accepted", "rejected", "neutral"})
    assert "breakout_status" not in setups.columns
    assert FORBIDDEN_FEATURE_COLUMNS.isdisjoint(setups.columns)
    assert setups["setup_id"].is_unique
    assert int(setups["bar_index"].iloc[0]) == 36
