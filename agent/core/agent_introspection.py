"""Deterministic agent introspection snapshot builder.

Read-only self-awareness telemetry: summarizes policy, ML, thesis, scoring,
and portfolio guard state at decision time without changing trade authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.core.config import settings

INTROSPECTION_VERSION = "1.0"


@dataclass
class AgentIntrospectionSnapshot:
    """Versioned introspection block attached to DecisionReadyEvent."""

    version: str = INTROSPECTION_VERSION
    timestamp: str = ""
    symbol: str = ""
    agent_state: str = "unknown"
    policy_mode: str = ""
    policy_signal: str = ""
    policy_confidence: float = 0.0
    policy_reason_codes: List[str] = field(default_factory=list)
    ml_candidate_signal: Optional[str] = None
    thesis_signal: Optional[str] = None
    trade_score: Optional[float] = None
    trade_score_pass: Optional[bool] = None
    v43_regime: Optional[str] = None
    v43_gate_reject: Optional[str] = None
    regime_bar_age: Optional[int] = None
    regime_transition_risk: Optional[str] = None
    portfolio_guard_action: Optional[str] = None
    portfolio_guard_reason_codes: List[str] = field(default_factory=list)
    memory_enabled: bool = False
    memory_context_count: int = 0
    limits: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "agent_state": self.agent_state,
            "policy_mode": self.policy_mode,
            "policy_signal": self.policy_signal,
            "policy_confidence": self.policy_confidence,
            "policy_reason_codes": list(self.policy_reason_codes),
            "ml_candidate_signal": self.ml_candidate_signal,
            "thesis_signal": self.thesis_signal,
            "trade_score": self.trade_score,
            "trade_score_pass": self.trade_score_pass,
            "v43_regime": self.v43_regime,
            "v43_gate_reject": self.v43_gate_reject,
            "regime_bar_age": self.regime_bar_age,
            "regime_transition_risk": self.regime_transition_risk,
            "portfolio_guard_action": self.portfolio_guard_action,
            "portfolio_guard_reason_codes": list(self.portfolio_guard_reason_codes),
            "memory_enabled": self.memory_enabled,
            "memory_context_count": self.memory_context_count,
            "limits": dict(self.limits),
        }


def _resolve_agent_state() -> str:
    try:
        from agent.core.context_manager import context_manager

        st = context_manager.get_state()
        if st is not None:
            return str(getattr(st, "state", None) or getattr(st, "agent_state", None) or "unknown")
    except Exception:
        pass
    return "unknown"


def build_introspection_snapshot(
    *,
    symbol: str,
    signal: str,
    confidence: float,
    policy_reason_codes: Optional[List[str]] = None,
    policy_verdict: Optional[Dict[str, Any]] = None,
    ml_evidence_snapshot: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    trade_score: Optional[float] = None,
    memory_context_count: int = 0,
    memory_enabled: bool = False,
) -> AgentIntrospectionSnapshot:
    """Build deterministic introspection from orchestrator decision inputs."""
    now = datetime.now(timezone.utc).isoformat()
    pv = policy_verdict if isinstance(policy_verdict, dict) else {}
    ml = ml_evidence_snapshot if isinstance(ml_evidence_snapshot, dict) else {}
    mctx = market_context if isinstance(market_context, dict) else {}

    ts_val = trade_score
    if ts_val is None:
        ts_raw = ml.get("trade_score")
        if ts_raw is not None:
            try:
                ts_val = float(ts_raw)
            except (TypeError, ValueError):
                ts_val = None
    if ts_val is None and isinstance(mctx.get("trade_score"), dict):
        try:
            ts_val = float(mctx["trade_score"].get("score"))
        except (TypeError, ValueError, AttributeError):
            pass
    elif ts_val is None and mctx.get("trade_score") is not None:
        try:
            ts_val = float(mctx["trade_score"])
        except (TypeError, ValueError):
            pass

    min_score = float(getattr(settings, "agent_trade_score_min", 70.0) or 70.0)
    trade_pass: Optional[bool] = None
    if ts_val is not None:
        trade_pass = ts_val >= min_score

    pg = mctx.get("portfolio_guard")
    pg_action: Optional[str] = None
    pg_codes: List[str] = []
    if isinstance(pg, dict):
        pg_action = pg.get("action")
        raw_codes = pg.get("reason_codes")
        if isinstance(raw_codes, list):
            pg_codes = [str(c) for c in raw_codes]

    excerpt = ml.get("market_context_excerpt")
    if not isinstance(excerpt, dict):
        excerpt = {}
    v43_regime = ml.get("v43_regime") or excerpt.get("v43_regime")
    v43_gate = ml.get("v43_gate_reject") or excerpt.get("v43_gate_reject")

    ml_validation = mctx.get("ml_validation")
    if v43_regime is None and isinstance(ml_validation, dict):
        v43_regime = ml_validation.get("regime")
    if v43_gate is None and isinstance(ml_validation, dict):
        v43_gate = ml_validation.get("gate_reject")

    regime_bar_age: Optional[int] = None
    regime_transition_risk: Optional[str] = None
    if isinstance(mctx, dict):
        rba = mctx.get("regime_bar_age")
        if rba is not None:
            try:
                regime_bar_age = int(rba)
            except (TypeError, ValueError):
                regime_bar_age = None
        rtr = mctx.get("regime_transition_risk")
        if rtr is not None:
            regime_transition_risk = str(rtr)

    limits: Dict[str, Any] = {
        "trade_score_min": min_score,
        "require_ml_signal_for_orders": bool(
            getattr(settings, "require_ml_signal_for_orders", False)
        ),
        "agent_policy_force_hold": bool(getattr(settings, "agent_policy_force_hold", False)),
    }

    return AgentIntrospectionSnapshot(
        version=INTROSPECTION_VERSION,
        timestamp=now,
        symbol=str(symbol or ""),
        agent_state=_resolve_agent_state(),
        policy_mode=str(getattr(settings, "agent_policy_mode", "") or ""),
        policy_signal=str(signal or "HOLD"),
        policy_confidence=float(confidence or 0.0),
        policy_reason_codes=list(policy_reason_codes or pv.get("reason_codes") or []),
        ml_candidate_signal=ml.get("ml_candidate_signal"),
        thesis_signal=ml.get("thesis_signal"),
        trade_score=ts_val,
        trade_score_pass=trade_pass,
        v43_regime=str(v43_regime) if v43_regime is not None else None,
        v43_gate_reject=str(v43_gate) if v43_gate is not None else None,
        regime_bar_age=regime_bar_age,
        regime_transition_risk=regime_transition_risk,
        portfolio_guard_action=str(pg_action) if pg_action is not None else None,
        portfolio_guard_reason_codes=pg_codes,
        memory_enabled=memory_enabled,
        memory_context_count=int(memory_context_count),
        limits=limits,
    )
