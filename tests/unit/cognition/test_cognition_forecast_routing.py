"""Phase C: cognition expectation preferred over legacy market_forecast stub."""

from __future__ import annotations

from agent.core.cognition_orchestration import _market_forecast_for_evidence
from agent.core.evidence_types import MarketForecastBundle
from agent.core.strategy_types import MLValidationSnapshot
from agent.intelligence.evidence_graph import build_evidence_graph
from agent.core.evidence_engine import build_evidence_bundle
from agent.core.strategy_types import MarketStructureSnapshot, StrategyCandidate


def test_market_forecast_prefers_cognition_expectation() -> None:
    mc = {
        "regime": "neutral",
        "decision_context_v3": {
            "meta": {"schema_version": "3.0", "symbol": "BTCUSD", "bar_index": 1},
            "expectation": {
                "dominant_expectation": "breakout",
                "confidence": 0.66,
                "horizons": [],
                "delta_from_prior": 0.0,
                "revision_drivers": [],
                "reason_codes": [],
            },
        },
    }
    ml = MLValidationSnapshot(
        expected_return=0.01,
        threshold=0.005,
        short_threshold=0.005,
        regime="neutral",
    )
    forecast = _market_forecast_for_evidence(mc, ml)
    assert isinstance(forecast, MarketForecastBundle)
    assert forecast.breakout_probability == 0.66
    assert forecast.momentum_score == 0.66


def test_evidence_graph_includes_expectation_dominant_node() -> None:
    mc = {
        "regime": "neutral",
        "features": {"adx_14": 28.0},
        "decision_context_v3": {
            "meta": {"schema_version": "3.0"},
            "expectation": {
                "dominant_expectation": "breakout",
                "confidence": 0.66,
                "horizons": [],
            },
            "scenario": {"primary": "markup", "confidence": 0.7},
        },
    }
    structure = MarketStructureSnapshot(
        market_type="NEUTRAL",
        regime="neutral",
        liquidity_ok=True,
        chop_market=False,
    )
    ml = MLValidationSnapshot(
        expected_return=0.01,
        threshold=0.005,
        short_threshold=0.005,
        regime="neutral",
    )
    strategy = StrategyCandidate(
        signal="LONG",
        direction="LONG",
        strength=0.6,
        confidence=0.6,
    )
    bundle = build_evidence_bundle(
        market_context=mc,
        ml_validation=ml,
        structure=structure,
        strategy=strategy,
        thesis_verdict=None,
        ml_confirms=True,
    )
    graph = build_evidence_graph(
        bundle,
        direction="LONG",
        market_forecast=_market_forecast_for_evidence(mc, ml).to_dict(),
        decision_context=mc["decision_context_v3"],
    )
    node_ids = {n.node_id for n in graph.nodes}
    assert "expectation_dominant" in node_ids
