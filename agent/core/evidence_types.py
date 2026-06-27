"""Continuous evidence types for evidence-based decision pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EvidenceDimension(str, Enum):
    """Canonical evidence dimensions (scores 0–1)."""

    TREND = "trend"
    LIQUIDITY = "liquidity"
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    FUNDING = "funding"
    REGIME = "regime"
    STRUCTURE = "structure"
    ML_EDGE = "ml_edge"
    MODEL_CERTAINTY = "model_certainty"
    HORIZON_ALIGNMENT = "horizon_alignment"
    ORDER_FLOW = "order_flow"
    VOLATILITY = "volatility"
    SQUEEZE_RISK = "squeeze_risk"


class EvidenceBundle(BaseModel):
    """Continuous market evidence for one decision cycle."""

    scores: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    regime_distribution: Dict[str, float] = Field(default_factory=dict)

    def get(self, key: str, default: float = 0.5) -> float:
        raw = self.scores.get(key)
        if raw is None:
            return default
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "metadata": dict(self.metadata),
            "regime_distribution": dict(self.regime_distribution),
        }


class ConvictionResult(BaseModel):
    """Reasoning-tier conviction and sizing output."""

    conviction: float = Field(ge=0.0, le=1.0, default=0.0)
    direction: Optional[str] = None
    size_fraction: float = Field(ge=0.0, le=1.0, default=0.0)
    dimensions: Dict[str, float] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    below_entry_floor: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conviction": self.conviction,
            "direction": self.direction,
            "size_fraction": self.size_fraction,
            "dimensions": dict(self.dimensions),
            "reason_codes": list(self.reason_codes),
            "below_entry_floor": self.below_entry_floor,
        }


class MarketForecastBundle(BaseModel):
    """ML market-condition forecasts (not discrete trade labels)."""

    regime_distribution: Dict[str, float] = Field(default_factory=dict)
    liquidity_forecast: Optional[float] = None
    breakout_probability: Optional[float] = None
    vol_expansion_prob: Optional[float] = None
    momentum_score: Optional[float] = None
    expected_edge: Optional[float] = None
    uncertainty_score: Optional[float] = None
    p_setup_quality: Optional[float] = None
    p_regime_favorable: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
