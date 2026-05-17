"""
Agent policy engine — sole authority for autonomous trade intent on the event bus.

ML outputs are packaged as :class:`MLEvidenceSnapshot` (schemas); this module
produces a :class:`PolicyVerdict` that may adopt, veto, or fuse ML with rule-based thesis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.events.schemas import MLEvidenceSnapshot, PolicyVerdict
from agent.core.config import settings
from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict, agent_thesis_engine

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_POLICY_MODES = frozenset(
    {"ml_only", "thesis_only", "ml_or_thesis", "ml_and_thesis", "thesis_veto_ml"}
)


def conclusion_to_ml_signal_and_size(conclusion: str) -> Tuple[str, float]:
    """Map a reasoning conclusion string to a discrete ML-style signal and default size."""
    c = (conclusion or "").lower()
    if "strong_buy" in c or "strong buy" in c:
        return "STRONG_BUY", 0.1
    if "strong_sell" in c or "strong sell" in c:
        return "STRONG_SELL", 0.1
    if "buy" in c:
        return "BUY", 0.05
    if "sell" in c:
        return "SELL", 0.05
    return "HOLD", 0.0


def build_ml_evidence_from_orchestrator_result(result: Dict[str, Any]) -> MLEvidenceSnapshot:
    """Build ML evidence snapshot from a full MCP orchestrator prediction result dict."""
    symbol = str(result.get("symbol") or settings.trading_symbol or "BTCUSD")
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    mc = result.get("market_context") if isinstance(result.get("market_context"), dict) else {}
    models = result.get("models") if isinstance(result.get("models"), dict) else {}
    preds = result.get("model_predictions")
    if not isinstance(preds, list):
        preds = models.get("predictions") or []

    excerpt: Dict[str, Any] = {}
    if isinstance(mc, dict):
        for k in (
            "v43_gate_reject",
            "v43_training_forward_bars",
            "v43_dedicated_decision",
            "v43_execution_profile",
        ):
            if k in mc:
                excerpt[k] = mc[k]

    regime = None
    if isinstance(mc, dict):
        regime = mc.get("regime") or mc.get("v43_regime")

    return MLEvidenceSnapshot(
        symbol=symbol,
        source="v43_orchestrator",
        ml_candidate_signal=str(decision.get("signal") or "HOLD"),
        ml_candidate_confidence=float(decision.get("confidence") or 0.0),
        ml_candidate_position_size=float(decision.get("position_size") or 0.0),
        consensus_signal=_opt_float(models.get("consensus_prediction")),
        consensus_confidence=_opt_float(models.get("consensus_confidence")),
        model_predictions=list(preds) if isinstance(preds, list) else [],
        v43_gate_reject=mc.get("v43_gate_reject") if isinstance(mc, dict) else None,
        v43_regime=str(regime) if regime is not None else None,
        market_context_excerpt=excerpt,
    )


def build_ml_evidence_from_reasoning_context(
    symbol: str,
    market_context: Dict[str, Any],
    ml_candidate_signal: str,
    ml_candidate_confidence: float,
    ml_candidate_position_size: float,
    model_predictions: List[Dict[str, Any]],
) -> MLEvidenceSnapshot:
    """Build ML evidence when the pipeline came through standalone reasoning request."""
    mc = market_context if isinstance(market_context, dict) else {}
    excerpt: Dict[str, Any] = {}
    for k in ("v43_gate_reject", "v43_dedicated_decision", "v43_execution_profile"):
        if k in mc:
            excerpt[k] = mc[k]
    regime = mc.get("regime") or mc.get("v43_regime")
    return MLEvidenceSnapshot(
        symbol=symbol,
        source="reasoning_path",
        ml_candidate_signal=str(ml_candidate_signal or "HOLD"),
        ml_candidate_confidence=float(ml_candidate_confidence or 0.0),
        ml_candidate_position_size=float(ml_candidate_position_size or 0.0),
        consensus_signal=_opt_float(mc.get("consensus_signal")),
        consensus_confidence=_opt_float(mc.get("consensus_confidence")),
        model_predictions=list(model_predictions or []),
        v43_gate_reject=mc.get("v43_gate_reject"),
        v43_regime=str(regime) if regime is not None else None,
        market_context_excerpt=excerpt,
    )


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_signal(sig: str) -> str:
    s = str(sig or "HOLD").upper()
    if s not in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"):
        return "HOLD"
    return s


def _is_entry(sig: str) -> bool:
    return _normalize_signal(sig) in _ENTRY_SIGNALS


def _same_direction(a: str, b: str) -> bool:
    sa, sb = _normalize_signal(a), _normalize_signal(b)
    if sa in ("BUY", "STRONG_BUY") and sb in ("BUY", "STRONG_BUY"):
        return True
    if sa in ("SELL", "STRONG_SELL") and sb in ("SELL", "STRONG_SELL"):
        return True
    return sa == sb == "HOLD"


def _fuse_signals(
    ml_evidence: MLEvidenceSnapshot,
    thesis: ThesisVerdict,
    mode: str,
    conclusion: str,
) -> PolicyVerdict:
    ml_sig = _normalize_signal(ml_evidence.ml_candidate_signal)
    th_sig = _normalize_signal(thesis.signal)
    ml_entry = _is_entry(ml_sig)
    th_entry = _is_entry(th_sig)

    reasons: List[str] = [f"fusion_mode={mode}", f"thesis_type={thesis.thesis_type}"]
    reasons.extend(thesis.reason_codes[:6])

    if mode == "ml_only":
        return _verdict_from_ml(ml_evidence, ml_sig, conclusion, reasons + ["fusion_ml_only"])

    if mode == "thesis_only":
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or ml_evidence.ml_candidate_position_size or 0.05),
                reason_codes=reasons + ["agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(thesis.confidence),
            position_size=0.0,
            reason_codes=reasons + ["thesis_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=False,
        )

    if mode == "thesis_veto_ml":
        if th_sig == "HOLD" and thesis.thesis_type in ("crisis_veto", "flat") and any(
            "veto" in r for r in thesis.reason_codes
        ):
            return PolicyVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=reasons + ["thesis_veto_ml_active"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        if ml_entry:
            return _verdict_from_ml(
                ml_evidence, ml_sig, conclusion, reasons + ["thesis_veto_passed_ml_adopted"]
            )
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or 0.05),
                reason_codes=reasons + ["agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["thesis_veto_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=not ml_entry,
        )

    if mode == "ml_or_thesis":
        if ml_entry:
            return _verdict_from_ml(
                ml_evidence, ml_sig, conclusion, reasons + ["fusion_ml_or_thesis_ml"]
            )
        if th_entry:
            reasons.append("agent_thesis_entry")
            return PolicyVerdict(
                signal=th_sig,
                confidence=float(thesis.confidence),
                position_size=float(thesis.position_size or 0.05),
                reason_codes=reasons + ["fusion_ml_or_thesis_thesis", "agent_thesis_origin"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["fusion_ml_or_thesis_hold"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=True,
        )

    if mode == "ml_and_thesis":
        if ml_entry and th_entry and _same_direction(ml_sig, th_sig):
            reasons.append("agent_thesis_confirms_ml")
            v = _verdict_from_ml(
                ml_evidence,
                ml_sig,
                conclusion,
                reasons + ["fusion_ml_and_thesis_agree"],
            )
            v.confidence = max(v.confidence, float(thesis.confidence))
            return v
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons
            + [
                "fusion_ml_and_thesis_no_agreement",
                f"ml={ml_sig}",
                f"thesis={th_sig}",
            ],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=False,
        )

    return _verdict_from_ml(ml_evidence, ml_sig, conclusion, reasons + ["fusion_unknown_mode_fallback"])


def _verdict_from_ml(
    ml_evidence: MLEvidenceSnapshot,
    sig: str,
    conclusion: str,
    reasons: List[str],
) -> PolicyVerdict:
    if sig == "HOLD":
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons + ["agent_hold_ml_candidate_hold", "ml_evidence_supporting"],
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=True,
        )
    out_reasons = list(reasons) + [
        "agent_ratified_ml_evidence",
        "ml_evidence_supporting",
        f"ml_source={ml_evidence.source}",
    ]
    if conclusion:
        out_reasons.append("reasoning_conclusion_considered")
    return PolicyVerdict(
        signal=sig,
        confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
        position_size=float(ml_evidence.ml_candidate_position_size or 0.0),
        reason_codes=out_reasons,
        ml_evidence_id=ml_evidence.evidence_id,
        adopted_ml_candidate=True,
    )


class AgentPolicyEngine:
    """Evaluates ML evidence + rule thesis; emits :class:`PolicyVerdict` for the agent."""

    def __init__(self, thesis_engine: Optional[AgentThesisEngine] = None) -> None:
        self._thesis_engine = thesis_engine or agent_thesis_engine

    def evaluate(
        self,
        *,
        ml_evidence: MLEvidenceSnapshot,
        conclusion: str = "",
        market_context: Optional[Dict[str, Any]] = None,
    ) -> PolicyVerdict:
        """Return the agent policy verdict for this cycle."""
        mc = market_context if isinstance(market_context, dict) else {}
        force_hold = bool(getattr(settings, "agent_policy_force_hold", False))
        if force_hold:
            return PolicyVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["agent_policy_force_hold", "veto_all_entries"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=False,
            )

        mode = str(getattr(settings, "agent_policy_mode", "ml_only") or "ml_only").strip().lower()
        if mode not in _POLICY_MODES:
            logger.warning("agent_policy_unknown_mode", mode=mode, fallback="ml_only")
            mode = "ml_only"

        regime = ml_evidence.v43_regime or mc.get("regime") or mc.get("v43_regime")
        thesis = self._thesis_engine.evaluate(regime, mc)
        return _fuse_signals(ml_evidence, thesis, mode, conclusion)


agent_policy_engine = AgentPolicyEngine()
