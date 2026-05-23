"""Deterministic post-trade reflection engine (advisory only).

Evaluates decision quality against realized outcomes without mutating policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

REFLECTION_VERSION = "1.0"

_ENTRY_LONG = frozenset({"BUY", "STRONG_BUY"})
_ENTRY_SHORT = frozenset({"SELL", "STRONG_SELL"})


@dataclass
class ReflectionSnapshot:
    """Advisory reflection block emitted on position close."""

    version: str = REFLECTION_VERSION
    timestamp: str = ""
    symbol: str = ""
    position_id: str = ""
    advisory_only: bool = True
    predicted_signal: str = ""
    exit_reason: str = ""
    pnl: float = 0.0
    was_profitable: bool = False
    direction_correct: Optional[bool] = None
    confidence_at_entry: Optional[float] = None
    calibration_bucket: str = "unknown"
    quality_score: float = 0.0
    diagnostics: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "position_id": self.position_id,
            "advisory_only": self.advisory_only,
            "predicted_signal": self.predicted_signal,
            "exit_reason": self.exit_reason,
            "pnl": self.pnl,
            "was_profitable": self.was_profitable,
            "direction_correct": self.direction_correct,
            "confidence_at_entry": self.confidence_at_entry,
            "calibration_bucket": self.calibration_bucket,
            "quality_score": self.quality_score,
            "diagnostics": list(self.diagnostics),
            "reason_codes": list(self.reason_codes),
        }


def _calibration_bucket(confidence: Optional[float], was_profitable: bool) -> str:
    if confidence is None:
        return "unknown"
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if c > 1.0:
        c = c / 100.0
    c = max(0.0, min(1.0, c))
    if c >= 0.75:
        tier = "high"
    elif c >= 0.50:
        tier = "medium"
    else:
        tier = "low"
    outcome = "win" if was_profitable else "loss"
    return f"{tier}_confidence_{outcome}"


def _direction_correct(predicted_signal: str, pnl: float) -> Optional[bool]:
    sig = str(predicted_signal or "").upper()
    if sig in _ENTRY_LONG:
        return pnl > 0
    if sig in _ENTRY_SHORT:
        return pnl > 0
    return None


def reflect_on_trade(
    *,
    symbol: str,
    position_id: str,
    predicted_signal: str,
    pnl: float,
    exit_reason: str,
    confidence_at_entry: Optional[float] = None,
    policy_reason_codes: Optional[List[str]] = None,
    introspection_at_entry: Optional[Dict[str, Any]] = None,
    advisory_only: bool = True,
) -> ReflectionSnapshot:
    """Score trade outcome vs entry intent deterministically."""
    now = datetime.now(timezone.utc).isoformat()
    profitable = float(pnl) > 0
    dir_ok = _direction_correct(predicted_signal, float(pnl))
    cal_bucket = _calibration_bucket(confidence_at_entry, profitable)

    diagnostics: List[str] = []
    reason_codes: List[str] = []

    if dir_ok is True:
        reason_codes.append("direction_aligned_with_pnl")
        diagnostics.append("Predicted direction matched profitable outcome.")
    elif dir_ok is False:
        reason_codes.append("direction_misaligned_with_pnl")
        diagnostics.append("Predicted direction did not align with PnL sign.")
    else:
        reason_codes.append("direction_not_applicable")
        diagnostics.append("Entry signal was HOLD or non-directional.")

    if profitable:
        reason_codes.append("outcome_profitable")
    else:
        reason_codes.append("outcome_unprofitable")

    intro = introspection_at_entry if isinstance(introspection_at_entry, dict) else {}
    if intro.get("v43_gate_reject"):
        reason_codes.append("entry_had_v43_gate_reject_flag")
        diagnostics.append(f"v43_gate_reject at entry: {intro.get('v43_gate_reject')}")

    trade_pass = intro.get("trade_score_pass")
    if trade_pass is False:
        reason_codes.append("entry_below_trade_score_min")
        diagnostics.append("Trade score was below minimum at entry introspection.")

    codes = policy_reason_codes or intro.get("policy_reason_codes") or []
    if isinstance(codes, list):
        hold_like = [c for c in codes if "hold" in str(c).lower() or "veto" in str(c).lower()]
        if hold_like and predicted_signal not in ("HOLD", ""):
            reason_codes.append("policy_hold_codes_with_entry_signal")
            diagnostics.append("Policy carried hold/veto codes while emitting entry signal.")

    quality = 0.5
    if dir_ok is True:
        quality += 0.35
    elif dir_ok is False:
        quality -= 0.35
    if profitable:
        quality += 0.10
    else:
        quality -= 0.10
    if confidence_at_entry is not None:
        try:
            conf = float(confidence_at_entry)
            if conf > 1.0:
                conf = conf / 100.0
            if profitable and conf >= 0.7:
                quality += 0.05
            if not profitable and conf >= 0.7:
                quality -= 0.10
                reason_codes.append("high_confidence_loss")
        except (TypeError, ValueError):
            pass
    quality = max(0.0, min(1.0, quality))

    return ReflectionSnapshot(
        version=REFLECTION_VERSION,
        timestamp=now,
        symbol=str(symbol or ""),
        position_id=str(position_id or ""),
        advisory_only=advisory_only,
        predicted_signal=str(predicted_signal or ""),
        exit_reason=str(exit_reason or "unknown"),
        pnl=float(pnl),
        was_profitable=profitable,
        direction_correct=dir_ok,
        confidence_at_entry=confidence_at_entry,
        calibration_bucket=cal_bucket,
        quality_score=quality,
        diagnostics=diagnostics,
        reason_codes=reason_codes,
    )
