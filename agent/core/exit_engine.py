"""EV-based exit decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from agent.core.config import settings
from agent.core.position_intelligence import PositionQuality
from agent.core.trade_lifecycle_engine import (
    ExitTrigger,
    _bars_held,
    _f,
    _has_critical_invalidation,
    _resolve_exit_trigger_and_detail,
)
from agent.core.v43_signal_gates import round_trip_cost_pct


@dataclass
class ExitDecision:
    """Exit engine verdict."""

    should_exit: bool
    reason_detail: str = ""
    exit_trigger: ExitTrigger = ""
    exit_flags: Dict[str, bool] = None
    stay_ev: float = 0.0
    exit_ev: float = 0.0
    fee_aware_hold: bool = False

    def __post_init__(self) -> None:
        if self.exit_flags is None:
            self.exit_flags = {}


def _unrealized_pnl_pct(position: Dict[str, Any]) -> float:
    entry = _f(position.get("entry_price"))
    current = _f(position.get("current_price"), entry)
    if entry <= 0:
        return 0.0
    side = str(position.get("side") or "long").lower()
    if side in ("long", "buy"):
        return (current - entry) / entry
    return (entry - current) / entry


def compute_stay_ev(position: Dict[str, Any], quality: PositionQuality) -> float:
    """Expected value of holding (heuristic, price-return scale)."""
    pnl = _unrealized_pnl_pct(position)
    align = quality.continuation.alignment
    opp = quality.opportunity_score / 100.0
    return pnl * 0.5 + align * 0.3 + opp * 0.2


def compute_exit_ev(position: Dict[str, Any], quality: PositionQuality) -> float:
    """Expected value of exiting now (locked PnL minus fees)."""
    pnl = _unrealized_pnl_pct(position)
    rtc = round_trip_cost_pct()
    return pnl - rtc


def _min_hold_bars_met(position: Dict[str, Any]) -> bool:
    min_bars = int(getattr(settings, "trade_lifecycle_min_hold_bars", 2) or 2)
    if min_bars <= 0:
        return True
    return _bars_held(position) >= min_bars


def _health_exit_allowed(quality: PositionQuality) -> bool:
    if not bool(getattr(settings, "trade_lifecycle_health_exit_requires_critical", True)):
        return True
    return _has_critical_invalidation(quality.continuation) or not quality.thesis_valid


def decide_exit(
    position: Dict[str, Any],
    quality: PositionQuality,
) -> ExitDecision:
    """EV arbiter: exit vs hold using position quality and economics."""
    exit_max = float(getattr(settings, "trade_lifecycle_health_exit_max", 50.0) or 50.0)
    extend_min = float(
        getattr(settings, "trade_lifecycle_opportunity_extend_min", 80.0) or 80.0
    )
    reduce_opp = float(
        getattr(settings, "trade_lifecycle_opportunity_reduce_min", 40.0) or 40.0
    )
    health_low_hold_opp = float(
        getattr(settings, "trade_lifecycle_health_low_hold_opportunity_min", 60.0) or 60.0
    )
    ev_enabled = bool(getattr(settings, "trade_lifecycle_ev_exit_enabled", True))
    fee_hold = bool(getattr(settings, "trade_lifecycle_fee_aware_hold_enabled", True))
    min_delta = float(getattr(settings, "exit_engine_min_stay_ev_delta", 0.002) or 0.002)

    fsm_broken = "fsm_thesis_broken" in quality.continuation.invalidation_codes
    fsm_broken_exit = bool(getattr(settings, "trade_lifecycle_fsm_broken_exit", True))
    fsm_broken_flag = fsm_broken_exit and fsm_broken
    min_hold_ok = _min_hold_bars_met(position)

    stay_ev = compute_stay_ev(position, quality)
    exit_ev = compute_exit_ev(position, quality)
    pnl = _unrealized_pnl_pct(position)
    rtc = round_trip_cost_pct()

    if not ev_enabled:
        hard_exit = quality.opposite or fsm_broken_flag
        if not hard_exit and quality.health_score < exit_max:
            hard_exit = _health_exit_allowed(quality) and min_hold_ok
        if hard_exit:
            trigger, detail, flags = _resolve_exit_trigger_and_detail(
                opposite=quality.opposite,
                opp_reason=quality.opposite_reason,
                health=quality.health_score,
                exit_max=exit_max,
                fsm_broken=fsm_broken_flag,
            )
            return ExitDecision(
                should_exit=True,
                reason_detail=detail,
                exit_trigger=trigger,
                exit_flags=flags,
                stay_ev=stay_ev,
                exit_ev=exit_ev,
            )
        return ExitDecision(should_exit=False, stay_ev=stay_ev, exit_ev=exit_ev)

    if quality.opposite or fsm_broken_flag:
        trigger, detail, flags = _resolve_exit_trigger_and_detail(
            opposite=quality.opposite,
            opp_reason=quality.opposite_reason,
            health=quality.health_score,
            exit_max=exit_max,
            fsm_broken=fsm_broken_flag,
        )
        return ExitDecision(
            should_exit=True,
            reason_detail=detail,
            exit_trigger=trigger,
            exit_flags=flags,
            stay_ev=stay_ev,
            exit_ev=exit_ev,
        )

    if (
        fee_hold
        and pnl > 0
        and pnl < rtc
        and quality.opportunity_score >= extend_min
        and quality.continuation.would_enter_same_side_now
        and quality.thesis_valid
    ):
        return ExitDecision(
            should_exit=False,
            reason_detail="fee_aware_hold",
            stay_ev=stay_ev,
            exit_ev=exit_ev,
            fee_aware_hold=True,
        )

    if (
        fee_hold
        and quality.health_score < exit_max
        and quality.opportunity_score >= health_low_hold_opp
        and quality.thesis_valid
    ):
        return ExitDecision(
            should_exit=False,
            reason_detail="health_low_opportunity_moderate_hold",
            stay_ev=stay_ev,
            exit_ev=exit_ev,
            fee_aware_hold=True,
        )

    if (
        min_hold_ok
        and _health_exit_allowed(quality)
        and exit_ev > stay_ev + min_delta
        and not quality.continuation.would_enter_same_side_now
    ):
        return ExitDecision(
            should_exit=True,
            reason_detail="exit_ev_exceeds_stay",
            exit_trigger="health_threshold",
            exit_flags={"ev_arbiter": True},
            stay_ev=stay_ev,
            exit_ev=exit_ev,
        )

    if (
        min_hold_ok
        and _health_exit_allowed(quality)
        and quality.health_score < exit_max
        and quality.opportunity_score < reduce_opp
        and not quality.thesis_valid
    ):
        trigger, detail, flags = _resolve_exit_trigger_and_detail(
            opposite=False,
            opp_reason="",
            health=quality.health_score,
            exit_max=exit_max,
            fsm_broken=False,
        )
        return ExitDecision(
            should_exit=True,
            reason_detail=detail,
            exit_trigger=trigger,
            exit_flags=flags,
            stay_ev=stay_ev,
            exit_ev=exit_ev,
        )

    if quality.health_score < exit_max and quality.opportunity_score >= extend_min:
        return ExitDecision(
            should_exit=False,
            reason_detail="health_low_opportunity_high",
            stay_ev=stay_ev,
            exit_ev=exit_ev,
            fee_aware_hold=True,
        )

    return ExitDecision(should_exit=False, stay_ev=stay_ev, exit_ev=exit_ev)
