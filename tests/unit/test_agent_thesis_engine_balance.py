"""Thesis engine must not always prefer long rules when short also qualifies."""

from __future__ import annotations

from unittest.mock import patch

from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict


def test_select_best_thesis_conflict_returns_hold() -> None:
    long_v = ThesisVerdict(
        signal="BUY",
        confidence=0.7,
        position_size=0.0,
        reason_codes=["thesis_breakout_long"],
        thesis_type="breakout",
    )
    short_v = ThesisVerdict(
        signal="SELL",
        confidence=0.68,
        position_size=0.0,
        reason_codes=["thesis_breakout_short"],
        thesis_type="breakout",
    )
    out = AgentThesisEngine._select_best_thesis(
        [long_v, short_v],
        pos_size=0.05,
        regime="neutral",
    )
    assert out.signal == "HOLD"
    assert "thesis_direction_conflict" in out.reason_codes


def test_collect_candidates_includes_short_when_enabled() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 30.0,
        "di_spread": -8.0,
        "vol_regime": 1.2,
        "h_trend": -1.0,
        "h1_trend": -0.5,
        "h_trend_200": -0.3,
        "rsi_14": 55.0,
        "hurst_60": 0.55,
    }
    with patch(
        "agent.core.agent_thesis_engine.settings"
    ) as mock_settings:
        mock_settings.agent_thesis_breakout_enabled = True
        mock_settings.agent_thesis_trend_enabled = False
        mock_settings.agent_thesis_mean_reversion_enabled = False
        mock_settings.agent_thesis_breakout_adx_min = 25.0
        mock_settings.agent_thesis_breakout_di_min = 5.0
        mock_settings.agent_thesis_breakout_vol_regime_min = 1.1
        mock_settings.jacksparrow_v43_short_execution_enabled = True
        candidates = engine._collect_thesis_candidates(
            features,
            "neutral",
            {"breakout", "trend_continuation"},
            short_enabled=True,
        )
    signals = {c.signal for c in candidates}
    assert "SELL" in signals or "STRONG_SELL" in signals
