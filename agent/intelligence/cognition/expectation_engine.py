"""Rule-based forward expectation (indicators-only v1)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from agent.core.config import settings
from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.decision_context import CognitionInputs
from agent.intelligence.cognition.types import ExpectationHorizon, ExpectationState, MarketUnderstanding
from feature_store.jacksparrow_v43_horizon import V43HorizonProfile, V43_MULTIHEAD_FORWARD_BARS, horizon_profile


def _feat(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, float(val)))


def _trend_persistence(understanding: Optional[MarketUnderstanding], features: Dict[str, Any]) -> float:
    adx = _feat(features, "adx_14")
    score = 0.45
    if understanding is not None:
        if understanding.trend_strength == "strong":
            score += 0.25
        elif understanding.trend_strength == "moderate":
            score += 0.12
        if understanding.momentum == "increasing":
            score += 0.1
        elif understanding.momentum == "decreasing":
            score -= 0.12
    if adx >= 30:
        score += 0.15
    elif adx >= 22:
        score += 0.08
    ema_bias = _feat(features, "ema200_bias")
    if abs(ema_bias) > 0.1:
        score += 0.05
    return _clamp01(score)


def _breakout_likelihood(understanding: Optional[MarketUnderstanding], features: Dict[str, Any]) -> float:
    bb_width = _feat(features, "bb_width", 2.0)
    vol_reg = _feat(features, "vol_regime", 1.0)
    breakout_score = _feat(features, "breakout_score", 0.5)
    score = 0.35 + breakout_score * 0.35
    if bb_width < 1.5:
        score += 0.15
    if understanding is not None and understanding.volatility == "compressing":
        score += 0.12
    if vol_reg > 1.05:
        score += 0.08
    return _clamp01(score)


def _reversal_risk(understanding: Optional[MarketUnderstanding], features: Dict[str, Any]) -> float:
    rsi_mom = _feat(features, "rsi_mom")
    mom_accel = _feat(features, "mom_accel")
    score = 0.25
    if understanding is not None:
        if understanding.momentum == "decreasing":
            score += 0.2
        if understanding.trend_age_candles > 20:
            score += 0.1
    if rsi_mom < -0.05:
        score += 0.1
    if mom_accel < -0.05:
        score += 0.1
    return _clamp01(score)


def _volatility_expansion(understanding: Optional[MarketUnderstanding], features: Dict[str, Any]) -> float:
    atr_pct = _feat(features, "atr_pct")
    vol_reg = _feat(features, "vol_regime", 1.0)
    vol_exp = _feat(features, "vol_expansion", 0.0)
    score = 0.4
    if understanding is not None and understanding.volatility == "expanding":
        score += 0.2
    if vol_reg > 1.1:
        score += 0.15
    if vol_exp > 0:
        score += 0.1
    if atr_pct > 0.01:
        score += 0.08
    return _clamp01(score)


def _horizon_scale(base: float, profile: V43HorizonProfile) -> float:
    """Longer horizons slightly dampen extreme scores."""
    minutes = profile.horizon_minutes
    if minutes <= 10:
        return base
    damp = 1.0 - min(0.12, (minutes - 10) / 200.0)
    return _clamp01(0.5 + (base - 0.5) * damp)


def evaluate_expectation(
    inputs: CognitionInputs,
    *,
    prior: Optional[ExpectationState] = None,
) -> tuple[ExpectationState, ReasoningArtifact]:
    """Compute expectation from understanding + features only (v1)."""
    t0 = time.perf_counter()
    understanding = inputs.understanding
    features = inputs.features
    reasons: List[str] = []

    horizons: List[ExpectationHorizon] = []
    for bars in sorted(V43_MULTIHEAD_FORWARD_BARS):
        profile = horizon_profile(bars)
        tp = _horizon_scale(_trend_persistence(understanding, features), profile)
        bl = _horizon_scale(_breakout_likelihood(understanding, features), profile)
        rr = _horizon_scale(_reversal_risk(understanding, features), profile)
        ve = _horizon_scale(_volatility_expansion(understanding, features), profile)
        horizons.append(
            ExpectationHorizon(
                horizon_minutes=profile.horizon_minutes,
                trend_persistence=tp,
                breakout_likelihood=bl,
                reversal_risk=rr,
                volatility_expansion=ve,
            )
        )

    primary_h = horizons[1] if len(horizons) > 1 else (horizons[0] if horizons else None)
    dominant = "neutral"
    conf = 0.5
    if primary_h is not None:
        scores = {
            "trend_continuation": primary_h.trend_persistence,
            "breakout": primary_h.breakout_likelihood,
            "reversal": primary_h.reversal_risk,
            "vol_expansion": primary_h.volatility_expansion,
        }
        dominant = max(scores, key=scores.get)  # type: ignore[arg-type]
        conf = scores[dominant]
        reasons.append(f"expectation_dominant={dominant}")
        reasons.append(f"expectation_confidence={conf:.3f}")

    delta = 0.0
    drivers: List[str] = []
    if prior is not None and prior.confidence > 0:
        delta = conf - prior.confidence
        if abs(delta) > 0.05:
            drivers.append("confidence_shift")

    state = ExpectationState(
        horizons=tuple(horizons),
        dominant_expectation=dominant,
        confidence=conf,
        delta_from_prior=delta,
        revision_drivers=tuple(drivers),
        reason_codes=tuple(reasons),
    )
    artifact = ReasoningArtifact(
        module_id="expectation",
        confidence=conf,
        reason_codes=tuple(reasons),
        inputs={"has_understanding": understanding is not None},
        output=state.to_dict(),
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return state, artifact
