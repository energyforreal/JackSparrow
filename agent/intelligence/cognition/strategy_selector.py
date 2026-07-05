"""Strategy eligibility selection (no confidence adjustment)."""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.strategy_profiles import StrategyProfile, all_profiles, enabled_profiles
from agent.intelligence.cognition.types import ExpectationHorizon, StrategySelectionEntry, StrategySelectionResult


def _horizon_for_expectation(
    expectation_horizons: Tuple[ExpectationHorizon, ...],
    minutes: int,
) -> Optional[ExpectationHorizon]:
    for h in expectation_horizons:
        if h.horizon_minutes == minutes:
            return h
    return expectation_horizons[0] if expectation_horizons else None


def _expectation_value(h: ExpectationHorizon, key: str) -> float:
    return float(getattr(h, key, 0.5))


def _profile_eligible(
    profile: StrategyProfile,
    inputs: CognitionInputs,
    *,
    force_all: bool = False,
) -> Tuple[bool, Optional[str]]:
    if not profile.enabled and not force_all:
        return False, "profile_disabled"

    risk = inputs.risk_intelligence
    if risk is not None and risk.trade_environment_score < profile.risk_floor:
        return False, f"risk_below_floor={risk.trade_environment_score:.2f}"

    scenario = inputs.scenario
    if profile.supported_scenarios and scenario is not None:
        if scenario.primary not in profile.supported_scenarios:
            return False, f"scenario_mismatch={scenario.primary}"

    memory = inputs.memory
    if profile.id == "breakout" and memory is not None:
        if memory.failed_breakout_weighted >= 2.0:
            return False, "memory_excess_failed_breakouts"

    exp = inputs.expectation
    if profile.expectation_thresholds and exp is not None and exp.horizons:
        h = _horizon_for_expectation(exp.horizons, profile.horizon_minutes)
        if h is not None:
            for dim, (lo, hi) in profile.expectation_thresholds:
                val = _expectation_value(h, dim)
                if val < lo or val > hi:
                    return False, f"expectation_{dim}={val:.2f}_out_of_range"

    return True, None


def select_strategies(
    inputs: CognitionInputs,
    *,
    profiles: Optional[Tuple[StrategyProfile, ...]] = None,
    force_all: bool = False,
) -> Tuple[StrategySelectionResult, ReasoningArtifact]:
    """Determine eligible strategy profiles."""
    t0 = time.perf_counter()
    pool = profiles if profiles is not None else (
        all_profiles() if force_all else enabled_profiles()
    )
    entries: List[StrategySelectionEntry] = []
    for profile in pool:
        ok, reason = _profile_eligible(profile, inputs, force_all=force_all)
        entries.append(
            StrategySelectionEntry(
                profile_id=profile.id,
                eligible=ok,
                abstention_reason=reason,
            )
        )
    result = StrategySelectionResult(entries=tuple(entries))
    eligible_count = sum(1 for e in entries if e.eligible)
    artifact = ReasoningArtifact(
        module_id="strategy_selector",
        confidence=eligible_count / max(len(entries), 1),
        reason_codes=(f"eligible_count={eligible_count}",),
        output=result.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return result, artifact
