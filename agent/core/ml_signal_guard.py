"""Ensure exchange entry orders are driven only by ML model signals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_BUY_SIGNALS = frozenset({"BUY", "STRONG_BUY"})
_SELL_SIGNALS = frozenset({"SELL", "STRONG_SELL"})


def _side_from_trade_signal(signal: str) -> Optional[str]:
    s = str(signal or "").upper()
    if s in _BUY_SIGNALS:
        return "BUY"
    if s in _SELL_SIGNALS:
        return "SELL"
    return None


def _normalize_predictions(model_predictions: Any) -> List[Dict[str, Any]]:
    if not isinstance(model_predictions, list):
        return []
    return [p for p in model_predictions if isinstance(p, dict)]


def _has_healthy_model_predictions(model_predictions: List[Dict[str, Any]]) -> bool:
    if not model_predictions:
        return False
    for pred in model_predictions:
        if pred.get("healthy") is False:
            continue
        if pred.get("prediction") is not None:
            return True
        if pred.get("confidence") is not None:
            try:
                if float(pred["confidence"]) > 0:
                    return True
            except (TypeError, ValueError):
                pass
        if pred.get("model_name") or pred.get("model_version"):
            return True
    return False


def _ml_validation_gates_passed(market_context: Dict[str, Any], side: str) -> Tuple[bool, str]:
    """Require ml_validation.final_long/final_short aligned with entry side."""
    ml_val = market_context.get("ml_validation")
    if not isinstance(ml_val, dict):
        return False, "ml_validation_missing"
    if side == "BUY":
        if not bool(ml_val.get("final_long")):
            return False, "ml_validation_final_long_false"
        return True, "ml_validation_long_gates_passed"
    if side == "SELL":
        if not bool(ml_val.get("final_short")):
            return False, "ml_validation_final_short_false"
        return True, "ml_validation_short_gates_passed"
    return False, "ml_validation_invalid_side"


def _v43_gates_passed(market_context: Dict[str, Any], side: str) -> Tuple[bool, str]:
    v43_exec = market_context.get("v43_execution_profile")
    if not isinstance(v43_exec, dict) or not v43_exec.get("enabled"):
        return False, "v43_profile_not_enabled"

    if market_context.get("v43_gate_reject") is not None:
        return False, f"v43_gate_reject={market_context.get('v43_gate_reject')}"

    v43_dec = market_context.get("v43_dedicated_decision")
    if not isinstance(v43_dec, dict) or not v43_dec.get("enabled"):
        return False, "v43_decision_missing"

    ml_ok, ml_reason = _ml_validation_gates_passed(market_context, side)
    if not ml_ok:
        return False, ml_reason

    desired = v43_exec.get("desired_side")
    if side == "BUY":
        if not bool(v43_dec.get("final_long")):
            return False, "v43_final_long_false"
        if desired not in (None, "long"):
            return False, "v43_desired_side_mismatch"
        return True, "v43_long_gates_passed"
    if side == "SELL":
        if not bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False)):
            return False, "v43_short_not_enabled"
        if not bool(v43_dec.get("final_short")):
            return False, "v43_final_short_false"
        if desired not in (None, "short"):
            return False, "v43_desired_side_mismatch"
        return True, "v43_short_gates_passed"
    return False, "invalid_side"


def _consensus_supports_side(market_context: Dict[str, Any], side: str) -> Tuple[bool, str]:
    raw = market_context.get("consensus_signal")
    if raw is None:
        return False, "missing_consensus_signal"
    try:
        consensus = float(raw)
    except (TypeError, ValueError):
        return False, "invalid_consensus_signal"

    thr = float(getattr(settings, "reasoning_consensus_label_threshold", 0.5) or 0.5)
    if side == "BUY" and consensus > thr:
        return True, "consensus_bullish"
    if side == "SELL" and consensus < -thr:
        return True, "consensus_bearish"
    return False, f"consensus_not_aligned={consensus:.4f}"


def _policy_supports_entry(
    policy_verdict: Optional[Dict[str, Any]],
    signal: str,
) -> Tuple[bool, str]:
    if not isinstance(policy_verdict, dict):
        return False, "missing_policy_verdict"
    reasons = policy_verdict.get("reason_codes") or []
    reason_set = {str(r) for r in reasons}
    verdict_sig = str(policy_verdict.get("signal") or "").upper()
    trade_sig = str(signal or "").upper()
    if verdict_sig != trade_sig:
        return False, f"policy_signal_mismatch={verdict_sig}"
    if verdict_sig not in _BUY_SIGNALS | _SELL_SIGNALS:
        return False, "policy_signal_not_entry"
    if "agent_thesis_confirms_ml" in reason_set:
        return True, "policy_thesis_confirms_ml"
    if "agent_thesis_origin" in reason_set or "agent_thesis_entry" in reason_set:
        return True, "policy_thesis_entry"
    if not bool(policy_verdict.get("adopted_ml_candidate")):
        return False, "policy_did_not_adopt_ml_candidate"
    return True, "policy_adopted_ml_candidate"


def _strategy_ml_agreement_ok(
    market_context: Dict[str, Any],
    policy_verdict: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Validate thesis+ML agreement for ml_and_thesis production mode."""
    mode = str(getattr(settings, "agent_policy_mode", "ml_and_thesis") or "ml_and_thesis").lower()
    if not bool(getattr(settings, "require_strategy_ml_agreement", True)):
        return True, "strategy_ml_agreement_not_required"
    if mode != "ml_and_thesis":
        return True, "strategy_ml_agreement_mode_skip"

    reasons = set()
    if isinstance(policy_verdict, dict):
        reasons = {str(r) for r in (policy_verdict.get("reason_codes") or [])}
    if any(
        str(r).startswith("multi_horizon_") and "passed" not in str(r)
        for r in reasons
    ):
        return False, "strategy_ml_multi_horizon_reject"
    if "fusion_ml_and_thesis_no_agreement" in reasons:
        return False, "strategy_ml_no_agreement"
    if "agent_thesis_confirms_ml" not in reasons:
        return False, "missing_agent_thesis_confirms_ml"

    ts = market_context.get("trade_score")
    if isinstance(ts, dict) and not bool(ts.get("passed", True)):
        return False, "trade_score_not_passed"

    ml_val = market_context.get("ml_validation")
    policy_sig = ""
    if isinstance(policy_verdict, dict):
        policy_sig = str(policy_verdict.get("signal") or "").upper()
    if isinstance(ml_val, dict):
        if policy_sig in _BUY_SIGNALS and not bool(ml_val.get("final_long")):
            return False, "ml_validation_final_long_false"
        if policy_sig in _SELL_SIGNALS and not bool(ml_val.get("final_short")):
            return False, "ml_validation_final_short_false"
        if policy_sig in _BUY_SIGNALS | _SELL_SIGNALS:
            return True, "strategy_ml_agreement_ok"
        if not bool(ml_val.get("final_long") or ml_val.get("final_short")):
            return False, "ml_validation_gates_not_passed"
    return True, "strategy_ml_agreement_ok"


