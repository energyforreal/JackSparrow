"""Unified trade analysis facade — single entry point for all analytics modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from agent.intelligence.market_validation import validate_market
from agent.intelligence.post_trade_analyzer import analyze_post_trade
from agent.intelligence.signal_explainer import explain_signal


class AnalysisModule(Protocol):
    """Pluggable analysis module interface."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        ...


@dataclass
class UnifiedAssessment:
    """Combined output from all analysis modules."""

    market: Dict[str, Any] = field(default_factory=dict)
    signal: Dict[str, Any] = field(default_factory=dict)
    position: Dict[str, Any] = field(default_factory=dict)
    replay: Dict[str, Any] = field(default_factory=dict)
    calibration: Dict[str, Any] = field(default_factory=dict)
    post_trade: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market": dict(self.market),
            "signal": dict(self.signal),
            "position": dict(self.position),
            "replay": dict(self.replay),
            "calibration": dict(self.calibration),
            "post_trade": dict(self.post_trade),
        }


class MarketAnalysisModule:
    """Market validation and regime benchmarks."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
        mv = dc.get("market_validation")
        if isinstance(mv, dict) and mv:
            return {"market_validation": mv}
        rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
        ms = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
        gates = dc.get("gate_evaluation") if isinstance(dc.get("gate_evaluation"), dict) else {}
        cats = gates.get("categories") if isinstance(gates.get("categories"), dict) else {}
        result = validate_market(market_state=ms, gate_categories=cats)
        return {"market_validation": result.to_dict()}


class SignalAnalysisModule:
    """Signal explainability from snapshot."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
        expl = dc.get("signal_explanation")
        if isinstance(expl, dict) and expl:
            return {"signal_explanation": expl}
        rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
        gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
        fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
        ms = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
        expl = explain_signal(
            signal=str(dc.get("signal") or "HOLD"),
            structural_confidence=float(rb.get("structural_confidence") or dc.get("confidence") or 0.5),
            gate_categories=gates.get("categories"),
            block_reasons=gates.get("block_reasons"),
            fsm_state=str(fsm.get("fsm_state") or ""),
            setup_type=str(gates.get("setup_type") or "none"),
            market_state=ms,
        )
        return {"signal_explanation": expl}


class PositionAnalysisModule:
    """Position monitoring and structure timeline."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        monitoring = snapshot.get("position_monitoring")
        timeline = snapshot.get("market_structure_timeline")
        out: Dict[str, Any] = {}
        if isinstance(monitoring, list):
            out["position_monitoring_count"] = len(monitoring)
            if monitoring:
                last = monitoring[-1]
                out["last_health_score"] = last.get("health_score")
                out["last_opportunity_score"] = last.get("opportunity_score")
        if isinstance(timeline, list):
            out["market_structure_timeline"] = timeline
        return out


class PostTradeModule:
    """Four-dimension post-trade quality assessment."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        assessment = snapshot.get("post_trade_assessment")
        if isinstance(assessment, dict) and assessment:
            return {"post_trade_assessment": assessment}
        if snapshot.get("snapshot_kind") != "closed_round_trip":
            return {}
        result = analyze_post_trade(snapshot)
        return {"post_trade_assessment": result}


class ReplayAnalysisModule:
    """Placeholder for replay-derived metrics attached to snapshot."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        replay = snapshot.get("replay_assessment")
        if isinstance(replay, dict):
            return {"replay_assessment": replay}
        return {}


class CalibrationModule:
    """Confidence bucket metadata from snapshot."""

    def analyze(self, snapshot: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
        dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
        conf = dc.get("structural_confidence") or dc.get("confidence")
        if conf is None:
            return {}
        try:
            c = float(conf)
            if c > 1.0:
                c = c / 100.0
            bucket = int(c * 10) * 10
            return {"confidence_bucket": f"{bucket}-{bucket + 10}"}
        except (TypeError, ValueError):
            return {}


class TradeAnalysisEngine:
    """Orchestrates all analysis modules into a unified assessment."""

    def __init__(self, modules: Optional[List[AnalysisModule]] = None) -> None:
        self._modules: List[AnalysisModule] = modules or [
            MarketAnalysisModule(),
            SignalAnalysisModule(),
            PositionAnalysisModule(),
            PostTradeModule(),
            ReplayAnalysisModule(),
            CalibrationModule(),
        ]

    def run(self, snapshot: Dict[str, Any], *, context: Optional[Dict[str, Any]] = None) -> UnifiedAssessment:
        """Run all modules and merge results."""
        ctx = context or {}
        assessment = UnifiedAssessment()
        for module in self._modules:
            chunk = module.analyze(snapshot, context=ctx)
            if "market_validation" in chunk:
                assessment.market.update(chunk)
            if "signal_explanation" in chunk:
                assessment.signal.update(chunk)
            if any(k in chunk for k in ("position_monitoring_count", "market_structure_timeline")):
                assessment.position.update(chunk)
            if "post_trade_assessment" in chunk:
                assessment.post_trade.update(chunk)
            if "replay_assessment" in chunk:
                assessment.replay.update(chunk)
            if "confidence_bucket" in chunk:
                assessment.calibration.update(chunk)
        return assessment


trade_analysis_engine = TradeAnalysisEngine()
