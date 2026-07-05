"""Cognition replay: calibration and what-if counterfactual analysis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.intelligence.cognition.decision_context import CognitionInputs, DecisionContext
from agent.intelligence.cognition.strategy_profiles import all_profiles
from agent.intelligence.cognition.strategy_scorer import score_strategies
from agent.intelligence.cognition.strategy_selector import select_strategies


def counterfactual_strategy_scores(
    ctx: DecisionContext,
    *,
    features: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate ALL registered profiles regardless of live eligibility."""
    inputs = CognitionInputs(
        understanding=ctx.understanding,
        memory=ctx.memory,
        scenario=ctx.scenario,
        expectation=ctx.expectation,
        risk_intelligence=ctx.risk_intelligence,
        features=dict(features or {}),
        structural_evidence=dict(ctx.structural_evidence),
        behavioral_evidence=dict(ctx.behavioral_evidence),
    )
    sel, _ = select_strategies(inputs, profiles=all_profiles(), force_all=True)
    scores, _ = score_strategies(inputs, sel)
    live_best = None
    if ctx.strategy_scores and ctx.strategy_scores.entries:
        live_best = max(ctx.strategy_scores.entries, key=lambda e: e.adjusted_confidence)
    counterfactual = [
        {
            "profile_id": e.profile_id,
            "eligible": next(
                (s.eligible for s in sel.entries if s.profile_id == e.profile_id),
                False,
            ),
            "adjusted_confidence": e.adjusted_confidence,
            "abstention_reason": next(
                (s.abstention_reason for s in sel.entries if s.profile_id == e.profile_id),
                None,
            ),
        }
        for e in scores.entries
    ]
    best_cf = max(counterfactual, key=lambda x: x["adjusted_confidence"]) if counterfactual else None
    return {
        "live_best_profile": live_best.profile_id if live_best else None,
        "counterfactual_best_profile": best_cf["profile_id"] if best_cf else None,
        "counterfactual_scores": counterfactual,
        "consensus_direction": scores.consensus_direction,
    }


def calibration_metrics_from_trace(layers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize cognition layers from a ScenarioRunner trace."""
    out: Dict[str, Any] = {"layers_present": [], "expectation_logged": False}
    for layer in layers:
        name = str(layer.get("name") or "")
        if name.startswith("cognition"):
            out["layers_present"].append(name)
        if name == "cognition_expectation" and layer.get("ok"):
            out["expectation_logged"] = True
            out["expectation_output"] = layer.get("output") or layer.get("_obj")
    return out
