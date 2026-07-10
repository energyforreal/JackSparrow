"""Decision-cycle telemetry helpers — v3 schema, terminal cause classification."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.core.config import settings
from agent.core.signal_vocabulary import ENTRY_SIGNALS, is_entry_signal


def frozen_policy_snapshot() -> Dict[str, Any]:
    """Frozen pi0 policy snapshot for calibration labels and telemetry."""
    from agent.core.v43_signal_gates import round_trip_cost_pct

    return {
        "horizon_bars": int(getattr(settings, "jacksparrow_v43_forward_target_bars", 2) or 2),
        "gate5_ratio": float(
            getattr(settings, "jacksparrow_v43_min_edge_cost_ratio", 0.75) or 0.75
        ),
        "entry_quality_min": float(
            getattr(settings, "entry_quality_min_score", 55.0) or 55.0
        ),
        "conviction_entry_floor": float(
            getattr(settings, "conviction_entry_floor", 0.35) or 0.35
        ),
        "hypothesis_min_margin": float(
            getattr(settings, "hypothesis_min_margin", 0.03) or 0.03
        ),
        "stop_loss_pct": float(getattr(settings, "stop_loss_percentage", 0.02) or 0.02),
        "take_profit_pct": float(
            getattr(settings, "jacksparrow_v43_take_profit_pct", 0.015) or 0.015
        ),
        "trade_lifecycle_enabled": bool(
            getattr(settings, "trade_lifecycle_enabled", False)
        ),
        "round_trip_cost": float(round_trip_cost_pct()),
        "policy_mode": str(getattr(settings, "agent_policy_mode", "ml_or_thesis") or "ml_or_thesis"),
    }


def classify_terminal_cause(
    *,
    policy_signal: str,
    gate_reject: Optional[str],
    final_long: bool,
    final_short: bool,
    raw_long: bool,
    raw_short: bool,
    entry_quality_passed: Optional[bool] = None,
    conviction_below_floor: Optional[bool] = None,
    handler_reject_reason: Optional[str] = None,
    executed: bool = False,
) -> str:
    """Single bucket for rejection attribution."""
    if executed:
        return "executed"
    if handler_reject_reason:
        reason = str(handler_reject_reason).lower()
        if "risk" in reason:
            return "risk"
        return "handler"
    sig = str(policy_signal or "HOLD").upper()
    if is_entry_signal(sig) and not executed:
        if conviction_below_floor:
            return "conviction"
        if entry_quality_passed is False:
            return "quality"
        return "policy"
    if not raw_long and not raw_short:
        return "g1"
    if gate_reject:
        gr = str(gate_reject).lower()
        if gr in ("min_edge_cost", "high_uncertainty"):
            return "g5"
        if gr in ("open_position", "debounce", "freq_hourly", "freq_daily"):
            return "g2"
        if gr in ("crisis_regime", "trending_blocked"):
            return "g4"
        if gr.startswith("below_threshold"):
            return "g1"
        return "g2"
    if not final_long and not final_short:
        return "g5"
    if sig == "HOLD" or not sig:
        return "policy"
    return "policy"


def build_gate_telemetry(
    *,
    raw_long: bool,
    raw_short: bool,
    final_long: bool,
    final_short: bool,
    gate_reject: Optional[str],
    g5_pass: Optional[bool] = None,
) -> Dict[str, Any]:
    """Per-gate pass flags for v3 telemetry."""
    g1 = bool(raw_long or raw_short)
    g5 = g5_pass
    if g5 is None:
        g5 = bool(final_long or final_short) if g1 else False
    g2_through = g1 and not gate_reject
    gr = str(gate_reject or "").lower()
    if gr in ("open_position", "debounce", "freq_hourly", "freq_daily"):
        g2_through = False
    g4_pass = g2_through and gr not in ("crisis_regime", "trending_blocked")
    return {
        "g1_raw_long": bool(raw_long),
        "g1_raw_short": bool(raw_short),
        "g2_pass": bool(g2_through),
        "g3_pass": bool(g2_through),
        "g4_pass": bool(g4_pass),
        "g5_pass": bool(g5),
        "gate_reject": gate_reject,
    }


def build_latent_telemetry(
    *,
    expected_return: float,
    threshold: float,
    model_confidence: float,
    thesis_confidence: float,
    trade_score: float,
    hypothesis_margin: Optional[float] = None,
    mtf_alignment: Optional[float] = None,
) -> Dict[str, float]:
    """Latent variable proxies for v3 telemetry."""
    epsilon_proxy = float(expected_return) - float(threshold)
    q_composite = max(0.0, min(1.0, float(trade_score) / 100.0))
    margin = float(hypothesis_margin or 0.0)
    align = float(mtf_alignment or 0.0)
    a_composite = max(0.0, min(1.0, 0.5 * margin + 0.5 * align)) if (margin or align) else margin
    return {
        "epsilon_proxy": epsilon_proxy,
        "kappa_ml": float(model_confidence),
        "kappa_thesis": float(thesis_confidence),
        "q_composite": q_composite,
        "A_composite": a_composite,
    }
