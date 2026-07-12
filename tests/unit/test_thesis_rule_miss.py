"""Tests for thesis rule miss diagnostics and neutral mild trend prototype."""

from unittest.mock import patch

from agent.core.agent_thesis_engine import AgentThesisEngine


def test_diagnose_rule_miss_breakout_adx_gap() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 20.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": 0.01,
        "bb_pos": 0.5,
    }
    misses = engine.diagnose_rule_miss(features, "neutral")
    blockers = {m.blocker for m in misses if m.rule == "breakout"}
    assert "adx_14" in blockers


def test_nearest_rule_miss_picks_smallest_gap() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 24.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": 0.01,
        "bb_pos": 0.5,
        "h1_trend": 0.002,
        "hurst_60": 0.55,
        "rsi_14": 50.0,
    }
    nearest = engine.nearest_rule_miss(features, "neutral")
    assert nearest is not None
    assert nearest.gap <= 1.0


def test_diagnose_aligns_h_trend_with_live_sign_gate() -> None:
    """Small positive h_trend passes live h>0; must not dominate nearest-miss."""
    engine = AgentThesisEngine()
    features = {
        "adx_14": 30.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": 0.0006,
        "bb_pos": 0.5,
        "h1_trend": 0.002,
        "hurst_60": 0.0,
        "rsi_14": 50.0,
    }
    misses = engine.diagnose_rule_miss(features, "neutral")
    trend_blockers = {m.blocker for m in misses if m.rule == "trend_continuation"}
    assert "h_trend" not in trend_blockers
    assert "hurst_60" in trend_blockers
    nearest = engine.nearest_rule_miss(
        features, "neutral", directions=["LONG"]
    )
    assert nearest is not None
    assert nearest.blocker == "hurst_60"


def test_diagnose_flags_non_positive_h_trend() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 30.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": -0.0002,
        "bb_pos": 0.5,
        "h1_trend": 0.002,
        "hurst_60": 0.55,
        "rsi_14": 50.0,
    }
    misses = engine.diagnose_rule_miss(features, "neutral")
    assert any(
        m.rule == "trend_continuation" and m.blocker == "h_trend" for m in misses
    )


def test_neutral_mild_trend_disabled_by_default() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 18.0,
        "h1_trend": 0.01,
        "h_trend": 0.005,
    }
    verdict = engine._eval_neutral_mild_trend_long(features, "neutral")
    assert verdict is not None
    assert verdict.thesis_type == "trend_continuation"

    candidates = engine.collect_all_rule_verdicts(
        features, "neutral", short_enabled=True
    )
    assert not any(v.reason_codes[0] == "thesis_neutral_mild_trend_long" for v in candidates)


def test_neutral_mild_trend_enabled_when_flag_on() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 18.0,
        "h1_trend": 0.01,
        "h_trend": 0.005,
    }
    with patch("agent.core.agent_thesis_engine.settings") as mock_settings:
        mock_settings.agent_thesis_neutral_mild_trend_enabled = True
        mock_settings.agent_thesis_breakout_enabled = True
        mock_settings.agent_thesis_trend_enabled = True
        mock_settings.agent_thesis_mean_reversion_enabled = False
        mock_settings.agent_thesis_neutral_mild_trend_adx_max = 22.0
        candidates = engine.collect_all_rule_verdicts(
            features, "neutral", short_enabled=True
        )
    assert any(
        "thesis_neutral_mild_trend_long" in v.reason_codes for v in candidates
    )


def test_thesis_hurst_v2_flag_reads_v2_feature() -> None:
    engine = AgentThesisEngine()
    features = {
        "h1_trend": 0.01,
        "h_trend": 0.005,
        "rsi_14": 50.0,
        "hurst_60": 0.0,
        "hurst_60_v2": 0.58,
    }
    with patch("agent.core.agent_thesis_engine.settings") as mock_settings:
        mock_settings.agent_thesis_use_hurst_v2 = False
        mock_settings.agent_thesis_trend_rsi_lo = 40.0
        mock_settings.agent_thesis_trend_rsi_hi = 65.0
        mock_settings.agent_thesis_trend_hurst_min = 0.52
        assert engine._eval_trend_continuation_long(features, "neutral") is None

        mock_settings.agent_thesis_use_hurst_v2 = True
        verdict = engine._eval_trend_continuation_long(features, "neutral")
    assert verdict is not None
    assert any(c.startswith("hurst_60_v2=") for c in verdict.reason_codes)
