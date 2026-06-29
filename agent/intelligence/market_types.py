"""Shared dataclasses for rule-based market intelligence pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketStateSnapshot:
    """Objective market facts derived from rolling history + features."""

    symbol: str
    bar_index: int = 0
    trend: str = "neutral"  # bullish | bearish | neutral
    trend_strength: str = "weak"  # weak | moderate | strong
    trend_age_candles: int = 0
    momentum: str = "flat"  # increasing | flat | decreasing
    breakout_status: str = "none"  # none | forming | confirmed | failed
    retest_status: str = "none"  # none | pending | successful | failed
    structure: str = "UNKNOWN"
    liquidity: str = "healthy"  # healthy | thin | stressed
    volatility: str = "stable"  # expanding | compressing | stable
    regime: str = "neutral"
    confidence: str = "low"  # low | medium | high
    mtf: Dict[str, str] = field(default_factory=dict)
    direction_bias: str = "HOLD"  # LONG | SHORT | HOLD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "trend": self.trend,
            "trend_strength": self.trend_strength,
            "trend_age_candles": self.trend_age_candles,
            "momentum": self.momentum,
            "breakout_status": self.breakout_status,
            "retest_status": self.retest_status,
            "structure": self.structure,
            "liquidity": self.liquidity,
            "volatility": self.volatility,
            "regime": self.regime,
            "confidence": self.confidence,
            "mtf": dict(self.mtf),
            "direction_bias": self.direction_bias,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MarketStateSnapshot":
        return cls(
            symbol=str(raw.get("symbol") or ""),
            bar_index=int(raw.get("bar_index") or 0),
            trend=str(raw.get("trend") or "neutral"),
            trend_strength=str(raw.get("trend_strength") or "weak"),
            trend_age_candles=int(raw.get("trend_age_candles") or 0),
            momentum=str(raw.get("momentum") or "flat"),
            breakout_status=str(raw.get("breakout_status") or "none"),
            retest_status=str(raw.get("retest_status") or "none"),
            structure=str(raw.get("structure") or "UNKNOWN"),
            liquidity=str(raw.get("liquidity") or "healthy"),
            volatility=str(raw.get("volatility") or "stable"),
            regime=str(raw.get("regime") or "neutral"),
            confidence=str(raw.get("confidence") or "low"),
            mtf=dict(raw.get("mtf") or {}),
            direction_bias=str(raw.get("direction_bias") or "HOLD"),
        )


@dataclass
class NarrativeEvent:
    """Single timestamped market narrative event."""

    event_type: str
    timestamp: str
    bar_index: int
    detail: Dict[str, Any] = field(default_factory=dict)
    count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "bar_index": self.bar_index,
            "detail": dict(self.detail),
        }
        if self.count is not None:
            out["count"] = self.count
        return out


@dataclass
class StructuralGateResult:
    """Categorical structural permission result."""

    trade_allowed: bool
    categories: Dict[str, bool] = field(default_factory=dict)
    block_reasons: List[str] = field(default_factory=list)
    setup_type: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_allowed": self.trade_allowed,
            "categories": dict(self.categories),
            "block_reasons": list(self.block_reasons),
            "setup_type": self.setup_type,
        }


@dataclass
class FSMDecision:
    """Market FSM lifecycle decision."""

    fsm_state: str
    entry_signal: str
    exit_signal: bool = False
    abstention_reason: Optional[str] = None
    narrative_tail: List[Dict[str, Any]] = field(default_factory=list)
    thesis_health: str = "healthy"
    position_lifecycle: str = "watching"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fsm_state": self.fsm_state,
            "entry_signal": self.entry_signal,
            "exit_signal": self.exit_signal,
            "abstention_reason": self.abstention_reason,
            "narrative_tail": list(self.narrative_tail),
            "thesis_health": self.thesis_health,
            "position_lifecycle": self.position_lifecycle,
        }


@dataclass
class RuleBasedPipelineResult:
    """Full rule-based pipeline output for one cycle."""

    market_state: MarketStateSnapshot
    narrative_events: List[NarrativeEvent] = field(default_factory=list)
    narrative_tail: List[Dict[str, Any]] = field(default_factory=list)
    structural_gates: StructuralGateResult = field(
        default_factory=lambda: StructuralGateResult(trade_allowed=False)
    )
    fsm_decision: FSMDecision = field(
        default_factory=lambda: FSMDecision(fsm_state="Watching", entry_signal="HOLD")
    )
    structural_confidence: float = 0.5
    position_size_fraction: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_state": self.market_state.to_dict(),
            "narrative_events": [e.to_dict() for e in self.narrative_events],
            "narrative_tail": list(self.narrative_tail),
            "structural_gates": self.structural_gates.to_dict(),
            "fsm_decision": self.fsm_decision.to_dict(),
            "structural_confidence": self.structural_confidence,
            "position_size_fraction": self.position_size_fraction,
        }
