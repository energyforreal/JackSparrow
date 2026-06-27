"""Policy-first entry validation before exchange orders (IC / v43 runtime)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.core.config import settings
from agent.core.signal_vocabulary import (
    ENTRY_SIGNALS,
    is_entry_signal,
    is_long_signal,
    is_short_signal,
    normalize_signal,
    parse_entry_side,
    signal_to_position_side,
)

logger = structlog.get_logger()

_BUY_SIGNALS = frozenset({"LONG", "STRONG_LONG", "BUY", "STRONG_BUY"})
_SELL_SIGNALS = frozenset({"SHORT", "STRONG_SHORT", "SELL", "STRONG_SELL"})
_POLICY_ENTRY_REASONS = frozenset(
    {
        "agent_thesis_confirms_ml",
        "fusion_ml_gated_thesis_neutral",
        "agent_thesis_origin",
        "agent_thesis_entry",
        "policy_thesis_confirms_ml",
        "policy_ml_gated_thesis_neutral",
        "policy_thesis_entry",
        "policy_adopted_ml_candidate",
    }
)


def _ic_validation_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "require_ic_validation_for_orders",
            getattr(settings, "require_ml_signal_for_orders", True),
        )
    )


def _side_from_trade_signal(signal: str) -> Optional[str]:
    return signal_to_position_side(signal)


def _normalize_predictions(model_predictions: Any) -> List[Dict[str, Any]]:
    if not isinstance(model_predictions, list):
        return []
    return [p for p in model_predictions if isinstance(p, dict)]


def _has_healthy_predictions(model_predictions: List[Dict[str, Any]]) -> bool:
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


def _policy_supports_entry(
    policy_verdict: Optional[Dict[str, Any]],
    signal: str,
) -> Tuple[bool, str]:
    if not isinstance(policy_verdict, dict):
        return False, "missing_policy_verdict"
    reasons = {str(r) for r in (policy_verdict.get("reason_codes") or [])}
    verdict_sig = normalize_signal(policy_verdict.get("signal") or "")
    trade_sig = normalize_signal(signal)
    if verdict_sig != trade_sig:
        return False, f"policy_signal_mismatch={verdict_sig}"
    if not is_entry_signal(verdict_sig):
        return False, "policy_signal_not_entry"
    if reasons & _POLICY_ENTRY_REASONS:
        matched = sorted(reasons & _POLICY_ENTRY_REASONS)[0]
        return True, matched
    if bool(policy_verdict.get("adopted_ml_candidate")):
        return True, "policy_adopted_ml_candidate"
    return False, "policy_entry_not_authorized"


def _v43_gates_passed(market_context: Dict[str, Any], side: str) -> Tuple[bool, str]:
    ml_val = market_context.get("ml_validation")
    if not isinstance(ml_val, dict):
        return False, "ic_validation_missing"
    if side == "long":
        if not bool(ml_val.get("final_long")):
            return False, "ic_validation_final_long_false"
        return True, "ic_validation_long_gates_passed"
    if side == "short":
        if not bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False)):
            return False, "ic_validation_short_not_enabled"
        if not bool(ml_val.get("final_short")):
            return False, "ic_validation_final_short_false"
        return True, "ic_validation_short_gates_passed"
    return False, "ic_validation_invalid_side"


def validate_entry_signal(
    *,
    signal: str,
    side: str,
    model_predictions: Any,
    market_context: Optional[Dict[str, Any]],
    ml_evidence_snapshot: Optional[Dict[str, Any]] = None,
    policy_verdict: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Return (ok, reason) — policy-first entry validation for IC runtime."""
    if not _ic_validation_enabled():
        return True, "ic_validation_guard_disabled"

    trade_side = parse_entry_side(side) or signal_to_position_side(signal) or ""
    if trade_side not in ("long", "short"):
        return False, "not_an_entry_signal"

    preds = _normalize_predictions(model_predictions)
    if not _has_healthy_predictions(preds):
        snap_preds = []
        if isinstance(ml_evidence_snapshot, dict):
            snap_preds = _normalize_predictions(ml_evidence_snapshot.get("model_predictions"))
        if not _has_healthy_predictions(snap_preds):
            return False, "no_healthy_ic_predictions"
        preds = snap_preds

    policy_ok, policy_reason = _policy_supports_entry(policy_verdict, signal)
    if not policy_ok:
        logger.info(
            "ic_validation_rejected",
            reason=policy_reason,
            signal=signal,
            side=trade_side,
        )
        return False, policy_reason

    mc = market_context if isinstance(market_context, dict) else {}
    if bool(getattr(settings, "require_v43_gates_for_entry", True)):
        gate_ok, gate_reason = _v43_gates_passed(mc, trade_side)
        if not gate_ok:
            logger.info(
                "ic_validation_rejected",
                reason=gate_reason,
                signal=signal,
                side=trade_side,
            )
            return False, gate_reason
        return True, gate_reason

    return True, policy_reason


def validate_ml_entry_signal(
    *,
    signal: str,
    side: str,
    model_predictions: Any,
    market_context: Optional[Dict[str, Any]],
    ml_evidence_snapshot: Optional[Dict[str, Any]] = None,
    policy_verdict: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Deprecated alias — use validate_entry_signal."""
    return validate_entry_signal(
        signal=signal,
        side=side,
        model_predictions=model_predictions,
        market_context=market_context,
        ml_evidence_snapshot=ml_evidence_snapshot,
        policy_verdict=policy_verdict,
    )
