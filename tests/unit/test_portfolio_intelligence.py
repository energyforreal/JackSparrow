"""Unit tests for portfolio intelligence guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.portfolio_intelligence import (
    PortfolioExposureSnapshot,
    PortfolioPositionRow,
    apply_portfolio_guard_to_verdict,
    evaluate_portfolio_guard,
)
from agent.events.schemas import PolicyVerdict


def _snap(
    equity: float = 10000.0,
    positions=None,
) -> PortfolioExposureSnapshot:
    return PortfolioExposureSnapshot(
        portfolio_equity_usd=equity,
        positions=positions or [],
        source="test",
    )


@pytest.fixture
def portfolio_enabled_no_shadow():
    with patch("agent.core.portfolio_intelligence.settings") as mock:
        mock.portfolio_intelligence_enabled = True
        mock.portfolio_intelligence_shadow_mode = False
        mock.portfolio_intelligence_reduce_enabled = True
        mock.portfolio_intelligence_block_enabled = True
        mock.portfolio_max_heat_ratio = 0.85
        mock.portfolio_max_same_side_concentration = 0.70
        mock.portfolio_max_correlation_group_fraction = 0.55
        mock.portfolio_near_limit_size_factor = 0.50
        mock.portfolio_near_limit_band = 0.08
        mock.portfolio_correlation_groups_json = (
            '{"crypto_major":["BTCUSD","ETHUSD"]}'
        )
        yield mock


def test_guard_blocks_when_heat_exceeds_cap(portfolio_enabled_no_shadow) -> None:
    snap = _snap(
        10000.0,
        [PortfolioPositionRow("BTCUSD", "LONG", 8000.0)],
    )
    guard = evaluate_portfolio_guard(
        snap,
        symbol="ETHUSD",
        proposed_signal="BUY",
        proposed_size_fraction=0.10,
    )
    assert guard.action == "block"
    assert "portfolio_heat_cap" in " ".join(guard.reason_codes)


def test_guard_reduces_size_when_near_heat_cap(portfolio_enabled_no_shadow) -> None:
    snap = _snap(
        10000.0,
        [PortfolioPositionRow("BTCUSD", "LONG", 7200.0)],
    )
    guard = evaluate_portfolio_guard(
        snap,
        symbol="ETHUSD",
        proposed_signal="BUY",
        proposed_size_fraction=0.10,
    )
    assert guard.action in ("reduce_size", "block")
    if guard.action == "reduce_size":
        assert guard.allowed_size_fraction < 0.10


def test_guard_blocks_same_side_concentration(portfolio_enabled_no_shadow) -> None:
    snap = _snap(
        10000.0,
        [
            PortfolioPositionRow("BTCUSD", "LONG", 5000.0),
            PortfolioPositionRow("ETHUSD", "LONG", 4000.0),
        ],
    )
    guard = evaluate_portfolio_guard(
        snap,
        symbol="BTCUSD",
        proposed_signal="BUY",
        proposed_size_fraction=0.05,
    )
    assert guard.action == "block"
    assert any("portfolio_side_concentration" in r for r in guard.reason_codes)


def test_guard_correlation_group_blocks_additional_crypto_major(
    portfolio_enabled_no_shadow,
) -> None:
    snap = _snap(
        10000.0,
        [PortfolioPositionRow("BTCUSD", "LONG", 5000.0)],
    )
    guard = evaluate_portfolio_guard(
        snap,
        symbol="ETHUSD",
        proposed_signal="BUY",
        proposed_size_fraction=0.10,
    )
    assert guard.action in ("reduce_size", "block")
    assert guard.correlation_group == "crypto_major"


def test_shadow_mode_does_not_enforce_block(portfolio_enabled_no_shadow) -> None:
    with patch("agent.core.portfolio_intelligence.settings") as mock:
        mock.portfolio_intelligence_enabled = True
        mock.portfolio_intelligence_shadow_mode = True
        mock.portfolio_intelligence_reduce_enabled = True
        mock.portfolio_intelligence_block_enabled = True
        mock.portfolio_max_heat_ratio = 0.10
        mock.portfolio_max_same_side_concentration = 0.70
        mock.portfolio_max_correlation_group_fraction = 0.55
        mock.portfolio_near_limit_size_factor = 0.50
        mock.portfolio_near_limit_band = 0.08
        mock.portfolio_correlation_groups_json = "{}"
        snap = _snap(10000.0, [PortfolioPositionRow("BTCUSD", "LONG", 9000.0)])
        guard = evaluate_portfolio_guard(
            snap,
            symbol="ETHUSD",
            proposed_signal="BUY",
            proposed_size_fraction=0.10,
        )
    assert guard.action == "allow"
    assert guard.shadow_only is True


def test_apply_guard_blocks_verdict_to_hold() -> None:
    verdict = PolicyVerdict(
        signal="BUY",
        confidence=0.8,
        position_size=0.05,
        reason_codes=["fusion_ml_and_thesis_agree"],
        adopted_ml_candidate=True,
    )
    from agent.core.portfolio_intelligence import PortfolioGuardDecision

    guard = PortfolioGuardDecision(
        action="block",
        allowed_size_fraction=0.0,
        heat_ratio=1.2,
        side_concentration_ratio=0.9,
        reason_codes=["portfolio_heat_cap"],
    )
    out = apply_portfolio_guard_to_verdict(verdict, guard, symbol="BTCUSD")
    assert out.signal == "HOLD"
    assert out.position_size == 0.0
    assert out.adopted_ml_candidate is False


def test_apply_guard_reduces_position_size() -> None:
    verdict = PolicyVerdict(
        signal="STRONG_BUY",
        confidence=0.9,
        position_size=0.10,
        reason_codes=[],
        adopted_ml_candidate=True,
    )
    from agent.core.portfolio_intelligence import PortfolioGuardDecision

    guard = PortfolioGuardDecision(
        action="reduce_size",
        allowed_size_fraction=0.04,
        heat_ratio=0.82,
        side_concentration_ratio=0.6,
        reason_codes=["portfolio_heat_near_cap"],
    )
    out = apply_portfolio_guard_to_verdict(verdict, guard, symbol="BTCUSD")
    assert out.signal == "STRONG_BUY"
    assert out.position_size == pytest.approx(0.04)
