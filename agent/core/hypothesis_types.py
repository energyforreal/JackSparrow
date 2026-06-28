"""Market hypothesis portfolio types for strategy-first pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HypothesisCandidate:
    """Single structural trade hypothesis for one bar."""

    id: str
    direction: str  # LONG, SHORT, FLAT
    confidence: float
    thesis_type: str
    horizon_bars: int = 0
    horizon_minutes: int = 0
    reason_codes: List[str] = field(default_factory=list)
    regime_weight: float = 1.0
    weighted_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "direction": self.direction,
            "confidence": float(self.confidence),
            "thesis_type": self.thesis_type,
            "horizon_bars": int(self.horizon_bars),
            "horizon_minutes": int(self.horizon_minutes),
            "reason_codes": list(self.reason_codes),
            "regime_weight": float(self.regime_weight),
            "weighted_confidence": float(self.weighted_confidence),
        }


@dataclass
class MarketHypothesisSnapshot:
    """Competing hypotheses and environment scores for one decision cycle."""

    hypotheses: List[HypothesisCandidate] = field(default_factory=list)
    environment: Dict[str, float] = field(default_factory=dict)
    regime: str = "neutral"
    dominant: Optional[HypothesisCandidate] = None
    aggregate_direction: str = "FLAT"  # LONG, SHORT, FLAT
    aggregate_confidence: float = 0.0
    hypothesis_margin: float = 0.0
    long_pressure: float = 0.0
    short_pressure: float = 0.0
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "environment": dict(self.environment),
            "regime": self.regime,
            "dominant": self.dominant.to_dict() if self.dominant else None,
            "aggregate_direction": self.aggregate_direction,
            "aggregate_confidence": float(self.aggregate_confidence),
            "hypothesis_margin": float(self.hypothesis_margin),
            "long_pressure": float(self.long_pressure),
            "short_pressure": float(self.short_pressure),
            "reason_codes": list(self.reason_codes),
        }


def hypothesis_snapshot_from_dict(raw: Any) -> Optional[MarketHypothesisSnapshot]:
    """Restore snapshot from market_context cache."""
    if not isinstance(raw, dict):
        return None
    try:
        hyps: List[HypothesisCandidate] = []
        for h in raw.get("hypotheses") or []:
            if not isinstance(h, dict):
                continue
            hyps.append(
                HypothesisCandidate(
                    id=str(h.get("id") or ""),
                    direction=str(h.get("direction") or "FLAT"),
                    confidence=float(h.get("confidence") or 0.0),
                    thesis_type=str(h.get("thesis_type") or "flat"),
                    horizon_bars=int(h.get("horizon_bars") or 0),
                    horizon_minutes=int(h.get("horizon_minutes") or 0),
                    reason_codes=list(h.get("reason_codes") or []),
                    regime_weight=float(h.get("regime_weight") or 1.0),
                    weighted_confidence=float(h.get("weighted_confidence") or 0.0),
                )
            )
        dom_raw = raw.get("dominant")
        dominant = None
        if isinstance(dom_raw, dict) and dom_raw.get("id"):
            dominant = HypothesisCandidate(
                id=str(dom_raw.get("id") or ""),
                direction=str(dom_raw.get("direction") or "FLAT"),
                confidence=float(dom_raw.get("confidence") or 0.0),
                thesis_type=str(dom_raw.get("thesis_type") or "flat"),
                horizon_bars=int(dom_raw.get("horizon_bars") or 0),
                horizon_minutes=int(dom_raw.get("horizon_minutes") or 0),
                reason_codes=list(dom_raw.get("reason_codes") or []),
                regime_weight=float(dom_raw.get("regime_weight") or 1.0),
                weighted_confidence=float(dom_raw.get("weighted_confidence") or 0.0),
            )
        return MarketHypothesisSnapshot(
            hypotheses=hyps,
            environment=dict(raw.get("environment") or {}),
            regime=str(raw.get("regime") or "neutral"),
            dominant=dominant,
            aggregate_direction=str(raw.get("aggregate_direction") or "FLAT"),
            aggregate_confidence=float(raw.get("aggregate_confidence") or 0.0),
            hypothesis_margin=float(raw.get("hypothesis_margin") or 0.0),
            long_pressure=float(raw.get("long_pressure") or 0.0),
            short_pressure=float(raw.get("short_pressure") or 0.0),
            reason_codes=list(raw.get("reason_codes") or []),
        )
    except (TypeError, ValueError):
        return None
