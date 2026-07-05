"""Frozen cognition slice types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent.intelligence.cognition.artifacts import ReasoningArtifact


@dataclass(frozen=True)
class MarketUnderstanding:
    """Present-tense market facts (immutable slice)."""

    symbol: str
    bar_index: int = 0
    trend: str = "neutral"
    trend_strength: str = "weak"
    trend_age_candles: int = 0
    momentum: str = "flat"
    breakout_status: str = "none"
    retest_status: str = "none"
    structure: str = "UNKNOWN"
    liquidity: str = "healthy"
    volatility: str = "stable"
    regime: str = "neutral"
    confidence: str = "low"
    direction_bias: str = "HOLD"
    regime_benchmark: str = "ranging"
    mtf: Tuple[Tuple[str, str], ...] = ()

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
            "direction_bias": self.direction_bias,
            "regime_benchmark": self.regime_benchmark,
            "mtf": dict(self.mtf),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MarketUnderstanding":
        mtf_raw = raw.get("mtf") or {}
        mtf = tuple(mtf_raw.items()) if isinstance(mtf_raw, dict) else ()
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
            direction_bias=str(raw.get("direction_bias") or "HOLD"),
            regime_benchmark=str(raw.get("regime_benchmark") or "ranging"),
            mtf=mtf,
        )


@dataclass(frozen=True)
class BehavioralEvent:
    """Single decay-weighted behavioral memory entry."""

    event_type: str
    bar_index: int
    weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "bar_index": int(self.bar_index),
            "weight": float(self.weight),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "BehavioralEvent":
        return cls(
            event_type=str(raw.get("event_type") or ""),
            bar_index=int(raw.get("bar_index") or 0),
            weight=float(raw.get("weight") or 1.0),
        )


@dataclass(frozen=True)
class MarketMemory:
    """Compact behavioral/structural history with time decay."""

    symbol: str = ""
    bar_index: int = 0
    failed_breakout_count: int = 0
    failed_breakout_weighted: float = 0.0
    liquidity_sweep_weighted: float = 0.0
    rejection_weighted: float = 0.0
    range_duration_bars: int = 0
    trend_duration_bars: int = 0
    hh_hl_sequence: str = "neutral"
    regime_history: Tuple[str, ...] = ()
    last_false_signal_bars_ago: Optional[int] = None
    behavioral_events: Tuple[BehavioralEvent, ...] = ()
    behavioral_scores: Tuple[Tuple[str, float], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "failed_breakout_count": self.failed_breakout_count,
            "failed_breakout_weighted": self.failed_breakout_weighted,
            "liquidity_sweep_weighted": self.liquidity_sweep_weighted,
            "rejection_weighted": self.rejection_weighted,
            "range_duration_bars": self.range_duration_bars,
            "trend_duration_bars": self.trend_duration_bars,
            "hh_hl_sequence": self.hh_hl_sequence,
            "regime_history": list(self.regime_history),
            "last_false_signal_bars_ago": self.last_false_signal_bars_ago,
            "behavioral_events": [e.to_dict() for e in self.behavioral_events],
            "behavioral_scores": dict(self.behavioral_scores),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MarketMemory":
        events = tuple(
            BehavioralEvent.from_dict(e)
            for e in (raw.get("behavioral_events") or [])
            if isinstance(e, dict)
        )
        scores_raw = raw.get("behavioral_scores") or {}
        scores = tuple(scores_raw.items()) if isinstance(scores_raw, dict) else ()
        hist = raw.get("regime_history") or []
        return cls(
            symbol=str(raw.get("symbol") or ""),
            bar_index=int(raw.get("bar_index") or 0),
            failed_breakout_count=int(raw.get("failed_breakout_count") or 0),
            failed_breakout_weighted=float(raw.get("failed_breakout_weighted") or 0.0),
            liquidity_sweep_weighted=float(raw.get("liquidity_sweep_weighted") or 0.0),
            rejection_weighted=float(raw.get("rejection_weighted") or 0.0),
            range_duration_bars=int(raw.get("range_duration_bars") or 0),
            trend_duration_bars=int(raw.get("trend_duration_bars") or 0),
            hh_hl_sequence=str(raw.get("hh_hl_sequence") or "neutral"),
            regime_history=tuple(str(r) for r in hist),
            last_false_signal_bars_ago=raw.get("last_false_signal_bars_ago"),
            behavioral_events=events,
            behavioral_scores=scores,
        )


@dataclass(frozen=True)
class ExpectationHorizon:
    """Expectation dimensions for one forward horizon."""

    horizon_minutes: int
    trend_persistence: float = 0.5
    breakout_likelihood: float = 0.5
    reversal_risk: float = 0.5
    volatility_expansion: float = 0.5
    liquidity_sweep_risk: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_minutes": self.horizon_minutes,
            "trend_persistence": self.trend_persistence,
            "breakout_likelihood": self.breakout_likelihood,
            "reversal_risk": self.reversal_risk,
            "volatility_expansion": self.volatility_expansion,
            "liquidity_sweep_risk": self.liquidity_sweep_risk,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ExpectationHorizon":
        return cls(
            horizon_minutes=int(raw.get("horizon_minutes") or 0),
            trend_persistence=float(raw.get("trend_persistence") or 0.5),
            breakout_likelihood=float(raw.get("breakout_likelihood") or 0.5),
            reversal_risk=float(raw.get("reversal_risk") or 0.5),
            volatility_expansion=float(raw.get("volatility_expansion") or 0.5),
            liquidity_sweep_risk=float(raw.get("liquidity_sweep_risk") or 0.0),
        )


@dataclass(frozen=True)
class ExpectationState:
    """Forward scenario expectations (revisable beliefs)."""

    horizons: Tuple[ExpectationHorizon, ...] = ()
    dominant_expectation: str = "neutral"
    confidence: float = 0.0
    delta_from_prior: float = 0.0
    revision_drivers: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizons": [h.to_dict() for h in self.horizons],
            "dominant_expectation": self.dominant_expectation,
            "confidence": self.confidence,
            "delta_from_prior": self.delta_from_prior,
            "revision_drivers": list(self.revision_drivers),
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ExpectationState":
        horizons = tuple(
            ExpectationHorizon.from_dict(h)
            for h in (raw.get("horizons") or [])
            if isinstance(h, dict)
        )
        return cls(
            horizons=horizons,
            dominant_expectation=str(raw.get("dominant_expectation") or "neutral"),
            confidence=float(raw.get("confidence") or 0.0),
            delta_from_prior=float(raw.get("delta_from_prior") or 0.0),
            revision_drivers=tuple(str(d) for d in (raw.get("revision_drivers") or [])),
            reason_codes=tuple(str(c) for c in (raw.get("reason_codes") or [])),
        )


@dataclass(frozen=True)
class ScenarioState:
    """Current market phase classification."""

    primary: str = "range"
    confidence: float = 0.0
    sub_signals: Tuple[str, ...] = ()
    previous_primary: Optional[str] = None
    revision_reason: Optional[str] = None
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary,
            "confidence": self.confidence,
            "sub_signals": list(self.sub_signals),
            "previous_primary": self.previous_primary,
            "revision_reason": self.revision_reason,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ScenarioState":
        return cls(
            primary=str(raw.get("primary") or "range"),
            confidence=float(raw.get("confidence") or 0.0),
            sub_signals=tuple(str(s) for s in (raw.get("sub_signals") or [])),
            previous_primary=raw.get("previous_primary"),
            revision_reason=raw.get("revision_reason"),
            reason_codes=tuple(str(c) for c in (raw.get("reason_codes") or [])),
        )


@dataclass(frozen=True)
class RiskIntelligenceState:
    """Opportunity vs risk context for strategy selection."""

    volatility_elevated: bool = False
    market_unstable: bool = False
    risk_budget_consumed_pct: float = 0.0
    recent_stopout_degradation: float = 0.0
    trade_environment_score: float = 0.5
    reason_codes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "volatility_elevated": self.volatility_elevated,
            "market_unstable": self.market_unstable,
            "risk_budget_consumed_pct": self.risk_budget_consumed_pct,
            "recent_stopout_degradation": self.recent_stopout_degradation,
            "trade_environment_score": self.trade_environment_score,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "RiskIntelligenceState":
        return cls(
            volatility_elevated=bool(raw.get("volatility_elevated")),
            market_unstable=bool(raw.get("market_unstable")),
            risk_budget_consumed_pct=float(raw.get("risk_budget_consumed_pct") or 0.0),
            recent_stopout_degradation=float(raw.get("recent_stopout_degradation") or 0.0),
            trade_environment_score=float(raw.get("trade_environment_score") or 0.5),
            reason_codes=tuple(str(c) for c in (raw.get("reason_codes") or [])),
        )


@dataclass(frozen=True)
class StrategySelectionEntry:
    profile_id: str
    eligible: bool = False
    abstention_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "eligible": self.eligible,
            "abstention_reason": self.abstention_reason,
        }


@dataclass(frozen=True)
class StrategySelectionResult:
    entries: Tuple[StrategySelectionEntry, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    def eligible_ids(self) -> Tuple[str, ...]:
        return tuple(e.profile_id for e in self.entries if e.eligible)


@dataclass(frozen=True)
class StrategyScoreEntry:
    profile_id: str
    base_confidence: float = 0.0
    adjustments: Tuple[Tuple[str, float], ...] = ()
    adjusted_confidence: float = 0.0
    agreement_with: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "base_confidence": self.base_confidence,
            "adjustments": dict(self.adjustments),
            "adjusted_confidence": self.adjusted_confidence,
            "agreement_with": list(self.agreement_with),
        }


@dataclass(frozen=True)
class StrategyScoreResult:
    entries: Tuple[StrategyScoreEntry, ...] = ()
    consensus_direction: str = "FLAT"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "consensus_direction": self.consensus_direction,
        }


@dataclass(frozen=True)
class StrategyProfile:
    """Declarative strategy environment requirements."""

    id: str
    supported_scenarios: Tuple[str, ...] = ()
    expectation_thresholds: Tuple[Tuple[str, Tuple[float, float]], ...] = ()
    risk_floor: float = 0.0
    horizon_minutes: int = 30
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "supported_scenarios": list(self.supported_scenarios),
            "expectation_thresholds": dict(self.expectation_thresholds),
            "risk_floor": self.risk_floor,
            "horizon_minutes": self.horizon_minutes,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class CognitionMeta:
    symbol: str = ""
    bar_index: int = 0
    cycle_id: str = ""
    schema_version: str = "3.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "cycle_id": self.cycle_id,
            "schema_version": self.schema_version,
        }
