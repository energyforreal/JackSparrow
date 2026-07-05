"""Market phase / scenario classification."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.types import MarketMemory, MarketUnderstanding, ScenarioState

_PHASES = (
    "accumulation",
    "distribution",
    "markup",
    "markdown",
    "compression",
    "expansion",
    "liquidity_grab",
    "trend_exhaustion",
    "range",
)


def evaluate_scenario(
    inputs: CognitionInputs,
    *,
    prior: Optional[ScenarioState] = None,
    narrative_tail: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[ScenarioState, ReasoningArtifact]:
    """Classify current market phase from understanding + memory."""
    t0 = time.perf_counter()
    u = inputs.understanding
    m = inputs.memory
    tail = narrative_tail or []
    reasons: List[str] = []
    sub: List[str] = []

    primary = "range"
    conf = 0.5

    if u is not None:
        if u.volatility == "compressing":
            primary = "compression"
            conf = 0.65
            reasons.append("scenario_compression")
            sub.append("volatility_compressing")
        elif u.volatility == "expanding":
            primary = "expansion"
            conf = 0.62
            reasons.append("scenario_expansion")

        if u.trend == "bullish" and u.trend_strength in ("moderate", "strong"):
            if u.momentum == "increasing":
                primary = "markup"
                conf = max(conf, 0.72)
                reasons.append("scenario_markup")
            elif u.momentum == "decreasing" and u.trend_age_candles > 15:
                primary = "trend_exhaustion"
                conf = max(conf, 0.68)
                reasons.append("scenario_trend_exhaustion")
        elif u.trend == "bearish" and u.trend_strength in ("moderate", "strong"):
            if u.momentum == "increasing":
                primary = "markdown"
                conf = max(conf, 0.72)
                reasons.append("scenario_markdown")

        if u.breakout_status == "forming":
            sub.append("breakout_forming")
            if primary == "compression":
                conf = min(0.85, conf + 0.1)

    if m is not None:
        if m.failed_breakout_weighted >= 1.5:
            sub.append("repeated_breakout_failures")
            if primary in ("compression", "expansion"):
                primary = "accumulation"
                conf = 0.6
                reasons.append("scenario_accumulation_after_failures")
        if m.rejection_weighted >= 1.0:
            sub.append("level_rejection")
        if m.liquidity_sweep_weighted >= 0.8:
            primary = "liquidity_grab"
            conf = max(conf, 0.7)
            reasons.append("scenario_liquidity_grab")

    for ev in tail[-5:]:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("event_type") or "")
        if et == "compression_detected":
            sub.append("compression_detected")
        if et == "volatility_expansion":
            sub.append("volatility_expansion")

    prev_primary = prior.primary if prior else None
    revision = None
    if prior is not None and prior.primary != primary:
        revision = f"phase_shift_{prior.primary}_to_{primary}"

    state = ScenarioState(
        primary=primary,
        confidence=conf,
        sub_signals=tuple(sub),
        previous_primary=prev_primary,
        revision_reason=revision,
        reason_codes=tuple(reasons),
    )
    artifact = ReasoningArtifact(
        module_id="scenario",
        confidence=conf,
        reason_codes=tuple(reasons),
        output=state.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return state, artifact
