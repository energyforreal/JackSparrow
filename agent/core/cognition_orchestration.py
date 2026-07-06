"""Cognition + rule-based orchestration helpers for MCP prediction paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

from agent.core.agent_thesis_engine import (
    agent_thesis_engine,
    get_last_hypothesis_snapshot,
    thesis_verdict_to_dict,
)
from agent.core.config import settings
from agent.core.evidence_engine import build_evidence_bundle, market_forecast_from_context
from agent.core.evidence_types import EvidenceBundle, MarketForecastBundle
from agent.core.strategy_types import MLValidationSnapshot, StrategyCandidate
from agent.intelligence.cognition.decision_context_builder import attach_decision_context_v3
from agent.intelligence.cognition.flags import cognition_cycle_enabled
from agent.intelligence.rule_based_pipeline import rule_based_pipeline

logger = structlog.get_logger()


@dataclass
class EvidenceStackResult:
    """Evidence bundle, forecast, and optional graph payload for market_context."""

    evidence_bundle: EvidenceBundle
    market_forecast: MarketForecastBundle
    evidence_graph: Optional[Dict[str, Any]] = None
    market_state_trajectory: Optional[Dict[str, Any]] = None


def populate_rule_based_context(
    market_context: Dict[str, Any],
    *,
    symbol: str,
    bar_index: int,
    features: Dict[str, Any],
    regime: str,
    structure: Any,
    thesis_signal: str,
    thesis_type: str,
    has_open_position: bool,
    gate_state: Any,
    contract_state: Any,
    features_history: Optional[List[Dict[str, Any]]] = None,
    skip_if_populated: bool = True,
    decision_context_v3: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run rule-based pipeline and copy outputs into market_context."""
    mc = market_context if isinstance(market_context, dict) else {}
    if skip_if_populated and isinstance(mc.get("rule_based_pipeline"), dict):
        return mc

    rb = rule_based_pipeline.run_cycle(
        symbol=symbol,
        bar_index=bar_index,
        features=features,
        regime=regime,
        thesis_signal=thesis_signal,
        thesis_type=thesis_type,
        has_open_position=has_open_position,
        structure=structure,
        gate_state=gate_state,
        contract_state=contract_state,
        features_history=features_history,
        decision_context_v3=decision_context_v3,
    )
    mc["rule_based_pipeline"] = rb.to_dict()
    mc["market_state"] = rb.market_state.to_dict()
    mc["narrative_tail"] = rb.narrative_tail
    mc["structural_gates"] = rb.structural_gates.to_dict()
    mc["fsm_state"] = rb.fsm_decision.fsm_state
    mc["entry_signal"] = rb.fsm_decision.entry_signal
    mc["thesis_health"] = rb.fsm_decision.thesis_health
    mc["position_lifecycle"] = rb.fsm_decision.position_lifecycle

    from agent.intelligence.trade_archetype_memory import trade_archetype_memory

    sim = trade_archetype_memory.similar_setups(
        symbol,
        setup_type=rb.structural_gates.setup_type,
        regime=regime,
        narrative_tail=rb.narrative_tail,
    )
    mc["archetype_similarity"] = sim

    new_ev_dicts = [e.to_dict() for e in rb.narrative_events]
    if new_ev_dicts:
        mc["narrative_new_events"] = new_ev_dicts
    mc["_rule_based_pipeline_result"] = rb
    return mc


def attach_cognition(market_context: Dict[str, Any]) -> Dict[str, Any]:
    """Attach decision_context_v3 when cognition cycle is enabled."""
    if not cognition_cycle_enabled():
        return market_context
    return attach_decision_context_v3(market_context)


def evaluate_thesis_from_context(
    regime: str,
    market_context: Dict[str, Any],
) -> Any:
    """Evaluate authoritative thesis and sync snapshot fields into market_context."""
    mc = market_context if isinstance(market_context, dict) else {}
    verdict = agent_thesis_engine.evaluate(regime, mc)
    snap = get_last_hypothesis_snapshot()
    if snap:
        mc["hypothesis_snapshot"] = snap
        if isinstance(snap.get("environment"), dict):
            mc["environment_scores"] = dict(snap["environment"])
    mc["thesis_verdict"] = thesis_verdict_to_dict(verdict)
    return verdict


