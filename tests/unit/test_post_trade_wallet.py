"""Tests for wallet-aware post-trade root causes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.intelligence.post_trade_analyzer import analyze_post_trade


def test_funding_dominated_when_wallet_learning_enabled():
    snapshot = {
        "decision_context": {"market_validation": {"validation_score": 80}},
        "execution_timing": {},
        "outcome": {
            "pnl_usd": -2.0,
            "gross_pnl_usd": 1.0,
            "fees_usd": 0.1,
        },
        "wallet_attribution": {
            "funding_usd": -5.0,
            "net_wallet_impact_usd": -5.5,
        },
        "position_monitoring": [],
        "market_structure_timeline": [],
    }
    with patch("agent.intelligence.post_trade_analyzer.settings") as mock_settings:
        mock_settings.wallet_attribution_in_learning_enabled = True
        result = analyze_post_trade(snapshot)
    assert result["root_cause"] == "funding_dominated"


def test_cost_drag_when_gross_positive_net_wallet_negative():
    snapshot = {
        "decision_context": {"market_validation": {"validation_score": 80}},
        "execution_timing": {},
        "outcome": {
            "pnl_usd": 0.5,
            "gross_pnl_usd": 2.0,
            "fees_usd": 0.2,
        },
        "wallet_attribution": {
            "funding_usd": -1.0,
            "net_wallet_impact_usd": -1.5,
        },
        "position_monitoring": [],
        "market_structure_timeline": [],
    }
    with patch("agent.intelligence.post_trade_analyzer.settings") as mock_settings:
        mock_settings.wallet_attribution_in_learning_enabled = True
        result = analyze_post_trade(snapshot)
    assert result["root_cause"] == "cost_drag"
