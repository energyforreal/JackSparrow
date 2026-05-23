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
        mock.require_ml_signal_for_orders = True
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
            }
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
    )
    assert snap.trade_score_pass is False
