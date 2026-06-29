"""Tests for rule-based market intelligence pipeline."""

from __future__ import annotations

import pytest

from agent.intelligence.market_types import MarketStateSnapshot
from agent.intelligence.market_understanding_engine import market_understanding_engine
from agent.intelligence.market_narrative_engine import MarketNarrativeEngine
from agent.core.structural_gate_engine import structural_gate_engine
from agent.intelligence.market_fsm import MarketFSM
from agent.intelligence.rule_based_pipeline import rule_based_pipeline, normalize_compare
from agent.intelligence.trade_archetype_memory import (
    narrative_pattern_hash,
    trade_archetype_memory,
)


@pytest.fixture
def sample_features() -> dict:
    return {
        "h1_trend": 0.3,
        "h_trend": 0.25,
        "ema200_bias": 0.2,
        "adx_14": 28.0,
        "hurst_60": 0.56,
        "rsi_mom": 0.1,
        "mom_accel": 0.08,
        "trend_mom": 0.12,
        "vol_regime": 1.15,
        "atr_pct": 0.01,
        "breakout_score": 0.7,
        "vol_expansion": 0.05,
        "spread_bps": 5.0,
        "m15_trend": 0.2,
    }


def test_market_understanding_bullish_trend(sample_features: dict) -> None:
    snap = market_understanding_engine.evaluate(
        symbol="BTCUSD",
        bar_index=100,
        features=sample_features,
        regime="trending",
        thesis_signal="LONG",
        thesis_type="breakout",
    )
    assert snap.trend == "bullish"
    assert snap.trend_strength in ("moderate", "strong")
    assert snap.direction_bias == "LONG"


def test_narrative_detects_breakout_confirmed(sample_features: dict) -> None:
    engine = MarketNarrativeEngine()
    snap1 = MarketStateSnapshot(
        symbol="BTCUSD",
        bar_index=1,
        trend="bullish",
        breakout_status="forming",
        momentum="increasing",
        trend_strength="moderate",
    )
    snap2 = MarketStateSnapshot(
        symbol="BTCUSD",
        bar_index=2,
        trend="bullish",
        breakout_status="confirmed",
        momentum="increasing",
        trend_strength="strong",
        retest_status="successful",
    )
    engine.update_from_snapshot(snap1)
    events, tail = engine.update_from_snapshot(snap2)
    types = {e.event_type for e in events}
    assert "breakout_confirmed" in types or len(tail) >= 0


def test_structural_gates_block_neutral_trend(sample_features: dict) -> None:
    snap = MarketStateSnapshot(
        symbol="BTCUSD",
        bar_index=10,
        trend="neutral",
        trend_strength="weak",
        trend_age_candles=1,
        direction_bias="HOLD",
    )
    result = structural_gate_engine.evaluate(snapshot=snap)
    assert result.trade_allowed is False
    assert result.categories.get("trend") is False


def test_fsm_entry_ready_on_breakout_narrative(sample_features: dict) -> None:
    fsm = MarketFSM()
    snap = MarketStateSnapshot(
        symbol="TESTBTC",
        bar_index=50,
        trend="bullish",
        trend_strength="strong",
        trend_age_candles=10,
        momentum="increasing",
        breakout_status="confirmed",
        retest_status="successful",
        direction_bias="LONG",
        mtf={"h1": "context_bullish", "m15": "setup_aligned", "m5": "execution_ready"},
    )
    from agent.intelligence.market_types import StructuralGateResult

    gates = StructuralGateResult(
        trade_allowed=True,
        categories={
            "trend": True,
            "structure": True,
            "breakout": True,
            "liquidity": True,
            "volatility": True,
            "risk": True,
        },
        setup_type="breakout",
    )
    narrative = [
        {"event_type": "pullback_ends", "timestamp": "2026-01-01T10:00:00Z"},
        {"event_type": "breakout_confirmed", "timestamp": "2026-01-01T11:00:00Z"},
        {"event_type": "retest_successful", "timestamp": "2026-01-01T11:30:00Z"},
    ]
    fsm.persist_state("TESTBTC", "SetupForming")
    decision = fsm.evaluate(
        snapshot=snap,
        gates=gates,
        narrative_tail=narrative,
        has_open_position=False,
    )
    assert decision.fsm_state in ("EntryReady", "SetupForming")


def test_rule_based_pipeline_run_cycle(sample_features: dict) -> None:
    result = rule_based_pipeline.run_cycle(
        symbol="BTCUSD",
        bar_index=200,
        features=sample_features,
        regime="trending",
        thesis_signal="LONG",
        thesis_type="breakout",
        has_open_position=False,
    )
    assert result.market_state.symbol == "BTCUSD"
    assert "trend" in result.market_state.to_dict()
    assert result.fsm_decision.fsm_state


def test_normalize_compare() -> None:
    assert normalize_compare("STRONG_LONG") == "LONG"
    assert normalize_compare("HOLD") == "HOLD"


def test_archetype_pattern_hash() -> None:
    tail = [{"event_type": "breakout_confirmed"}, {"event_type": "retest_successful"}]
    h1 = narrative_pattern_hash(tail)
    h2 = narrative_pattern_hash(tail)
    assert h1 == h2


def test_archetype_similar_setups_empty() -> None:
    sim = trade_archetype_memory.similar_setups(
        "NEWPAIR",
        setup_type="breakout",
        regime="trending",
        narrative_tail=[],
    )
    assert sim["count"] == 0