def validate_ml_entry_signal(
    *,
    signal: str,
    side: str,
    model_predictions: Any,
    market_context: Optional[Dict[str, Any]],
    ml_evidence_snapshot: Optional[Dict[str, Any]] = None,
    policy_verdict: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Return (ok, reason) — entry orders require a validated ML model signal."""
    if not bool(getattr(settings, "require_ml_signal_for_orders", True)):
        return True, "ml_guard_disabled"

    trade_side = str(side or "").upper()
    if trade_side not in ("BUY", "SELL"):
        trade_side = _side_from_trade_signal(signal) or ""
    if trade_side not in ("BUY", "SELL"):
        return False, "not_an_entry_signal"

    preds = _normalize_predictions(model_predictions)
    if not _has_healthy_model_predictions(preds):
        snap_preds = []
        if isinstance(ml_evidence_snapshot, dict):
            snap_preds = _normalize_predictions(ml_evidence_snapshot.get("model_predictions"))
        if not _has_healthy_model_predictions(snap_preds):
            return False, "no_healthy_model_predictions"
        preds = snap_preds

    mc = market_context if isinstance(market_context, dict) else {}
    policy_ok, policy_reason = _policy_supports_entry(policy_verdict, signal)
    if not policy_ok:
        return False, policy_reason

    if policy_reason in ("policy_thesis_entry", "policy_thesis_confirms_ml"):
        agree_ok, agree_reason = _strategy_ml_agreement_ok(mc, policy_verdict)
        if not agree_ok:
            return False, agree_reason
        return True, policy_reason

    agree_ok, agree_reason = _strategy_ml_agreement_ok(mc, policy_verdict)
    if not agree_ok and str(getattr(settings, "agent_policy_mode", "")).lower() == "ml_and_thesis":
        return False, agree_reason

    if isinstance(ml_evidence_snapshot, dict):
        ml_sig = str(ml_evidence_snapshot.get("ml_candidate_signal") or "").upper()
        if ml_sig in _BUY_SIGNALS | _SELL_SIGNALS and ml_sig != str(signal or "").upper():
            return False, "ml_evidence_signal_mismatch"

    v43_exec = mc.get("v43_execution_profile")
    use_v43 = isinstance(v43_exec, dict) and bool(v43_exec.get("enabled"))
    if use_v43 or bool(getattr(settings, "require_v43_gates_for_entry", True)):
        v43_ok, v43_reason = _v43_gates_passed(mc, trade_side)
        if v43_ok:
            return True, v43_reason
        if use_v43:
            return False, v43_reason

    if bool(getattr(settings, "require_ml_consensus_alignment", True)):
        cons_ok, cons_reason = _consensus_supports_side(mc, trade_side)
        if cons_ok:
            return True, cons_reason
        return False, cons_reason

    return True, "ml_predictions_present"
