"""
Agent policy engine — sole authority for autonomous trade intent on the event bus.

ML outputs are packaged as :class:`MLEvidenceSnapshot` (schemas); this module
produces a :class:`PolicyVerdict` that may adopt or veto the ML candidate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.events.schemas import MLEvidenceSnapshot, PolicyVerdict
from agent.core.config import settings

logger = structlog.get_logger()


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


class AgentPolicyEngine:
    """Evaluates ML evidence and emits a single :class:`PolicyVerdict` for the agent."""

    def evaluate(
        self,
        *,
        ml_evidence: MLEvidenceSnapshot,
        conclusion: str = "",
        market_context: Optional[Dict[str, Any]] = None,
    ) -> PolicyVerdict:
        """Return the agent policy verdict for this cycle.

        Default policy: adopt the ML candidate after orchestrator+gates unless
        ``agent_policy_force_hold`` is set. Veto hooks can be extended here
        (regime, kill-switch, portfolio overlays).
        """
        _ = market_context  # reserved for future portfolio-aware vetoes
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

        sig = str(ml_evidence.ml_candidate_signal or "HOLD").upper()
        if sig not in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"):
            sig = "HOLD"

        if sig == "HOLD":
            return PolicyVerdict(
                signal="HOLD",
                confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
                position_size=0.0,
                reason_codes=["agent_hold_ml_candidate_hold", "ml_evidence_supporting"],
                ml_evidence_id=ml_evidence.evidence_id,
                adopted_ml_candidate=True,
            )

        reasons = [
            "agent_ratified_ml_evidence",
            "ml_evidence_supporting",
            f"ml_source={ml_evidence.source}",
        ]
        if conclusion:
            reasons.append("reasoning_conclusion_considered")

        return PolicyVerdict(
            signal=sig,
            confidence=float(ml_evidence.ml_candidate_confidence or 0.0),
            position_size=float(ml_evidence.ml_candidate_position_size or 0.0),
            reason_codes=reasons,
            ml_evidence_id=ml_evidence.evidence_id,
            adopted_ml_candidate=True,
        )


agent_policy_engine = AgentPolicyEngine()
