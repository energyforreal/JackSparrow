"""Hypothesis portfolio evaluation and aggregation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agent.core.config import settings
from agent.core.hypothesis_types import (
    HypothesisCandidate,
    MarketHypothesisSnapshot,
)
from agent.core.signal_vocabulary import is_long_signal, is_short_signal, normalize_signal
from feature_store.jacksparrow_v43_horizon import (
    forward_bars_to_minutes,
    thesis_intended_forward_bars,
)

if TYPE_CHECKING:
    from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict

# Regime prior multipliers (soft gating — never zero)
_REGIME_PRIORS: Dict[str, Dict[str, float]] = {
    "breakout": {
        "trending": 1.0,
        "neutral": 1.0,
        "ranging": 0.7,
        "crisis": 0.35,
        "unknown": 0.85,
    },
    "trend_continuation": {
        "trending": 1.0,
        "neutral": 0.9,
        "ranging": 0.65,
        "crisis": 0.3,
        "unknown": 0.85,
    },
    "mean_reversion": {
        "trending": 0.8,
        "neutral": 0.85,
        "ranging": 1.0,
        "crisis": 0.4,
        "unknown": 0.75,
    },
    "basis_crowding": {
        "trending": 0.95,
        "neutral": 0.95,
        "ranging": 0.85,
        "crisis": 0.5,
        "unknown": 0.9,
    },
    "funding_crowding": {
        "trending": 0.95,
        "neutral": 0.95,
        "ranging": 0.85,
        "crisis": 0.5,
        "unknown": 0.9,
    },
}


def regime_prior(hypothesis_type: str, regime: str) -> float:
    """Soft regime weight for a hypothesis family."""
    reg = str(regime or "neutral").strip().lower()
    family = str(hypothesis_type or "flat").strip().lower()
    table = _REGIME_PRIORS.get(family, {})
    return float(table.get(reg, table.get("neutral", 0.75)))


def _verdict_to_candidate(verdict: "ThesisVerdict", *, regime: str) -> HypothesisCandidate:
    sig = normalize_signal(verdict.signal)
    if is_long_signal(sig):
        direction = "LONG"
    elif is_short_signal(sig):
        direction = "SHORT"
    else:
        direction = "FLAT"
    h_bars = int(verdict.intended_horizon_bars or thesis_intended_forward_bars(verdict.thesis_type))
    h_min = int(verdict.horizon_minutes or forward_bars_to_minutes(h_bars))
    thesis_type = str(verdict.thesis_type or "flat")
    hid = f"{thesis_type}_{direction.lower()}"
    w = regime_prior(thesis_type, regime)
    conf = float(verdict.confidence or 0.0)
    return HypothesisCandidate(
        id=hid,
        direction=direction,
        confidence=conf,
        thesis_type=thesis_type,
        horizon_bars=h_bars,
        horizon_minutes=h_min,
        reason_codes=list(verdict.reason_codes or []),
        regime_weight=w,
        weighted_confidence=conf * w,
    )


def evaluate_all_hypotheses(
    engine: "AgentThesisEngine",
    features: Dict[str, Any],
    regime: str,
    *,
    short_enabled: bool,
) -> List[HypothesisCandidate]:
    """Evaluate every enabled rule family (no regime allow-list)."""
    from agent.core.agent_thesis_engine import ThesisVerdict

    raw_verdicts: List[ThesisVerdict] = engine.collect_all_rule_verdicts(
        features, regime, short_enabled=short_enabled
    )
    return [_verdict_to_candidate(v, regime=regime) for v in raw_verdicts]


def aggregate_hypotheses(
    candidates: List[HypothesisCandidate],
    environment: Dict[str, float],
    regime: str,
) -> MarketHypothesisSnapshot:
    """Weighted net direction from competing hypotheses."""
    min_margin = float(getattr(settings, "hypothesis_min_margin", 0.03) or 0.03)
    reasons: List[str] = []

    long_pressure = 0.0
    short_pressure = 0.0
    for c in candidates:
        wconf = float(c.weighted_confidence or (c.confidence * c.regime_weight))
        c.weighted_confidence = wconf
        if c.direction == "LONG":
            long_pressure += wconf
        elif c.direction == "SHORT":
            short_pressure += wconf

    total = long_pressure + short_pressure
    if total <= 1e-9:
        return MarketHypothesisSnapshot(
            hypotheses=candidates,
            environment=dict(environment),
            regime=regime,
            dominant=None,
            aggregate_direction="FLAT",
            aggregate_confidence=0.0,
            hypothesis_margin=0.0,
            long_pressure=long_pressure,
            short_pressure=short_pressure,
            reason_codes=["hypothesis_no_rule_fired", f"regime={regime}"],
        )

    margin = abs(long_pressure - short_pressure) / max(long_pressure, short_pressure, 1e-9)
    reasons.append(f"hypothesis_long_pressure={long_pressure:.3f}")
    reasons.append(f"hypothesis_short_pressure={short_pressure:.3f}")
    reasons.append(f"hypothesis_margin={margin:.3f}")

    if margin < min_margin:
        aggregate_direction = "FLAT"
        aggregate_confidence = max(long_pressure, short_pressure) * margin
        reasons.append("hypothesis_margin_below_min")
    elif long_pressure > short_pressure:
        aggregate_direction = "LONG"
        aggregate_confidence = long_pressure
    else:
        aggregate_direction = "SHORT"
        aggregate_confidence = short_pressure

    ranked = sorted(candidates, key=lambda h: h.weighted_confidence, reverse=True)
    dominant = ranked[0] if ranked else None
    if dominant:
        reasons.append(f"hypothesis_dominant={dominant.id}")

    return MarketHypothesisSnapshot(
        hypotheses=candidates,
        environment=dict(environment),
        regime=regime,
        dominant=dominant,
        aggregate_direction=aggregate_direction,
        aggregate_confidence=float(min(1.0, aggregate_confidence)),
        hypothesis_margin=float(margin),
        long_pressure=long_pressure,
        short_pressure=short_pressure,
        reason_codes=reasons,
    )


def thesis_verdict_from_snapshot(
    snapshot: MarketHypothesisSnapshot,
    *,
    pos_size: float,
    evidence_contributions: Optional[Dict[str, float]] = None,
) -> "ThesisVerdict":
    """Backward-compatible ThesisVerdict from hypothesis aggregate."""
    from agent.core.agent_thesis_engine import ThesisVerdict

    ec = dict(evidence_contributions or {})
    ec.update(snapshot.environment)

    direction = str(snapshot.aggregate_direction or "FLAT").upper()
    dom = snapshot.dominant
    if direction == "FLAT":
        return ThesisVerdict(
            signal="HOLD",
            confidence=float(snapshot.aggregate_confidence or 0.0),
            position_size=0.0,
            reason_codes=list(snapshot.reason_codes),
            thesis_type=str(dom.thesis_type if dom else "flat"),
            intended_horizon_bars=int(dom.horizon_bars if dom else 0),
            horizon_minutes=int(dom.horizon_minutes if dom else 0),
            evidence_contributions=ec,
        )

    conf = float(snapshot.aggregate_confidence or 0.0)
    if conf >= 0.85:
        signal = f"STRONG_{direction}"
    else:
        signal = direction

    thesis_type = str(dom.thesis_type if dom else "flat")
    h_bars = int(dom.horizon_bars if dom else thesis_intended_forward_bars(thesis_type))
    h_min = int(dom.horizon_minutes if dom else forward_bars_to_minutes(h_bars))

    reason_codes = list(snapshot.reason_codes)
    if dom:
        reason_codes.extend(dom.reason_codes[:4])

    return ThesisVerdict(
        signal=signal,
        confidence=conf,
        position_size=float(pos_size),
        reason_codes=reason_codes,
        thesis_type=thesis_type,
        intended_horizon_bars=h_bars,
        horizon_minutes=h_min,
        evidence_contributions=ec,
    )


def aggregate_direction_to_signal(direction: str, confidence: float) -> str:
    """Map aggregate direction to discrete signal vocabulary."""
    d = str(direction or "FLAT").upper()
    if d == "FLAT":
        return "HOLD"
    if confidence >= 0.85:
        return f"STRONG_{d}"
    return d
