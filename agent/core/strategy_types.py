"""Shared types for strategy-first agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MLValidationSnapshot:
    """ML probabilistic validation state (v43 expected_return vs thresholds)."""

    expected_return: float
    threshold: float
    short_threshold: float
    regime: str
    unc_scale: float = 1.0
    uncertainty: float = 0.0
    confirms_long: bool = False
    confirms_short: bool = False
    raw_long: bool = False
    raw_short: bool = False
    model_confidence: float = 0.0
    model_prediction: float = 0.0
    gate_reject: Optional[str] = None
    final_long: bool = False
    final_short: bool = False
    target_horizon_bars: int = 0
    horizon_minutes: int = 0
    multi_horizon_evidence: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_return": self.expected_return,
            "threshold": self.threshold,
            "short_threshold": self.short_threshold,
            "regime": self.regime,
            "unc_scale": self.unc_scale,
            "uncertainty": self.uncertainty,
            "confirms_long": self.confirms_long,
            "confirms_short": self.confirms_short,
            "raw_long": self.raw_long,
            "raw_short": self.raw_short,
            "model_confidence": self.model_confidence,
            "model_prediction": self.model_prediction,
            "gate_reject": self.gate_reject,
            "final_long": self.final_long,
            "final_short": self.final_short,
            "target_horizon_bars": self.target_horizon_bars,
            "horizon_minutes": self.horizon_minutes,
            "multi_horizon_evidence": self.multi_horizon_evidence,
        }


@dataclass
class StrategyCandidate:
    """Deterministic strategy proposal for one bar."""

    direction: str  # LONG, SHORT, FLAT
    strength: float  # 0.0 - 1.0
    signal: str  # BUY, SELL, HOLD, STRONG_BUY, STRONG_SELL
    reason_codes: List[str] = field(default_factory=list)
    thesis_type: str = "flat"
    confidence: float = 0.0
    position_size: float = 0.0
    intended_horizon_bars: int = 0
    horizon_minutes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "strength": self.strength,
            "signal": self.signal,
            "reason_codes": self.reason_codes,
            "thesis_type": self.thesis_type,
            "confidence": self.confidence,
            "position_size": self.position_size,
            "intended_horizon_bars": self.intended_horizon_bars,
            "horizon_minutes": self.horizon_minutes,
        }


@dataclass
class MarketStructureSnapshot:
    """Independent market structure classification for thesis and scoring."""

    market_type: str  # TRENDING, RANGING, LOW_VOL, CRISIS, NEUTRAL
    regime: str
    adx: float = 0.0
    atr_pct: float = 0.0
    vol_regime: float = 1.0
    liquidity_ok: bool = True
    chop_market: bool = False
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_type": self.market_type,
            "regime": self.regime,
            "adx": self.adx,
            "atr_pct": self.atr_pct,
            "vol_regime": self.vol_regime,
            "liquidity_ok": self.liquidity_ok,
            "chop_market": self.chop_market,
            "reason_codes": self.reason_codes,
        }
