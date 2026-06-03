"""Tests for IC micro-momentum expected_return fallback."""

from __future__ import annotations

import pytest

from agent.core import config as config_mod
from agent.intelligence.ic_micro_signal import (
    apply_ic_micro_momentum_er,
    micro_expected_return_from_features,
)


def test_micro_er_positive_on_bullish_ret() -> None:
    er = micro_expected_return_from_features(
        {"ret_1": 0.002, "trend_mom": 0.001},
        threshold=0.005,
        short_enabled=True,
    )
    assert er > 0.005


def test_micro_er_zero_when_flat_features() -> None:
    er = micro_expected_return_from_features({}, threshold=0.005, short_enabled=True)
    assert er == 0.0


def test_apply_only_for_hold_thesis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ic_mode", True)
    monkeypatch.setattr(config_mod.settings, "ic_micro_momentum_enabled", True)
    er = apply_ic_micro_momentum_er(
        "BUY",
        0.012,
        {"ret_1": 0.01},
        threshold=0.005,
        short_enabled=True,
    )
    assert er == 0.012


def test_apply_replaces_zero_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ic_mode", True)
    monkeypatch.setattr(config_mod.settings, "ic_micro_momentum_enabled", True)
    er = apply_ic_micro_momentum_er(
        "HOLD",
        0.0,
        {"ret_1": 0.003, "trend_mom": 0.002},
        threshold=0.005,
        short_enabled=True,
    )
    assert er > 0.007
