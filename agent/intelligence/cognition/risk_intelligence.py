"""Risk intelligence — opportunity vs risk context."""

from __future__ import annotations

import time
from typing import Tuple

from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.types import RiskIntelligenceState


def evaluate_risk_intelligence(inputs: CognitionInputs) -> Tuple[RiskIntelligenceState, ReasoningArtifact]:
    """Distill risk context for strategy selection (no hypothesis/policy reads)."""
    t0 = time.perf_counter()
    reasons: list[str] = []
    u = inputs.understanding
    s = inputs.scenario
    e = inputs.expectation

    vol_elevated = False
    unstable = False
    if u is not None:
        if u.volatility == "expanding":
            vol_elevated = True
            reasons.append("risk_vol_expanding")
        if u.liquidity == "stressed":
            unstable = True
            reasons.append("risk_liquidity_stressed")
        if u.regime == "crisis":
            unstable = True
            reasons.append("risk_crisis_regime")

    if s is not None and s.primary in ("trend_exhaustion", "liquidity_grab"):
        unstable = True
        reasons.append(f"risk_scenario_{s.primary}")

    risk_budget = min(1.0, max(0.0, inputs.portfolio_heat))
    if risk_budget > 0.7:
        reasons.append(f"risk_portfolio_heat={risk_budget:.2f}")

    stopout_deg = min(1.0, inputs.daily_drawdown_pct / 5.0) if inputs.daily_drawdown_pct > 0 else 0.0
    if stopout_deg > 0.5:
        reasons.append("risk_drawdown_elevated")

    score = 0.72
    if vol_elevated:
        score -= 0.12
    if unstable:
        score -= 0.18
    score -= risk_budget * 0.2
    score -= stopout_deg * 0.15

    if e is not None and e.horizons:
        h = e.horizons[0]
        if h.reversal_risk > 0.65:
            score -= 0.1
            reasons.append("risk_high_reversal_expectation")

    score = max(0.05, min(0.95, score))

    state = RiskIntelligenceState(
        volatility_elevated=vol_elevated,
        market_unstable=unstable,
        risk_budget_consumed_pct=risk_budget,
        recent_stopout_degradation=stopout_deg,
        trade_environment_score=score,
        reason_codes=tuple(reasons),
    )
    artifact = ReasoningArtifact(
        module_id="risk_intelligence",
        confidence=score,
        reason_codes=tuple(reasons),
        output=state.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return state, artifact
