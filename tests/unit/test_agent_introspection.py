"""Unit tests for deterministic agent introspection snapshots."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.agent_introspection import (
    INTROSPECTION_VERSION,
    build_introspection_snapshot,
)


@pytest.fixture
def introspection_settings():
    with patch("agent.core.agent_introspection.settings") as mock:
        mock.agent_policy_mode = "ml_and_thesis"
        mock.agent_trade_score_min = 70.0
        mock.require_ic_validation_for_orders = True
        mock.agent_policy_force_hold = False
        yield mock


def test_build_introspection_includes_policy_and_ml_fields(
    introspection_settings,
) -> None:
    snap = build_introspection_snapshot(
        symbol="BTCUSD",
        signal="BUY",
        confidence=0.82,
        policy_reason_codes=["agent_thesis_confirms_ml"],
        ml_evidence_snapshot={
            "ml_candidate_signal": "BUY",
            "thesis_signal": "BUY",
            "trade_score": 78.0,
            "v43_regime": "trend",
        },
        market_context={
            "portfolio_guard": {
                "action": "allow",
                "reason_codes": [],
            },
            "trade_score": {"score": 78.0, "passed": True},
            "ml_validation": {"final_long": True, "final_short": False},
        },
        memory_enabled=True,
        memory_context_count=12,
    )
    d = snap.to_dict()
    assert d["version"] == INTROSPECTION_VERSION
    assert d["symbol"] == "BTCUSD"
    assert d["policy_signal"] == "BUY"
    assert d["trade_score"] == pytest.approx(78.0)
    assert d["trade_score_pass"] is True
    assert d["v43_regime"] == "trend"
    assert d["memory_context_count"] == 12


def test_build_introspection_trade_score_fail(introspection_settings) -> None:
    snap = build_introspection_snapshot(
        symbol="BTCUSD",
        signal="HOLD",
        confidence=0.4,
        trade_score=55.0,
        market_context={
            "ml_validation": {"final_long": False, "final_short": False},
        },
    )
    assert snap.trade_score_pass is False


def test_build_introspection_trade_score_ok_with_gated_ml(
    introspection_settings,
) -> None:
    """Matches orchestrator: score >= min with final_short even if scorer.passed is false."""
    snap = build_introspection_snapshot(
        symbol="BTCUSD",
        signal="SELL",
        confidence=0.3,
        trade_score=93.0,
        policy_reason_codes=["fusion_ml_gated_thesis_neutral"],
        market_context={
            "trade_score": {"score": 93.0, "passed": False},
            "ml_validation": {"final_short": True, "final_long": False},
        },
    )
    assert snap.trade_score_pass is True


def test_build_introspection_trade_score_uses_passed_from_context(
    introspection_settings,
) -> None:
    snap = build_introspection_snapshot(
        symbol="BTCUSD",
        signal="HOLD",
        confidence=0.4,
        trade_score=40.0,
        market_context={
            "trade_score": {"score": 40.0, "passed": True},
            "ml_validation": {"final_long": False, "final_short": False},
        },
    )
    assert snap.trade_score_pass is True
