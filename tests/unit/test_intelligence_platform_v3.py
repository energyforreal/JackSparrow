"""Tests for intelligence platform v3 modules."""

from __future__ import annotations

from agent.intelligence.market_validation import validate_market
from agent.intelligence.post_trade_analyzer import analyze_post_trade
from agent.intelligence.regime_benchmark import derive_regime_benchmark
from agent.intelligence.rule_evaluation_engine import (
    evaluate_confidence_calibration,
    evaluate_rules_from_trades,
)
from agent.intelligence.signal_explainer import explain_signal
from agent.intelligence.structure_timeline import (
    condense_structure_timeline,
    derive_structure_state,
)
from agent.intelligence.trade_analysis_engine import trade_analysis_engine
from agent.intelligence.logic_version import get_logic_version


def test_regime_benchmark_trending_strong():
    ms = {
        "trend": "bullish",
        "trend_strength": "strong",
        "regime": "trending",
        "volatility": "stable",
        "breakout_status": "none",
        "momentum": "increasing",
    }
    assert derive_regime_benchmark(ms) == "trending_strong"


def test_market_validation_scores():
    ms = {
        "trend": "bullish",
        "trend_strength": "strong",
        "breakout_status": "confirmed",
        "volatility": "expanding",
        "momentum": "increasing",
        "mtf": {"h1": "bull_aligned"},
    }
    result = validate_market(
        market_state=ms,
        gate_categories={
            "trend": True,
            "volatility": True,
            "liquidity": True,
        },
    )
    assert result.validation_score >= 70
    assert result.trending is True


def test_signal_explainer():
    expl = explain_signal(
        signal="LONG",
        structural_confidence=0.84,
        gate_categories={"trend": True, "breakout": True, "liquidity": False},
        block_reasons=["liquidity_stressed"],
        fsm_state="EntryReady",
        setup_type="breakout",
        market_state={"momentum": "increasing", "mtf": {"h1": "bull"}},
    )
    assert expl["signal"] == "LONG"
    assert expl["confidence_pct"] == 84.0
    assert "trend_confirmed" in expl["reasons"]


def test_structure_timeline():
    monitoring = [
        {"structure_state": "bullish"},
        {"structure_state": "bullish"},
        {"structure_state": "neutral"},
        {"structure_state": "bearish"},
    ]
    timeline = condense_structure_timeline(monitoring)
    assert timeline == ["bullish", "neutral", "bearish"]


def test_post_trade_analyzer_dimensions():
    snapshot = {
        "snapshot_kind": "closed_round_trip",
        "decision_context": {
            "market_validation": {"validation_score": 80, "regime_benchmark": "trending_strong"},
            "structural_confidence": 0.85,
        },
        "outcome": {
            "pnl_usd": 10.0,
            "exit_reason": "take_profit_hit",
            "gross_pnl_usd": 12.0,
            "fees_usd": 2.0,
        },
        "execution_timing": {"risk_to_fill_ms": 500},
        "market_structure_timeline": ["bullish", "bullish"],
        "position_monitoring": [{"health_score": 75, "opportunity_score": 60}],
    }
    result = analyze_post_trade(snapshot)
    assert result["entry_quality"] in ("excellent", "adequate", "poor")
    assert result["strategy_quality"] in ("effective", "mixed", "ineffective")
    assert "root_cause" in result


def test_rule_evaluation_engine():
    trades = [
        {
            "pnl": 5.0,
            "metadata": {
                "decision_context": {
                    "gate_evaluation": {
                        "categories": {
                            "trend": True,
                            "breakout": True,
                            "structure": True,
                            "liquidity": True,
                            "volatility": True,
                            "risk": True,
                        }
                    }
                }
            },
        },
        {
            "pnl": -3.0,
            "metadata": {
                "decision_context": {
                    "gate_evaluation": {
                        "categories": {
                            "trend": True,
                            "breakout": False,
                            "structure": True,
                            "liquidity": True,
                            "volatility": True,
                            "risk": True,
                        }
                    },
                    "structural_confidence": 0.75,
                }
            },
        },
    ]
    report = evaluate_rules_from_trades(trades)
    assert "per_rule" in report
    assert report["trade_count"] == 2
    cal = evaluate_confidence_calibration(trades)
    assert "buckets" in cal


def test_trade_analysis_engine_run():
    snapshot = {
        "snapshot_kind": "closed_round_trip",
        "decision_context": {
            "signal": "LONG",
            "market_validation": {"validation_score": 75},
            "signal_explanation": {"signal": "LONG", "confidence_pct": 80},
            "rule_based_pipeline": {
                "market_state": {"regime": "trending", "regime_benchmark": "trending_strong"},
                "structural_confidence": 0.8,
            },
        },
        "outcome": {"pnl_usd": 1.0, "exit_reason": "take_profit_hit"},
        "position_monitoring": [{"structure_state": "bullish"}],
        "market_structure_timeline": ["bullish"],
    }
    assessment = trade_analysis_engine.run(snapshot)
    d = assessment.to_dict()
    assert "market" in d
    assert "post_trade" in d


def test_logic_version():
    lv = get_logic_version()
    assert "rule_set" in lv
    assert "analysis_engine" in lv


def test_derive_structure_state():
    assert derive_structure_state({"trend": "bullish", "trend_strength": "strong"}) == "bullish"
    assert derive_structure_state({"trend": "neutral"}) == "neutral"
