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
from agent.core.ml_validator import ml_confirms_direction, thesis_verdict_to_strategy_candidate
from agent.core.strategy_types import MLValidationSnapshot, StrategyCandidate
from agent.core.trade_scorer import score_trade_setup
from agent.intelligence.cognition.decision_context_builder import attach_decision_context_v3
from agent.intelligence.cognition.flags import (
    cognition_cycle_enabled,
    cognition_scorer_enabled,
    cognition_selector_enabled,
    cognition_temporal_authority_enabled,
)
from agent.intelligence.rule_based_pipeline import rule_based_pipeline

logger = structlog.get_logger()


@dataclass
class EvidenceStackResult:
    """Evidence bundle, forecast, and optional graph payload for market_context."""

    evidence_bundle: EvidenceBundle
    market_forecast: MarketForecastBundle
    evidence_graph: Optional[Dict[str, Any]] = None
    market_state_trajectory: Optional[Dict[str, Any]] = None


@dataclass
class PostCognitionAdjudication:
    """Trade score and alignment computed from a thesis + strategy candidate."""

    thesis_verdict: Any
    strategy_candidate: StrategyCandidate
    ml_confirms: bool
    trade_score: Any
    entry_quality_result: Any


def run_post_cognition_adjudication(
    *,
    thesis_verdict: Any,
    strategy_candidate: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
    structure: Any,
    market_context: Dict[str, Any],
    collapse_rate: float,
    eps: float,
) -> PostCognitionAdjudication:
    """Compute ml_confirms, trade_score, and entry_quality for a thesis path."""
    from agent.core.entry_quality import evaluate_entry_quality

    strat_side = (
        "LONG"
        if strategy_candidate.direction == "LONG"
        else ("SHORT" if strategy_candidate.direction == "SHORT" else "FLAT")
    )
    ml_confirms = (
        ml_confirms_direction(ml_validation, strat_side, eps=eps, require_gated=True)
        if strat_side != "FLAT"
        else False
    )
    quality_mc = dict(market_context) if isinstance(market_context, dict) else {}
    trade_score = score_trade_setup(
        strategy=strategy_candidate,
        ml_validation=ml_validation,
        structure=structure,
        ml_confirms=ml_confirms,
        market_context=quality_mc,
        collapse_rate=collapse_rate,
    )
    entry_quality_result = evaluate_entry_quality(
        strategy=strategy_candidate,
        ml_validation=ml_validation,
        structure=structure,
        ml_confirms=ml_confirms,
        market_context=quality_mc,
        collapse_rate=collapse_rate,
    )
    return PostCognitionAdjudication(
        thesis_verdict=thesis_verdict,
        strategy_candidate=strategy_candidate,
        ml_confirms=ml_confirms,
        trade_score=trade_score,
        entry_quality_result=entry_quality_result,
    )


def log_cognition_thesis_authority_compare(
    *,
    symbol: str,
    bar_index: int,
    provisional_thesis: Any,
    authoritative_thesis: Any,
    provisional_adjudication: PostCognitionAdjudication,
    authoritative_adjudication: PostCognitionAdjudication,
    market_context: Dict[str, Any],
    policy_signal: str,
) -> None:
    """Dual-path telemetry for rollout replay analysis."""
    mc = market_context if isinstance(market_context, dict) else {}
    dc = mc.get("decision_context_v3") if isinstance(mc.get("decision_context_v3"), dict) else {}
    exp = dc.get("expectation") if isinstance(dc.get("expectation"), dict) else {}
    hyp = mc.get("hypothesis_snapshot") if isinstance(mc.get("hypothesis_snapshot"), dict) else {}
    dom = hyp.get("dominant") if isinstance(hyp.get("dominant"), dict) else {}

    def _thesis_pair(tv: Any) -> Dict[str, str]:
        return {
            "signal": str(getattr(tv, "signal", "HOLD") or "HOLD"),
            "type": str(getattr(tv, "thesis_type", "flat") or "flat"),
        }

    logger.info(
        "cognition_thesis_authority_compare",
        symbol=symbol,
        bar_index=bar_index,
        provisional_thesis=_thesis_pair(provisional_thesis),
        authoritative_thesis=_thesis_pair(authoritative_thesis),
        eligible_profiles=list(mc.get("eligible_strategy_profiles") or []),
        dominant_hypothesis=dom.get("thesis_type") if dom else None,
        provisional_strategy_candidate=provisional_adjudication.strategy_candidate.direction,
        authoritative_strategy_candidate=authoritative_adjudication.strategy_candidate.direction,
        provisional_trade_score=float(provisional_adjudication.trade_score.score),
        authoritative_trade_score=float(authoritative_adjudication.trade_score.score),
        provisional_ml_confirms=bool(provisional_adjudication.ml_confirms),
        authoritative_ml_confirms=bool(authoritative_adjudication.ml_confirms),
        policy_signal=str(policy_signal or "HOLD"),
        expectation_dominant=exp.get("dominant_expectation"),
        expectation_confidence=float(exp.get("confidence") or 0.0),
        temporal_authority_enabled=cognition_temporal_authority_enabled(),
    )


def check_adjudication_parity(
    *,
    provisional: PostCognitionAdjudication,
    authoritative: PostCognitionAdjudication,
    provisional_thesis: Any,
    authoritative_thesis: Any,
) -> None:
    """Warn when shadow adjudication diverges while all authority flags are off."""
    if cognition_selector_enabled() or cognition_scorer_enabled() or cognition_temporal_authority_enabled():
        return
    prov_sig = str(getattr(provisional_thesis, "signal", "HOLD") or "HOLD")
    auth_sig = str(getattr(authoritative_thesis, "signal", "HOLD") or "HOLD")
    if prov_sig != auth_sig:
        return
    score_delta = abs(float(provisional.trade_score.score) - float(authoritative.trade_score.score))
    if score_delta > 0.01 or provisional.ml_confirms != authoritative.ml_confirms:
        logger.warning(
            "cognition_adjudication_parity_violation",
            trade_score_provisional=float(provisional.trade_score.score),
            trade_score_authoritative=float(authoritative.trade_score.score),
            ml_confirms_provisional=provisional.ml_confirms,
            ml_confirms_authoritative=authoritative.ml_confirms,
        )


def apply_temporal_authority(
    *,
    market_context: Dict[str, Any],
    adjudication: PostCognitionAdjudication,
    v43_decision: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Switch market_context consumers to post-cognition adjudication (Stage 4B)."""
    mc = market_context if isinstance(market_context, dict) else {}
    mc["strategy_candidate"] = adjudication.strategy_candidate.to_dict()
    mc["thesis_verdict"] = thesis_verdict_to_dict(adjudication.thesis_verdict)
    mc["trade_score"] = adjudication.trade_score.to_dict()
    mc["entry_quality"] = adjudication.entry_quality_result.to_dict()
    mc["ml_confirms_authoritative"] = adjudication.ml_confirms
    if isinstance(v43_decision, dict):
        mc["v43_dedicated_decision"] = v43_decision
    return mc


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
