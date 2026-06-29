"""Scenario-style tests for rule-based narrative sequences (plan phase 8)."""

from __future__ import annotations

from agent.intelligence.market_fsm import MarketFSM
from agent.intelligence.market_narrative_engine import MarketNarrativeEngine
from agent.intelligence.market_types import MarketStateSnapshot, StructuralGateResult
from agent.intelligence.rule_based_pipeline import rule_based_pipeline


def _bullish_features(**overrides: float) -> dict:
    base = {
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
        "pullback_depth": 0.01,
    }
    base.update(overrides)
    return base


def test_scenario_breakout_retest_entry_ready() -> None:
    """Pullback -> compression -> breakout -> retest -> EntryReady."""
    fsm = MarketFSM()
    narrative = MarketNarrativeEngine()
    sym = "SCENARIO_BR"

    states = [
        MarketStateSnapshot(sym, 1, trend="bullish", momentum="increasing", breakout_status="none"),
        MarketStateSnapshot(sym, 2, trend="bullish", momentum="decreasing", breakout_status="none"),
        MarketStateSnapshot(sym, 3, trend="bullish", momentum="increasing", breakout_status="forming", volatility="compressing"),
        MarketStateSnapshot(sym, 4, trend="bullish", momentum="increasing", breakout_status="confirmed", retest_status="pending"),
        MarketStateSnapshot(
            sym,
            5,
            trend="bullish",
            momentum="increasing",
            breakout_status="confirmed",
            retest_status="successful",
            trend_strength="strong",
            direction_bias="LONG",
            mtf={"h1": "context_bullish", "m15": "setup_aligned", "m5": "execution_ready"},
        ),
    ]
    event_types: list[str] = []
    for st in states:
        evs, _ = narrative.update_from_snapshot(st)
        event_types.extend(e.event_type for e in evs)

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
    tail = narrative.load(sym)
    tail_dicts = [e.to_dict() for e in tail]
    fsm.persist_state(sym, "SetupForming")
    decision = fsm.evaluate(
        snapshot=states[-1],
        gates=gates,
        narrative_tail=tail_dicts,
        has_open_position=False,
    )
    assert decision.fsm_state == "EntryReady"
    assert decision.entry_signal == "LONG"
    assert "breakout_confirmed" in event_types or "pullback_ends" in event_types


def test_scenario_failed_breakout_blocks_gates() -> None:
    """Failed breakout sequence should not permit trade."""
    result = rule_based_pipeline.run_cycle(
        symbol="SCENARIO_FB",
        bar_index=10,
        features=_bullish_features(breakout_score=0.3, vol_expansion=-0.1),
        regime="ranging",
        thesis_signal="HOLD",
        thesis_type="breakout",
        has_open_position=False,
    )
    assert result.structural_gates.trade_allowed is False


def test_scenario_trend_continuation_without_breakout() -> None:
    """Trend continuation path without breakout_confirmed narrative."""
    fsm = MarketFSM()
    snap = MarketStateSnapshot(
        "SCENARIO_TC",
        20,
        trend="bullish",
        trend_strength="moderate",
        trend_age_candles=8,
        momentum="flat",
        breakout_status="none",
        direction_bias="LONG",
        mtf={"h1": "context_bullish", "m15": "setup_aligned", "m5": "execution_ready"},
    )
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
        setup_type="trend_continuation",
    )
    narrative = [{"event_type": "pullback_ends", "timestamp": "t", "bar_index": 19}]
    fsm.persist_state("SCENARIO_TC", "SetupForming")
    decision = fsm.evaluate(
        snapshot=snap,
        gates=gates,
        narrative_tail=narrative,
        has_open_position=False,
    )
    assert decision.fsm_state in ("EntryReady", "SetupForming")