def _market_forecast_for_evidence(
    market_context: Dict[str, Any],
    ml_validation: Optional[MLValidationSnapshot],
) -> MarketForecastBundle:
    """Prefer cognition expectation over legacy regime lookup when available."""
    mc = market_context if isinstance(market_context, dict) else {}
    dc_raw = mc.get("decision_context_v3")
    if isinstance(dc_raw, dict) and isinstance(dc_raw.get("expectation"), dict):
        from agent.intelligence.cognition.decision_context import DecisionContext

        try:
            ctx = DecisionContext.from_dict(dc_raw)
            if ctx.expectation is not None:
                legacy = ctx.to_legacy_market_context()
                exp = legacy.get("expectation")
                if isinstance(exp, dict):
                    exp_conf = float(exp.get("confidence") or 0.5)
                    base = market_forecast_from_context(mc, ml_validation)
                    return MarketForecastBundle(
                        regime_distribution=base.regime_distribution,
                        liquidity_forecast=base.liquidity_forecast,
                        breakout_probability=exp_conf,
                        vol_expansion_prob=base.vol_expansion_prob,
                        momentum_score=exp_conf,
                        expected_edge=base.expected_edge,
                        uncertainty_score=base.uncertainty_score,
                        p_setup_quality=base.p_setup_quality,
                        p_regime_favorable=base.p_regime_favorable,
                    )
        except (TypeError, ValueError) as exc:
            logger.debug("cognition_forecast_fallback", error=str(exc))
    return market_forecast_from_context(mc, ml_validation)


def build_evidence_stack(
    *,
    market_context: Dict[str, Any],
    ml_validation: MLValidationSnapshot,
    structure: Any,
    strategy: StrategyCandidate,
    thesis_verdict: Any,
    ml_confirms: bool,
    symbol: str,
    bar_index: int,
    regime: str,
    reject_tail: str = "",
    include_graph: bool = True,
    include_trajectory: bool = True,
) -> EvidenceStackResult:
    """Build evidence bundle, forecast, graph, and optional market-state trajectory."""
    mc = market_context if isinstance(market_context, dict) else {}

    evidence_bundle = build_evidence_bundle(
        market_context=mc,
        ml_validation=ml_validation,
        structure=structure,
        strategy=strategy,
        thesis_verdict=thesis_verdict,
        ml_confirms=ml_confirms,
    )
    market_forecast = _market_forecast_for_evidence(mc, ml_validation)
    mc["evidence_bundle"] = evidence_bundle.to_dict()
    mc["market_forecast"] = market_forecast.to_dict()

    evidence_graph: Optional[Dict[str, Any]] = None
    if include_graph and bool(getattr(settings, "evidence_graph_enabled", True)):
        from agent.intelligence.evidence_graph import build_evidence_graph

        graph = build_evidence_graph(
            evidence_bundle,
            direction=strategy.signal,
            market_forecast=market_forecast.to_dict(),
            decision_context=mc.get("decision_context_v3"),
        )
        evidence_graph = graph.to_dict()
        mc["evidence_graph"] = evidence_graph

    trajectory: Optional[Dict[str, Any]] = None
    if include_trajectory and bool(getattr(settings, "market_intelligence_enabled", True)):
        from agent.intelligence.market_state_engine import market_state_engine

        ms_traj = market_state_engine.update_from_cycle(
            symbol=symbol,
            bar_index=bar_index,
            regime=regime,
            evidence=evidence_bundle,
            forecast=market_forecast,
            breakout_failed=reject_tail in ("failed_breakout", "breakout_failed"),
        )
        trajectory = ms_traj.to_dict()
        mc["market_state_trajectory"] = trajectory

    return EvidenceStackResult(
        evidence_bundle=evidence_bundle,
        market_forecast=market_forecast,
        evidence_graph=evidence_graph,
        market_state_trajectory=trajectory,
    )
