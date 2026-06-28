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

_GATED_ML_ADOPT_CODES = frozenset(
    {
        "fusion_ml_gated_thesis_neutral",
        "fusion_ml_or_thesis_gated_neutral",
        "fusion_ml_or_thesis_ml",
    }
)


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
    p_regime_favorable: Optional[float] = None
    p_setup_quality: Optional[float] = None
    p_vol_expansion: Optional[float] = None
    uncertainty_score: Optional[float] = None
    regime_bar_age: Optional[int] = None
    regime_transition_risk: Optional[str] = None
    portfolio_guard_action: Optional[str] = None
    portfolio_guard_reason_codes: List[str] = field(default_factory=list)
    memory_enabled: bool = False
    memory_context_count: int = 0
    conviction: Optional[float] = None
    size_fraction: Optional[float] = None
    abstention: Optional[str] = None
    evidence_summary: Optional[Dict[str, float]] = None
    hypothesis_top: Optional[List[Dict[str, Any]]] = None
    environment_scores: Optional[Dict[str, float]] = None
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
            "p_regime_favorable": self.p_regime_favorable,
            "p_setup_quality": self.p_setup_quality,
            "p_vol_expansion": self.p_vol_expansion,
            "uncertainty_score": self.uncertainty_score,
            "regime_bar_age": self.regime_bar_age,
            "regime_transition_risk": self.regime_transition_risk,
            "portfolio_guard_action": self.portfolio_guard_action,
            "portfolio_guard_reason_codes": list(self.portfolio_guard_reason_codes),
            "memory_enabled": self.memory_enabled,
            "memory_context_count": self.memory_context_count,
            "conviction": self.conviction,
            "size_fraction": self.size_fraction,
            "abstention": self.abstention,
            "evidence_summary": dict(self.evidence_summary) if self.evidence_summary else None,
            "hypothesis_top": list(self.hypothesis_top) if self.hypothesis_top else None,
            "environment_scores": (
                dict(self.environment_scores) if self.environment_scores else None
            ),
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

    reason_codes = list(policy_reason_codes or pv.get("reason_codes") or [])
    min_score = float(getattr(settings, "agent_trade_score_min", 55.0) or 55.0)
    if any(c in _GATED_ML_ADOPT_CODES for c in reason_codes):
        min_score = min(
            min_score,
            float(
                getattr(settings, "agent_trade_score_min_gated_ml_adoption", 30.0) or 30.0
            ),
        )

    ts_dict = mctx.get("trade_score")
    ts_passed_from_ctx: Optional[bool] = None
    if isinstance(ts_dict, dict) and ts_dict.get("passed") is not None:
        ts_passed_from_ctx = bool(ts_dict["passed"])

    ml_validation = mctx.get("ml_validation")
    final_long = False
    final_short = False
    if isinstance(ml_validation, dict):
        final_long = bool(ml_validation.get("final_long"))
        final_short = bool(ml_validation.get("final_short"))

    trade_pass: Optional[bool] = None
    if ts_passed_from_ctx is not None or ts_val is not None:
        score_ok = bool(ts_passed_from_ctx) or (
            ts_val is not None
            and float(ts_val) >= min_score
            and (final_long or final_short)
        )
        trade_pass = score_ok

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

    def _ml_float(key: str) -> Optional[float]:
        raw = ml.get(key)
        if raw is None:
            raw = mctx.get(key) if isinstance(mctx, dict) else None
        if raw is None:
            raw = excerpt.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    limits: Dict[str, Any] = {
        "trade_score_min": min_score,
        "conviction_entry_floor": float(
            getattr(settings, "conviction_entry_floor", 0.35) or 0.35
        ),
        "evidence_based_sizing": bool(getattr(settings, "evidence_based_sizing", True)),
        "require_ic_validation_for_orders": bool(
            getattr(
                settings,
                "require_ic_validation_for_orders",
                getattr(settings, "require_ml_signal_for_orders", False),
            )
        ),
        "agent_policy_force_hold": bool(getattr(settings, "agent_policy_force_hold", False)),
    }

    conv_val: Optional[float] = None
    size_frac: Optional[float] = None
    abstention_val: Optional[str] = None
    evidence_summary: Optional[Dict[str, float]] = None
    if pv.get("conviction") is not None:
        try:
            conv_val = float(pv["conviction"])
        except (TypeError, ValueError):
            pass
    elif isinstance(mctx.get("conviction"), dict):
        try:
            conv_val = float(mctx["conviction"].get("conviction"))
        except (TypeError, ValueError, AttributeError):
            pass
    if pv.get("size_fraction") is not None:
        try:
            size_frac = float(pv["size_fraction"])
        except (TypeError, ValueError):
            pass
    elif isinstance(mctx.get("conviction"), dict):
        try:
            size_frac = float(mctx["conviction"].get("size_fraction"))
        except (TypeError, ValueError, AttributeError):
            pass
    abstention_val = pv.get("abstention")
    ev_raw = pv.get("evidence") or mctx.get("evidence_bundle")
    if isinstance(ev_raw, dict):
        scores = ev_raw.get("scores")
        if isinstance(scores, dict):
            evidence_summary = {str(k): float(v) for k, v in scores.items() if v is not None}

    hypothesis_top: Optional[List[Dict[str, Any]]] = None
    environment_scores: Optional[Dict[str, float]] = None
    hyp_raw = mctx.get("hypothesis_snapshot")
    if isinstance(hyp_raw, dict):
        hyps = hyp_raw.get("hypotheses")
        if isinstance(hyps, list):
            ranked = sorted(
                [h for h in hyps if isinstance(h, dict)],
                key=lambda x: float(x.get("weighted_confidence") or x.get("confidence") or 0),
                reverse=True,
            )
            hypothesis_top = ranked[:3]
        env = hyp_raw.get("environment")
        if isinstance(env, dict):
            environment_scores = {str(k): float(v) for k, v in env.items()}
    if environment_scores is None and isinstance(mctx.get("environment_scores"), dict):
        environment_scores = {
            str(k): float(v) for k, v in mctx["environment_scores"].items()
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
        p_regime_favorable=_ml_float("p_regime_favorable"),
        p_setup_quality=_ml_float("p_setup_quality"),
        p_vol_expansion=_ml_float("p_vol_expansion"),
        uncertainty_score=_ml_float("uncertainty_score"),
        regime_bar_age=regime_bar_age,
        regime_transition_risk=regime_transition_risk,
        portfolio_guard_action=str(pg_action) if pg_action is not None else None,
        portfolio_guard_reason_codes=pg_codes,
        memory_enabled=memory_enabled,
        memory_context_count=int(memory_context_count),
        conviction=conv_val,
        size_fraction=size_frac,
        abstention=str(abstention_val) if abstention_val else None,
        evidence_summary=evidence_summary,
        hypothesis_top=hypothesis_top,
        environment_scores=environment_scores,
        limits=limits,
    )
