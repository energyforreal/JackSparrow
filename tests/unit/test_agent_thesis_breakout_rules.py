"""Breakout extension rules in agent thesis engine."""

from agent.core.agent_thesis_engine import AgentThesisEngine


def test_breakout_long_rejects_extended_bb_pos() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 35.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": 0.01,
        "bb_pos": 0.92,
    }
    verdict = engine._eval_breakout_long(features, "trending")
    assert verdict is None


def test_breakout_long_allows_fresh_extension() -> None:
    engine = AgentThesisEngine()
    features = {
        "adx_14": 35.0,
        "di_spread": 10.0,
        "vol_regime": 1.2,
        "h_trend": 0.01,
        "bb_pos": 0.72,
    }
    verdict = engine._eval_breakout_long(features, "trending")
    assert verdict is not None
    assert verdict.signal == "LONG"
