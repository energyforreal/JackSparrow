"""Unit tests for v43 horizon alignment helpers."""

from __future__ import annotations

import pytest

from feature_store.jacksparrow_v43_horizon import (
    V43_FORWARD_TARGET_BARS_DEFAULT,
    build_execution_profile,
    forward_bars_to_minutes,
    horizon_profile,
    horizons_compatible,
    resolve_training_forward_bars,
    thesis_intended_forward_bars,
    validate_metadata_forward_bars,
)


def test_forward_bars_to_minutes() -> None:
    assert forward_bars_to_minutes(6) == 30
    assert forward_bars_to_minutes(24) == 120


def test_resolve_training_forward_bars_from_meta() -> None:
    assert resolve_training_forward_bars({"primary_execution_horizon_bars": 2}) == 2
    assert resolve_training_forward_bars({"primary_execution_horizon_bars": 6}) == 6
    assert resolve_training_forward_bars({"training_forward_bars": 6}) == 6


def test_horizon_profile_intraday_30m() -> None:
    prof = horizon_profile(6)
    assert prof.label == "intraday_30m"
    assert prof.trade_debounce_bars == 2
    assert prof.max_position_hold_hours == 1.5


def test_horizon_profile_swing_2h() -> None:
    prof = horizon_profile(24)
    assert prof.trade_debounce_bars == 6
    assert prof.max_position_hold_hours == 4.0


def test_build_execution_profile_enabled() -> None:
    prof = build_execution_profile(6, align=True)
    assert prof["enabled"] is True
    assert prof["forward_bars"] == 6
    assert prof["horizon_minutes"] == 30


def test_thesis_horizon_mapping() -> None:
    assert thesis_intended_forward_bars("mean_reversion") == 2
    assert thesis_intended_forward_bars("trend_continuation") == 6
    assert thesis_intended_forward_bars("breakout") == 12


def test_horizons_compatible_strict() -> None:
    assert horizons_compatible(6, 6, strict=True)
    assert not horizons_compatible(6, 12, strict=True)


def test_validate_metadata_forward_bars_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="not in"):
        validate_metadata_forward_bars({"training_forward_bars": 99})


def test_default_training_bars_is_scalp_10m() -> None:
    assert V43_FORWARD_TARGET_BARS_DEFAULT == 2


def test_resolve_training_forward_bars_scalp_primary() -> None:
    assert resolve_training_forward_bars({"primary_execution_horizon_bars": 2}) == 2
