"""Persistent market understanding snapshot for live trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agent.core.strategy_types import MarketStructureSnapshot
from agent.core.v43_contract_state import ContractStateSnapshot
from agent.intelligence.regime_classifier import classify_regime


@dataclass
class MarketIntelligence:
    """Single object describing current market state for all consumers."""

    symbol: str
    bar_index: int
    timestamp: datetime
    closed_feats: Dict[str, float]
    regime: str
    structure: MarketStructureSnapshot
    contract_state: Optional[ContractStateSnapshot] = None
    thesis_verdict: Optional[Dict[str, Any]] = None
    trend_bias: str = "neutral"
    momentum_strength: float = 0.0
    volatility_state: str = "medium"
    liquidity_ok: bool = True
    confidence: float = 0.0
    version: int = 0

    @classmethod
    def from_cycle(
        cls,
        *,
        symbol: str,
        bar_index: int,
        closed_feats: Dict[str, float],
        structure: MarketStructureSnapshot,
        contract_state: Optional[ContractStateSnapshot] = None,
        thesis_verdict: Optional[Dict[str, Any]] = None,
        version: int = 0,
        timestamp: Optional[datetime] = None,
    ) -> "MarketIntelligence":
        regime = classify_regime(closed_feats)
        if "regime_label" in closed_feats:
            regime = str(closed_feats.get("regime_label", regime))

        atr_pct = float(closed_feats.get("atr_pct", 0.0) or 0.0)
        vol_regime = float(closed_feats.get("vol_regime", 1.0) or 1.0)
        if vol_regime > 2.5 or atr_pct > 0.02:
            volatility_state = "high"
        elif vol_regime < 0.8 and atr_pct < 0.005:
            volatility_state = "low"
        else:
            volatility_state = "medium"

        trend_bias = "neutral"
        ema_cross = float(closed_feats.get("ema_cross_9_21", 0.0) or 0.0)
        if regime == "trending":
            trend_bias = "bullish" if ema_cross > 0 else "bearish"
        elif regime == "ranging":
            trend_bias = "range"

        momentum_strength = min(
            1.0,
            abs(float(closed_feats.get("macd_hist", 0.0) or 0.0)) * 100.0
            + abs(float(closed_feats.get("roc_10", 0.0) or 0.0)) * 10.0,
        )

        confidence = 0.5
        if thesis_verdict and isinstance(thesis_verdict, dict):
            try:
                confidence = float(thesis_verdict.get("confidence", confidence))
            except (TypeError, ValueError):
                pass

        return cls(
            symbol=str(symbol),
            bar_index=int(bar_index),
            timestamp=timestamp or datetime.now(timezone.utc),
            closed_feats=dict(closed_feats),
            regime=regime,
            structure=structure,
            contract_state=contract_state,
            thesis_verdict=thesis_verdict,
            trend_bias=trend_bias,
            momentum_strength=momentum_strength,
            volatility_state=volatility_state,
            liquidity_ok=bool(structure.liquidity_ok),
            confidence=confidence,
            version=int(version),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "timestamp": self.timestamp.isoformat(),
            "closed_feats": self.closed_feats,
            "regime": self.regime,
            "v43_regime": self.regime,
            "market_structure": self.structure.to_dict(),
            "contract_state": (
                {
                    "state": self.contract_state.state,
                    "trading_status": self.contract_state.trading_status,
                    "is_operational": self.contract_state.is_operational,
                }
                if self.contract_state
                else None
            ),
            "thesis_verdict": self.thesis_verdict,
            "trend_bias": self.trend_bias,
            "momentum_strength": self.momentum_strength,
            "volatility_state": self.volatility_state,
            "liquidity_ok": self.liquidity_ok,
            "confidence": self.confidence,
            "version": self.version,
        }

    def to_market_context(self) -> Dict[str, Any]:
        """Flatten for reasoning / policy consumers."""
        ctx = self.to_dict()
        ctx["features"] = dict(self.closed_feats)
        if "volatility" not in ctx["features"]:
            atr = self.closed_feats.get("atr_pct")
            if atr is not None:
                ctx["features"]["volatility"] = float(atr) * 100.0
        return ctx


def merge_intel_into_market_context(mc: Dict[str, Any]) -> Dict[str, Any]:
    """Apply MarketIntelligence snapshot aliases without recomputing regime."""
    intel_raw = mc.get("market_intelligence")
    if not isinstance(intel_raw, dict):
        return mc
    out = dict(mc)
    regime = intel_raw.get("regime") or intel_raw.get("v43_regime")
    if regime:
        out.setdefault("regime", regime)
        out.setdefault("v43_regime", regime)
        out.setdefault("market_regime", regime)
    if intel_raw.get("market_structure") and "market_structure" not in out:
        out["market_structure"] = intel_raw["market_structure"]
    closed = intel_raw.get("closed_feats")
    if isinstance(closed, dict) and "features" not in out:
        out["features"] = dict(closed)
    for key in (
        "trend_bias",
        "volatility_state",
        "liquidity_ok",
        "confidence",
        "thesis_verdict",
        "bar_index",
    ):
        if key in intel_raw and key not in out:
            out[key] = intel_raw[key]
    return out
