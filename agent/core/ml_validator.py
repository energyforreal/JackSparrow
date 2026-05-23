"""ML validation helpers — v43 as probabilistic validator, not sole signal author."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent.core.config import settings
from agent.core.strategy_types import MLValidationSnapshot


_ENTRY_BUY = frozenset({"BUY", "STRONG_BUY"})
_ENTRY_SELL = frozenset({"SELL", "STRONG_SELL"})


def _signal_from_side(side: str, confidence: float) -> str:
    s = str(side or "").upper()
    if s in ("LONG", "BUY"):
        return "STRONG_BUY" if confidence >= 0.85 else "BUY"
    if s in ("SHORT", "SELL"):
        return "STRONG_SELL" if confidence >= 0.85 else "SELL"
    return "HOLD"


def build_ml_validation_from_prediction(
    pred_context: Dict[str, Any],
    *,
    pred_confidence: float = 0.0,
    pred_value: float = 0.0,
    eps: Optional[float] = None,
    short_enabled: Optional[bool] = None,
) -> MLValidationSnapshot:
    """Build MLValidationSnapshot from JackSparrow v43 prediction context."""
    proba = float(pred_context.get("expected_return", 0.0) or 0.0)
    thr = float(pred_context.get("threshold", 0.005) or 0.005)
    short_thr = float(pred_context.get("short_threshold", thr) or thr)
    regime = str(pred_context.get("regime", "neutral") or "neutral")
    u_scale = float(pred_context.get("unc_scale", 1.0) or 1.0)
    unc = float(pred_context.get("uncertainty", 0.0) or 0.0)

    if eps is None:
        eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)
    if short_enabled is None:
        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )

    raw_long = bool(proba > (thr - max(0.0, eps)))
    raw_short = bool(short_enabled and proba < -(short_thr - max(0.0, eps)))
    if raw_long and raw_short:
        raw_long = raw_short = False

    confirms_long = raw_long
    confirms_short = raw_short

    return MLValidationSnapshot(
        expected_return=proba,
        threshold=thr,
        short_threshold=short_thr,
        regime=regime,
        unc_scale=u_scale,
        uncertainty=unc,
        confirms_long=confirms_long,
        confirms_short=confirms_short,
        raw_long=raw_long,
        raw_short=raw_short,
        model_confidence=float(pred_confidence),
        model_prediction=float(pred_value),
    )


def ml_confirms_direction(
    snapshot: MLValidationSnapshot,
    side: str,
    eps: Optional[float] = None,
    *,
    require_gated: bool = False,
) -> bool:
    """Return True when ML validation agrees with trade side (long/short).

    When ``require_gated`` is True (entry/scoring paths), only post-gate
    ``final_long`` / ``final_short`` count — raw threshold passes are ignored.
    """
    if require_gated:
        s = str(side or "").upper()
        if s in ("LONG", "BUY"):
            return bool(snapshot.final_long)
        if s in ("SHORT", "SELL"):
            if not bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False)):
                return False
            return bool(snapshot.final_short)
        return False

    if eps is None:
        eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)
    s = str(side or "").upper()
    if s in ("LONG", "BUY"):
        return bool(
            snapshot.expected_return > (snapshot.threshold - max(0.0, eps))
            or snapshot.confirms_long
            or snapshot.final_long
        )
    if s in ("SHORT", "SELL"):
        if not bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False)):
            return False
        return bool(
            snapshot.expected_return < -(snapshot.short_threshold - max(0.0, eps))
            or snapshot.confirms_short
            or snapshot.final_short
        )
    return False


def ml_candidate_signal_from_validation(
    snapshot: MLValidationSnapshot,
    *,
    prefer_gated: bool = True,
) -> Tuple[str, float, float]:
    """Derive discrete ML candidate signal from validation snapshot."""
    if prefer_gated:
        if snapshot.final_long:
            return (
                _signal_from_side("LONG", snapshot.model_confidence),
                snapshot.model_confidence,
                0.05,
            )
        if snapshot.final_short:
            return (
                _signal_from_side("SHORT", snapshot.model_confidence),
                snapshot.model_confidence,
                0.05,
            )
        return "HOLD", snapshot.model_confidence, 0.0
    if snapshot.confirms_long:
        return _signal_from_side("LONG", snapshot.model_confidence), snapshot.model_confidence, 0.05
    if snapshot.confirms_short:
        return _signal_from_side("SHORT", snapshot.model_confidence), snapshot.model_confidence, 0.05
    return "HOLD", snapshot.model_confidence, 0.0


def apply_gates_to_ml_validation(
    snapshot: MLValidationSnapshot,
    *,
    final_long: bool,
    final_short: bool,
    gate_reject: Optional[str],
) -> MLValidationSnapshot:
    """Attach post-gate execution state to validation snapshot."""
    snapshot.final_long = final_long
    snapshot.final_short = final_short
    snapshot.gate_reject = gate_reject
    return snapshot


def thesis_verdict_to_strategy_candidate(verdict: Any) -> "StrategyCandidate":
    """Map ThesisVerdict to StrategyCandidate."""
    from agent.core.strategy_types import StrategyCandidate

    sig = str(getattr(verdict, "signal", "HOLD") or "HOLD").upper()
    if sig in _ENTRY_BUY:
        direction = "LONG"
    elif sig in _ENTRY_SELL:
        direction = "SHORT"
    else:
        direction = "FLAT"
    conf = float(getattr(verdict, "confidence", 0.0) or 0.0)
    h_bars = int(getattr(verdict, "intended_horizon_bars", 0) or 0)
    h_min = int(getattr(verdict, "horizon_minutes", 0) or 0)
    return StrategyCandidate(
        direction=direction,
        strength=conf,
        signal=sig,
        reason_codes=list(getattr(verdict, "reason_codes", []) or []),
        thesis_type=str(getattr(verdict, "thesis_type", "flat") or "flat"),
        confidence=conf,
        position_size=float(getattr(verdict, "position_size", 0.0) or 0.0),
        intended_horizon_bars=h_bars,
        horizon_minutes=h_min,
    )
