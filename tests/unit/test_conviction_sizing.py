"""Unit tests for conviction-scaled portfolio margin fraction."""

from __future__ import annotations

from agent.events.handlers.trading_handler import TradingEventHandler


def test_effective_margin_fraction_scales_by_size_fraction(monkeypatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "conviction_scales_portfolio_margin", True)

    base = 0.60
    payload = {
        "policy_verdict": {"size_fraction": 0.5, "position_size": 1.0},
    }
    eff = TradingEventHandler._effective_entry_margin_fraction(base, payload)
    assert eff == 0.3  # 0.60 * 0.5


def test_effective_margin_fraction_disabled_returns_base(monkeypatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "conviction_scales_portfolio_margin", False)

    base = 0.60
    payload = {"policy_verdict": {"size_fraction": 0.5}}
    eff = TradingEventHandler._effective_entry_margin_fraction(base, payload)
    assert eff == 0.60


def test_effective_margin_fraction_uses_position_size_when_no_fraction(monkeypatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "conviction_scales_portfolio_margin", True)

    payload = {"policy_verdict": {"position_size": 0.35}}
    eff = TradingEventHandler._effective_entry_margin_fraction(0.60, payload)
    assert eff == 0.21  # 0.60 * 0.35
