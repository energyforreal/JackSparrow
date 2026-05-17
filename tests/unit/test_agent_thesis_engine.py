"""Unit tests for rule-based agent thesis engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.core.agent_thesis_engine import AgentThesisEngine


def _breakout_features() -> dict:
    return {
        "adx_14": 30.0,
        "di_spread": 8.0,
        "vol_regime": 1.25,
        "h_trend": 0.02,
        "rsi_14": 55.0,
        "hurst_60": 0.55,
        "h1_trend": 0.01,
    }


def _trend_features() -> dict:
    return {
        "adx_14": 22.0,
        "di_spread": 3.0,
        "vol_regime": 1.0,
        "h_trend": 0.015,
        "h1_trend": 0.012,
        "rsi_14": 52.0,
        "hurst_60": 0.56,
    }


@patch("agent.core.agent_thesis_engine.settings")
def test_breakout_long_fires(mock_settings) -> None:
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_trend_enabled = True
    mock_settings.agent_thesis_crisis_veto = True
    mock_settings.agent_thesis_mean_reversion_enabled = False
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5
    mock_settings.agent_thesis_breakout_adx_min = 25.0
    mock_settings.agent_thesis_breakout_di_min = 5.0
    mock_settings.agent_thesis_breakout_vol_regime_min = 1.1
    mock_settings.jacksparrow_v43_max_position_pct = 0.1

    engine = AgentThesisEngine()
    v = engine.evaluate("neutral", {"features": _breakout_features()})
    assert v.signal == "BUY"
    assert v.thesis_type == "breakout"
    assert "thesis_breakout_long" in v.reason_codes


@patch("agent.core.agent_thesis_engine.settings")
def test_crisis_regime_forces_hold(mock_settings) -> None:
    mock_settings.agent_thesis_crisis_veto = True
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5

    engine = AgentThesisEngine()
    v = engine.evaluate("crisis", {"features": _breakout_features()})
    assert v.signal == "HOLD"
    assert v.thesis_type == "crisis_veto"


@patch("agent.core.agent_thesis_engine.settings")
def test_trending_regime_uses_trend_not_breakout(mock_settings) -> None:
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_trend_enabled = True
    mock_settings.agent_thesis_crisis_veto = True
    mock_settings.agent_thesis_mean_reversion_enabled = False
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5
    mock_settings.agent_thesis_breakout_adx_min = 25.0
    mock_settings.agent_thesis_trend_rsi_lo = 40.0
    mock_settings.agent_thesis_trend_rsi_hi = 65.0
    mock_settings.agent_thesis_trend_hurst_min = 0.52
    mock_settings.jacksparrow_v43_max_position_pct = 0.1

    engine = AgentThesisEngine()
    v = engine.evaluate("trending", {"features": _trend_features()})
    assert v.signal == "BUY"
    assert v.thesis_type == "trend_continuation"


@patch("agent.core.agent_thesis_engine.settings")
def test_open_position_blocks_thesis(mock_settings) -> None:
    mock_settings.agent_thesis_breakout_enabled = True
    mock_settings.agent_thesis_squeeze_veto_threshold = 0.5

    engine = AgentThesisEngine()
    v = engine.evaluate(
        "neutral",
        {"features": _breakout_features(), "has_open_position": True},
    )
    assert v.signal == "HOLD"
    assert "thesis_open_position" in v.reason_codes
