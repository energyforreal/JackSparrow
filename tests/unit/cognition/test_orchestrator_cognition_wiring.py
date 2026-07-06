"""Regression: cognition outputs must reach thesis before evidence/policy."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.core.agent_thesis_engine import get_last_hypothesis_snapshot
from agent.core.cognition_orchestration import (
    attach_cognition,
    evaluate_thesis_from_context,
    populate_rule_based_context,
)


def _breakout_features() -> dict[str, float]:
    return {
        "adx_14": 30.0,
        "di_spread": 8.0,
        "vol_regime": 1.25,
        "h_trend": 0.02,
        "rsi_14": 55.0,
        "hurst_60": 0.55,
        "h1_trend": 0.01,
        "atr_pct": 0.02,
    }


def _v43_handler_source() -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "agent" / "core" / "mcp_orchestrator.py").read_text(encoding="utf-8")


def _handler_body(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(_v43_handler_source())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == name:
                    return item
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _first_line(node: ast.AST, attr: str) -> int:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == attr:
                return child.lineno
            if isinstance(func, ast.Name) and func.id == attr:
                return child.lineno
    return -1


def test_v43_handler_cognition_before_evidence_graph() -> None:
    body = _handler_body("_process_jacksparrow_v43_prediction")
    attach_line = -1
    graph_line = -1
    for child in ast.walk(body):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            if func.id == "attach_cognition":
                attach_line = child.lineno
            if func.id == "build_evidence_stack":
                graph_line = child.lineno
        elif isinstance(func, ast.Attribute) and func.attr == "build_evidence_stack":
            graph_line = child.lineno
    assert attach_line > 0, "attach_cognition missing from v43 handler"
    assert graph_line > 0, "build_evidence_stack missing from v43 handler"
    assert attach_line < graph_line


def test_v43_handler_cognition_before_policy_evaluate() -> None:
    body = _handler_body("_process_jacksparrow_v43_prediction")
    attach_line = -1
    policy_line = -1
    for child in ast.walk(body):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id == "attach_cognition":
            attach_line = child.lineno
        if isinstance(func, ast.Attribute) and func.attr == "evaluate":
            base = func.value
            if isinstance(base, ast.Name) and base.id == "agent_policy_engine":
                policy_line = child.lineno
    assert attach_line > 0
    assert policy_line > 0
    assert attach_line < policy_line


@patch("agent.core.cognition_orchestration.cognition_cycle_enabled", return_value=True)
@patch("agent.core.cognition_orchestration.attach_decision_context_v3")
@patch("agent.core.agent_thesis_engine.hypothesis_portfolio_mode", return_value=True)
@patch("agent.core.agent_thesis_engine.settings")
def test_cognition_selector_reaches_thesis_evaluate(
    mock_settings: MagicMock,
    _portfolio: MagicMock,
    mock_attach: MagicMock,
    _cycle: MagicMock,
) -> None:
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_trend_enabled = True
    mock_settings.agent_thesis_mean_reversion_enabled = False
    mock_settings.agent_thesis_crisis_veto = True
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5
    mock_settings.agent_thesis_breakout_adx_min = 25.0
    mock_settings.agent_thesis_breakout_di_min = 5.0
    mock_settings.agent_thesis_breakout_vol_regime_min = 1.1
    mock_settings.jacksparrow_v43_max_position_pct = 0.1
    mock_settings.cognition_selector_enabled = True

    def _attach(mc: dict) -> dict:
        mc["decision_context_v3"] = {"meta": {"schema_version": "3.0"}}
        mc["eligible_strategy_profiles"] = ["breakout"]
        mc["strategy_scores"] = {
            "entries": [{"profile_id": "breakout", "adjusted_confidence": 0.8}],
        }
        return mc

    mock_attach.side_effect = _attach

    mc: dict = {
        "symbol": "BTCUSD",
        "v43_closed_bar_index": 42,
        "features": _breakout_features(),
        "regime": "neutral",
        "has_open_position": False,
        "rule_based_pipeline": {
            "market_state": {
                "symbol": "BTCUSD",
                "bar_index": 42,
                "trend": "bullish",
                "trend_strength": "moderate",
                "momentum": "increasing",
                "volatility": "stable",
                "regime": "neutral",
            }
        },
    }

    attach_cognition(mc)
    evaluate_thesis_from_context("neutral", mc)

    assert mc.get("eligible_strategy_profiles") == ["breakout"]
    snap = get_last_hypothesis_snapshot()
    assert snap.get("dominant") is not None
    dominant = snap["dominant"]
    assert dominant.get("thesis_type") == "breakout"
    assert "hypothesis_no_rule_fired" not in (snap.get("reason_codes") or [])


@patch("agent.core.cognition_orchestration.rule_based_pipeline")
def test_populate_rule_based_skips_when_already_present(mock_rb: MagicMock) -> None:
    mc = {"rule_based_pipeline": {"fsm_decision": {"entry_signal": "HOLD"}}}
    out = populate_rule_based_context(
        mc,
        symbol="BTCUSD",
        bar_index=1,
        features={},
        regime="neutral",
        structure=MagicMock(),
        thesis_signal="HOLD",
        thesis_type="flat",
        has_open_position=False,
        gate_state=None,
        contract_state=None,
        skip_if_populated=True,
    )
    assert out is mc
    mock_rb.run_cycle.assert_not_called()
