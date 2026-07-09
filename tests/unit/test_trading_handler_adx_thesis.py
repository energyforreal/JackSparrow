"""Unit tests for thesis-aware ADX helpers in trading_handler."""

from __future__ import annotations

import pytest

from agent.events.handlers import trading_handler as th


def test_adx_high_cap_applies_default_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(th.settings, "v15_adx_thesis_aware_enabled", False)
    assert th._adx_high_cap_applies("breakout") is True
    assert th._adx_high_cap_applies("mean_reversion") is True


def test_adx_high_cap_skips_trend_thesis_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(th.settings, "v15_adx_thesis_aware_enabled", True)
    assert th._adx_high_cap_applies("breakout") is False
    assert th._adx_high_cap_applies("trend_continuation") is False
    assert th._adx_high_cap_applies("mean_reversion") is True
    assert th._adx_high_cap_applies("flat") is True


def test_entry_thesis_type_from_policy_verdict() -> None:
    tt = th._entry_thesis_type(
        {},
        {"policy_verdict": {"reason_codes": ["thesis_type=breakout", "other"]}},
    )
    assert tt == "breakout"
