"""Strategy confidence scoring after eligibility."""

from __future__ import annotations

import time
from typing import Dict, List, Tuple

from agent.core.config import settings
from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.strategy_profiles import get_profile
from agent.intelligence.cognition.types import (
    ExpectationHorizon,
    StrategyScoreEntry,
    StrategyScoreResult,
    StrategySelectionResult,
)


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


def _horizon_match(
    horizons: Tuple[ExpectationHorizon, ...],
    minutes: int,
) -> ExpectationHorizon | None:
    for h in horizons:
        if h.horizon_minutes == minutes:
            return h
    return horizons[0] if horizons else None


def score_strategies(
    inputs: CognitionInputs,
    selection: StrategySelectionResult,
) -> Tuple[StrategyScoreResult, ReasoningArtifact]:
    """Apply confidence adjustments to eligible profiles."""
    t0 = time.perf_counter()
    agree_bonus = float(getattr(settings, "cognition_scorer_agreement_bonus", 0.12) or 0.12)
    disagree_penalty = float(
        getattr(settings, "cognition_scorer_disagreement_penalty", 0.18) or 0.18
    )

    entries: List[StrategyScoreEntry] = []
    direction_votes: Dict[str, float] = {"LONG": 0.0, "SHORT": 0.0}

    for sel in selection.entries:
        profile = get_profile(sel.profile_id)
        base = 0.55 if sel.eligible else 0.15
        adjustments: List[Tuple[str, float]] = []

        if not sel.eligible:
            entries.append(
                StrategyScoreEntry(
                    profile_id=sel.profile_id,
                    base_confidence=base,
                    adjustments=(),
                    adjusted_confidence=base,
                )
            )
            continue

        scenario = inputs.scenario
        if scenario is not None and profile is not None:
            if scenario.primary in profile.supported_scenarios:
                adjustments.append(("scenario_fit", 0.08))
                base += 0.08

        exp = inputs.expectation
        if exp is not None and profile is not None and exp.horizons:
            h = _horizon_match(exp.horizons, profile.horizon_minutes)
            if h is not None:
                if profile.id == "trend_continuation" and h.trend_persistence > 0.7:
                    adjustments.append(("expectation_agrees", agree_bonus))
                    base += agree_bonus
                elif profile.id == "breakout" and h.breakout_likelihood > 0.65:
                    adjustments.append(("expectation_agrees", agree_bonus))
                    base += agree_bonus
                elif h.reversal_risk > 0.6 and profile.id in (
                    "trend_continuation",
                    "breakout",
                ):
                    adjustments.append(("expectation_disagrees", -disagree_penalty))
                    base -= disagree_penalty

        risk = inputs.risk_intelligence
        if risk is not None:
            penalty = (0.5 - risk.trade_environment_score) * 0.3
            if penalty > 0:
                adjustments.append(("risk_penalty", -penalty))
                base -= penalty

        adj = _clamp01(base)
        entries.append(
            StrategyScoreEntry(
                profile_id=sel.profile_id,
                base_confidence=0.55,
                adjustments=tuple(adjustments),
                adjusted_confidence=adj,
            )
        )

        u = inputs.understanding
        if u is not None and adj >= 0.5:
            if u.direction_bias == "LONG":
                direction_votes["LONG"] += adj
            elif u.direction_bias == "SHORT":
                direction_votes["SHORT"] += adj

    long_p = direction_votes["LONG"]
    short_p = direction_votes["SHORT"]
    if long_p > short_p * 1.1 and long_p > 0.4:
        consensus = "LONG"
    elif short_p > long_p * 1.1 and short_p > 0.4:
        consensus = "SHORT"
    elif long_p > 0 and short_p > 0:
        consensus = "MIXED"
    else:
        consensus = "FLAT"

    agreement: Dict[str, List[str]] = {}
    ranked = sorted(entries, key=lambda e: e.adjusted_confidence, reverse=True)
    if len(ranked) >= 2 and ranked[0].adjusted_confidence > 0.5 and ranked[1].adjusted_confidence > 0.5:
        agreement[ranked[0].profile_id] = [ranked[1].profile_id]

    final_entries: List[StrategyScoreEntry] = []
    for e in entries:
        ag = tuple(agreement.get(e.profile_id, ()))
        final_entries.append(
            StrategyScoreEntry(
                profile_id=e.profile_id,
                base_confidence=e.base_confidence,
                adjustments=e.adjustments,
                adjusted_confidence=e.adjusted_confidence,
                agreement_with=ag,
            )
        )

    result = StrategyScoreResult(entries=tuple(final_entries), consensus_direction=consensus)
    artifact = ReasoningArtifact(
        module_id="strategy_scorer",
        confidence=max((e.adjusted_confidence for e in final_entries), default=0.0),
        reason_codes=(f"consensus={consensus}",),
        output=result.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return result, artifact
