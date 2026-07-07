"""
Trade Lifecycle Engine — symmetrical post-entry risk and opportunity management.

Evaluates open positions each candle using existing pipeline signals (no new ML).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from agent.core.config import settings
from agent.core.continuation_thesis import ContinuationResult, evaluate_continuation
from agent.core.dynamic_sl_tp import compute_sl_tp_levels
from agent.core.market_flip_detector import (
    compute_flip_tightened_levels,
    detect_market_flip_risk,
)
from agent.core.signal_vocabulary import is_long_signal, is_short_signal, normalize_signal

_CRITICAL_INVALIDATION_CODES = frozenset({
    "ema_death_cross",
    "ema_golden_cross",
    "fsm_thesis_broken",
    "narrative_exhaustion",
})

_SCENARIO_CRISIS_PHASES = frozenset({
    "markdown",
    "trend_exhaustion",
    "liquidity_grab",
})


def _bars_held(position: Dict[str, Any]) -> int:
    """Approximate decision cycles since entry from lifecycle monitoring records."""
    mon = position.get("lifecycle_monitoring")
    if isinstance(mon, list):
        return len(mon)
    return 0


def _has_critical_invalidation(continuation: ContinuationResult) -> bool:
    codes = set(continuation.invalidation_codes)
    return bool(codes & _CRITICAL_INVALIDATION_CODES)


def _scenario_health_adjustment(
    live_mc: Dict[str, Any],
    position_side: str,
) -> Tuple[float, List[str]]:
    """Penalties from cognition scenario phase shifts."""
    penalties: List[str] = []
    score_delta = 0.0
    dc = live_mc.get("decision_context_v3")
    if not isinstance(dc, dict):
        return 0.0, penalties
    scenario = dc.get("scenario")
    if not isinstance(scenario, dict):
        return 0.0, penalties
    revision = str(scenario.get("revision_reason") or "")
    primary = str(scenario.get("primary") or "").lower()
    if not revision.startswith("phase_shift_"):
        return 0.0, penalties

    penalties.append(revision)
    if "to_crisis" in revision or primary in _SCENARIO_CRISIS_PHASES:
        score_delta -= 25.0
        penalties.append("scenario_crisis_phase")
    elif "trending_to_ranging" in revision or "markup_to_range" in revision:
        if position_side == "long":
            score_delta -= 15.0
            penalties.append("scenario_trend_to_range_long")
    elif "trending_to_ranging" in revision or "markdown_to_range" in revision:
        if position_side == "short":
            score_delta -= 15.0
            penalties.append("scenario_trend_to_range_short")
    elif "to_range" in revision or primary == "range":
        score_delta -= 8.0

    return score_delta, penalties


LifecycleAction = Literal["HOLD", "TIGHTEN_SL", "MODIFY_TP", "EXIT"]
TpDirection = Literal["extend", "reduce"]
ExitTrigger = Literal[
    "",
    "opposite_signal",
    "ml_reversal",
    "health_threshold",
    "fsm_broken",
    "health_and_fsm",
    "hard_exit_unknown",
]


@dataclass
class LifecycleVerdict:
    """Post-entry lifecycle decision."""

    action: LifecycleAction
    health_score: float
    opportunity_score: float
    conviction_now: float
    conviction_at_entry: float
    conviction_delta: float
    invalidation_reasons: List[str] = field(default_factory=list)
    opportunity_reasons: List[str] = field(default_factory=list)
    tighten_stop_to: Optional[float] = None
    new_take_profit: Optional[float] = None
    tp_direction: Optional[TpDirection] = None
    tp_reason: str = ""
    exit_reason_detail: str = ""
    exit_trigger: ExitTrigger = ""
    exit_flags: Dict[str, bool] = field(default_factory=dict)
    health_breakdown: Dict[str, Any] = field(default_factory=dict)
    continuation: Optional[ContinuationResult] = None
    secondary_action: Optional[LifecycleAction] = None
    secondary_new_take_profit: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "action": self.action,
            "health_score": self.health_score,
            "opportunity_score": self.opportunity_score,
            "conviction_now": self.conviction_now,
            "conviction_at_entry": self.conviction_at_entry,
            "conviction_delta": self.conviction_delta,
            "invalidation_reasons": list(self.invalidation_reasons),
            "opportunity_reasons": list(self.opportunity_reasons),
            "exit_reason_detail": self.exit_reason_detail,
        }
        if self.exit_trigger:
            out["exit_trigger"] = self.exit_trigger
        if self.exit_flags:
            out["exit_flags"] = dict(self.exit_flags)
        if self.health_breakdown:
            out["health_breakdown"] = dict(self.health_breakdown)
        if self.tighten_stop_to is not None:
            out["tighten_stop_to"] = self.tighten_stop_to
        if self.new_take_profit is not None:
            out["new_take_profit"] = self.new_take_profit
        if self.tp_direction:
            out["tp_direction"] = self.tp_direction
        if self.tp_reason:
            out["tp_reason"] = self.tp_reason
        if self.continuation is not None:
            out["continuation"] = self.continuation.to_dict()
        if self.secondary_action:
            out["secondary_action"] = self.secondary_action
        return out


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _position_side(position: Dict[str, Any]) -> str:
    side = str(position.get("side") or "long").lower()
    return "long" if side in ("long", "buy") else "short"


def _conviction_from_context(live_mc: Dict[str, Any]) -> float:
    pv = live_mc.get("policy_verdict")
    if isinstance(pv, dict) and pv.get("conviction") is not None:
        return _f(pv.get("conviction"), 0.5)
    conv = live_mc.get("conviction")
    if conv is not None:
        return _f(conv, 0.5)
    return _f(live_mc.get("structural_confidence"), 0.5)


def _flip_score(live_mc: Dict[str, Any], position_side: str, symbol: str) -> float:
    feats = live_mc.get("features")
    if not isinstance(feats, dict):
        return 0.0
    snap = detect_market_flip_risk(
        feats,
        position_side,
        str(symbol or "UNKNOWN"),
        settings=settings,
    )
    return float(snap.score)


def _opposite_signal_inputs(live_mc: Dict[str, Any], position_side: str) -> Tuple[bool, str]:
    """Signal-reversal and ML-reversal inputs folded into TLE."""
    reasons: List[str] = []
    signal = normalize_signal(
        live_mc.get("signal")
        or (live_mc.get("policy_verdict") or {}).get("signal")
    )
    if position_side == "long" and is_short_signal(signal):
        return True, "opposite_entry_signal"
    if position_side == "short" and is_long_signal(signal):
        return True, "opposite_entry_signal"

    ml_val = live_mc.get("ml_validation")
    if not isinstance(ml_val, dict):
        mc = live_mc
        ml_val = mc.get("ml_validation") if isinstance(mc.get("ml_validation"), dict) else {}

    min_conf = float(getattr(settings, "position_exit_ml_confidence_min", 0.70) or 0.70)
    ml_conf = _f(
        ml_val.get("model_confidence")
        or live_mc.get("consensus_confidence")
    )
    if ml_conf > 1.0:
        ml_conf = ml_conf / 100.0

    final_short = bool(ml_val.get("final_short"))
    final_long = bool(ml_val.get("final_long"))
    short_enabled = bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False))

    if ml_conf >= min_conf:
        if position_side == "long" and final_short:
            return True, "ml_reversal_short"
        if position_side == "short" and final_long and short_enabled:
            return True, "ml_reversal_long"

    return False, ""


def _compute_health_score(
    continuation: ContinuationResult,
    conviction_delta: float,
    flip_score: float,
    live_mc: Dict[str, Any],
    opposite: bool,
    *,
    position_side: str = "long",
) -> Tuple[float, List[str], Dict[str, Any]]:
    """0-100 risk score (higher = healthier) with component breakdown."""
    alignment_base = 100.0 * continuation.alignment
    score = alignment_base
    reasons: List[str] = list(continuation.invalidation_codes)
    penalties: Dict[str, float] = {}

    exit_delta = float(
        getattr(settings, "trade_lifecycle_conviction_exit_delta", -0.25) or -0.25
    )
    soften_align = float(
        getattr(settings, "trade_lifecycle_conviction_penalty_soften_alignment", 0.70)
        or 0.70
    )
    if conviction_delta <= exit_delta:
        reasons.append(f"conviction_drop:{conviction_delta:.3f}")
        conv_penalty = -25.0
        if continuation.alignment >= soften_align:
            conv_penalty = -12.0
            penalties["conviction_drop_softened"] = conv_penalty
        else:
            penalties["conviction_drop"] = conv_penalty
        score += conv_penalty

    flip_exit = float(getattr(settings, "trade_lifecycle_flip_exit_score", 0.70) or 0.70)
    if flip_score >= flip_exit:
        reasons.append(f"flip_risk:{flip_score:.3f}")
        penalties["flip_risk"] = -20.0
        score -= 20.0
    elif flip_score >= flip_exit * 0.75:
        penalties["flip_risk_elevated"] = -10.0
        score -= 10.0

    scenario_delta, scenario_reasons = _scenario_health_adjustment(live_mc, position_side)
    if scenario_delta != 0.0:
        reasons.extend(scenario_reasons)
        penalties["scenario_phase_shift"] = scenario_delta
        score += scenario_delta

    fsm = (live_mc.get("rule_based_pipeline") or {}).get("fsm_decision")
    if isinstance(fsm, dict):
        if fsm.get("exit_signal"):
            reasons.append("fsm_exit_signal")
            penalties["fsm_exit_signal"] = -15.0
            score -= 15.0
        health = str(fsm.get("thesis_health") or "").lower()
        if health == "broken":
            penalties["fsm_thesis_broken"] = -20.0
            score -= 20.0
        elif health == "weakening":
            penalties["fsm_thesis_weakening"] = -10.0
            score -= 10.0

    if opposite:
        reasons.append("opposite_or_ml_reversal")
        penalties["opposite_or_ml_reversal"] = -30.0
        score -= 30.0

    final = max(0.0, min(100.0, score))
    breakdown: Dict[str, Any] = {
        "alignment_base": round(alignment_base, 2),
        "penalties": {k: round(v, 2) for k, v in penalties.items()},
        "final": round(final, 2),
        "invalidation_codes": list(continuation.invalidation_codes),
    }
    return final, reasons, breakdown


def _resolve_exit_trigger_and_detail(
    *,
    opposite: bool,
    opp_reason: str,
    health: float,
    exit_max: float,
    fsm_broken: bool,
) -> Tuple[ExitTrigger, str, Dict[str, bool]]:
    """Map hard-exit inputs to structured trigger, detail string, and flags."""
    health_below = health < exit_max
    flags: Dict[str, bool] = {
        "opposite": opposite,
        "health_below_exit_max": health_below,
        "fsm_thesis_broken": fsm_broken,
        "ml_reversal": opposite and opp_reason.startswith("ml_reversal"),
    }

    if opposite:
        if opp_reason.startswith("ml_reversal"):
            return "ml_reversal", opp_reason, flags
        return "opposite_signal", opp_reason or "opposite_entry_signal", flags
    if health_below and fsm_broken:
        return "health_and_fsm", "health_and_fsm_thesis_broken", flags
    if fsm_broken:
        return "fsm_broken", "fsm_thesis_broken", flags
    if health_below:
        return "health_threshold", "health_below_exit_threshold", flags
    return "hard_exit_unknown", "hard_exit_unknown", flags


def _compute_opportunity_score(
    continuation: ContinuationResult,
    conviction_delta: float,
    live_mc: Dict[str, Any],
) -> Tuple[float, List[str]]:
    """0-100 reward score (higher = more opportunity to extend)."""
    score = 50.0
    reasons: List[str] = list(continuation.improvement_codes)

    extend_delta = float(
        getattr(settings, "trade_lifecycle_conviction_extend_delta", 0.10) or 0.10
    )
    if conviction_delta >= extend_delta:
        reasons.append(f"conviction_rise:{conviction_delta:.3f}")
        score += 20.0

    if continuation.would_enter_same_side_now:
        score += 15.0
        reasons.append("would_enter_same_side")

    regime = str(live_mc.get("regime") or live_mc.get("v43_regime") or "").lower()
    if regime == "trending":
        score += 10.0
        reasons.append("regime_trending")

    fsm = (live_mc.get("rule_based_pipeline") or {}).get("fsm_decision")
    if isinstance(fsm, dict) and str(fsm.get("thesis_health") or "") == "healthy":
        score += 8.0

    material = live_mc.get("market_intel_material_change")
    if isinstance(material, dict):
        for r in material.get("reasons") or []:
            rs = str(r).lower()
            if "confidence_delta" in rs or "trend:" in rs:
                reasons.append(f"intel:{r}")
                score += 5.0

    return max(0.0, min(100.0, score)), reasons


def _propose_tighten_stop(
    position: Dict[str, Any],
    flip_score: float,
    live_mc: Dict[str, Any],
) -> Optional[float]:
    entry = _f(position.get("entry_price"))
    current = _f(position.get("current_price"), entry)
    if entry <= 0 or current <= 0:
        return None
    side = _position_side(position)
    current_sl = position.get("stop_loss")
    try:
        current_sl_f = float(current_sl) if current_sl is not None else None
    except (TypeError, ValueError):
        current_sl_f = None

    be_pct = float(getattr(settings, "trade_lifecycle_breakeven_profit_pct", 0.0) or 0.0)
    if be_pct > 0:
        if side == "long" and current > entry:
            profit_pct = (current - entry) / entry
            if profit_pct >= be_pct:
                from agent.core.v43_signal_gates import round_trip_cost_pct

                rtc = round_trip_cost_pct()
                be_stop = entry * (1.0 + rtc)
                if current_sl_f is None or be_stop > current_sl_f:
                    return be_stop
        elif side == "short" and current < entry:
            profit_pct = (entry - current) / entry
            if profit_pct >= be_pct:
                from agent.core.v43_signal_gates import round_trip_cost_pct

                rtc = round_trip_cost_pct()
                be_stop = entry * (1.0 - rtc)
                if current_sl_f is None or be_stop < current_sl_f:
                    return be_stop

    feats = live_mc.get("features")
    if isinstance(feats, dict) and flip_score > 0:
        sym = str(position.get("symbol") or "UNKNOWN")
        snap = detect_market_flip_risk(feats, side, sym, settings=settings)
        if snap.score >= float(getattr(settings, "flip_score_threshold_low", 0.55) or 0.55):
            new_sl, _ = compute_flip_tightened_levels(
                entry,
                current,
                current_sl_f,
                position.get("take_profit"),
                side,
                snap.score,
                settings=settings,
            )
            if new_sl is not None:
                return new_sl

    lock_frac = float(getattr(settings, "trade_lifecycle_tighten_lock_fraction", 0.5) or 0.5)
    if side == "long" and current > entry:
        candidate = entry + (current - entry) * lock_frac
        if current_sl_f is None or candidate > current_sl_f:
            return candidate
    elif side == "short" and current < entry:
        candidate = entry - (entry - current) * lock_frac
        if current_sl_f is None or candidate < current_sl_f:
            return candidate
    return None


def _propose_tp_modify(
    position: Dict[str, Any],
    live_mc: Dict[str, Any],
    direction: TpDirection,
    flip_score: float,
) -> Optional[float]:
    entry = _f(position.get("entry_price"))
    current = _f(position.get("current_price"), entry)
    current_tp = position.get("take_profit")
    try:
        current_tp_f = float(current_tp) if current_tp is not None else None
    except (TypeError, ValueError):
        current_tp_f = None
    if entry <= 0 or current <= 0 or current_tp_f is None:
        return None

    side = _position_side(position)
    is_long = side == "long"

    if direction == "reduce" and flip_score > 0:
        current_sl = position.get("stop_loss")
        try:
            sl_f = float(current_sl) if current_sl is not None else None
        except (TypeError, ValueError):
            sl_f = None
        new_sl, new_tp = compute_flip_tightened_levels(
            entry,
            current,
            sl_f,
            current_tp_f,
            side,
            flip_score,
            settings=settings,
        )
        if new_tp is not None:
            if is_long and current < new_tp < current_tp_f:
                return new_tp
            if not is_long and current > new_tp > current_tp_f:
                return new_tp
        return None

    if direction == "extend" and bool(
        getattr(settings, "trade_lifecycle_tp_recompute_use_live_atr", True)
    ):
        feats = live_mc.get("features") if isinstance(live_mc.get("features"), dict) else {}
        atr = feats.get("atr_14")
        regime = live_mc.get("regime") or live_mc.get("v43_regime")
        tick = position.get("tick_size")
        try:
            tick_sz = float(tick) if tick is not None else None
        except (TypeError, ValueError):
            tick_sz = None
        sl_side = "BUY" if is_long else "SELL"
        levels = compute_sl_tp_levels(
            entry,
            sl_side,
            float(atr) if atr is not None else None,
            str(regime) if regime else None,
            settings,
            tick_size=tick_sz,
        )
        proposed = levels.take_profit
        if proposed is None:
            return None
        if is_long and proposed > current_tp_f:
            return proposed
        if not is_long and proposed < current_tp_f:
            return proposed
    return None


def _tp_change_allowed(position: Dict[str, Any], new_tp: float) -> bool:
    last_raw = position.get("last_tp_modify_at")
    if last_raw:
        try:
            if isinstance(last_raw, str):
                last_ts = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            else:
                last_ts = last_raw
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_ts).total_seconds()
            min_iv = int(
                getattr(settings, "trade_lifecycle_tp_modify_min_interval_seconds", 60) or 60
            )
            if age < min_iv:
                return False
        except (TypeError, ValueError):
            pass

    current_tp = position.get("take_profit")
    try:
        old = float(current_tp) if current_tp is not None else None
    except (TypeError, ValueError):
        old = None
    if old is None or old <= 0:
        return True
    min_chg = float(
        getattr(settings, "trade_lifecycle_tp_modify_min_change_pct", 0.002) or 0.002
    )
    if abs(new_tp - old) / old < min_chg:
        return False
    return True


def evaluate_lifecycle(
    position: Dict[str, Any],
    entry_snapshot: Dict[str, Any],
    live_mc: Dict[str, Any],
) -> LifecycleVerdict:
    """
    Evaluate post-entry lifecycle verdict from position state and live intelligence.

    Args:
        position: Open position from PositionManager.
        entry_snapshot: entry_decision_snapshot dict (or reconstructed).
        live_mc: market_context from DecisionReady reasoning chain.

    Returns:
        LifecycleVerdict with action and optional level adjustments.
    """
    symbol = str(position.get("symbol") or live_mc.get("symbol") or "")
    pos_side = _position_side(position)

    from agent.core.exit_engine import decide_exit
    from agent.core.position_intelligence import evaluate_position_quality

    position_quality = evaluate_position_quality(position, entry_snapshot, live_mc)
    health = position_quality.health_score
    opportunity = position_quality.opportunity_score
    conviction_now = position_quality.conviction_now
    conviction_at_entry = position_quality.conviction_at_entry
    conviction_delta = position_quality.conviction_delta
    continuation = position_quality.continuation
    opposite = position_quality.opposite
    opp_reason = position_quality.opposite_reason
    inv_reasons = list(position_quality.invalidation_reasons)
    opp_reasons = list(position_quality.opportunity_reasons)
    health_breakdown = position_quality.health_breakdown
    flip_score = position_quality.flip_score

    from agent.core.position_forecast_adapter import evaluate_forecast_adjustment

    forecast_adj = evaluate_forecast_adjustment(position, entry_snapshot, live_mc)
    if forecast_adj.reason_codes:
        opp_reasons.extend(forecast_adj.reason_codes)
    if forecast_adj.hint == "extend_tp" and opportunity < 85.0:
        opportunity = min(100.0, opportunity + 10.0)
        opp_reasons.append("forecast_extend_boost")
    elif forecast_adj.hint == "reduce_tp":
        opportunity = max(0.0, opportunity - 8.0)
        opp_reasons.append("forecast_reduce_penalty")
    elif forecast_adj.hint == "tighten":
        health = max(0.0, health - 5.0)
        inv_reasons.append("forecast_tighten_hint")
    elif forecast_adj.hint == "exit_candidate" and forecast_adj.expectation_confidence >= 0.6:
        health = max(0.0, health - 12.0)
        inv_reasons.append("forecast_exit_candidate")

    position_quality.health_score = health
    position_quality.opportunity_score = opportunity
    position_quality.invalidation_reasons = inv_reasons
    position_quality.opportunity_reasons = opp_reasons

    try:
        from agent.intelligence.evidence_graph_diff import graph_diff_from_snapshots

        gdiff = graph_diff_from_snapshots(entry_snapshot, live_mc)
        for code in gdiff.get("invalidation_codes") or []:
            if code not in inv_reasons:
                inv_reasons.append(code)
        g_align = float(gdiff.get("alignment") or 1.0)
        if g_align < 0.5:
            health = max(0.0, health - 10.0)
            inv_reasons.append("evidence_graph_low_alignment")
        position_quality.health_score = health
        position_quality.invalidation_reasons = inv_reasons
    except Exception:
        pass

    try:
        from agent.core.position_scale import evaluate_scale_out

        position["last_scale_out_hint"] = evaluate_scale_out(
            position,
            health_score=health,
            opportunity_score=opportunity,
        ).to_dict()
    except Exception:
        pass

    trade_score_raw = live_mc.get("trade_score")
    if isinstance(trade_score_raw, dict):
        try:
            ts_val = float(
                trade_score_raw.get("total_score")
                or trade_score_raw.get("quality_score")
                or 0
            )
            if ts_val > 0 and ts_val < 40.0 and health > 45.0:
                health = max(0.0, health - 5.0)
                inv_reasons.append("trade_score_entry_penalty_while_open")
                position_quality.health_score = health
                position_quality.invalidation_reasons = inv_reasons
        except (TypeError, ValueError):
            pass

    hold_min = float(getattr(settings, "trade_lifecycle_health_hold_min", 70.0) or 70.0)
    tighten_min = float(getattr(settings, "trade_lifecycle_health_tighten_min", 50.0) or 50.0)
    exit_max = float(getattr(settings, "trade_lifecycle_health_exit_max", 50.0) or 50.0)
    extend_min = float(
        getattr(settings, "trade_lifecycle_opportunity_extend_min", 80.0) or 80.0
    )
    reduce_opp = float(
        getattr(settings, "trade_lifecycle_opportunity_reduce_min", 40.0) or 40.0
    )

    exit_decision = decide_exit(position, position_quality)
    if exit_decision.should_exit:
        exit_trigger = exit_decision.exit_trigger or "health_threshold"
        detail = exit_decision.reason_detail or "health_below_exit_threshold"
        return LifecycleVerdict(
            action="EXIT",
            health_score=health,
            opportunity_score=opportunity,
            conviction_now=conviction_now,
            conviction_at_entry=conviction_at_entry,
            conviction_delta=conviction_delta,
            invalidation_reasons=inv_reasons,
            opportunity_reasons=opp_reasons,
            exit_reason_detail=detail,
            exit_trigger=exit_trigger,
            exit_flags=dict(exit_decision.exit_flags or {}),
            health_breakdown=health_breakdown,
            continuation=continuation,
        )

    tighten_stop = None
    new_tp = None
    tp_dir: Optional[TpDirection] = None
    tp_reason = ""
    secondary_action: Optional[LifecycleAction] = None
    secondary_tp: Optional[float] = None

    if health < hold_min or flip_score >= float(
        getattr(settings, "trade_lifecycle_flip_exit_score", 0.70) or 0.70
    ) * 0.75:
        tighten_stop = _propose_tighten_stop(position, flip_score, live_mc)
        if health < hold_min and health >= tighten_min and opportunity < reduce_opp:
            candidate = _propose_tp_modify(position, live_mc, "reduce", flip_score)
            if candidate is not None and _tp_change_allowed(position, candidate):
                new_tp = candidate
                tp_dir = "reduce"
                tp_reason = "health_weakening_lock_profit"

    if (
        opportunity >= extend_min
        and conviction_delta >= float(
            getattr(settings, "trade_lifecycle_conviction_extend_delta", 0.10) or 0.10
        )
        and continuation.would_enter_same_side_now
        and health >= hold_min
    ):
        candidate = _propose_tp_modify(position, live_mc, "extend", flip_score)
        if candidate is not None and _tp_change_allowed(position, candidate):
            if tighten_stop is not None:
                secondary_action = "MODIFY_TP"
                secondary_tp = candidate
            else:
                new_tp = candidate
                tp_dir = "extend"
                tp_reason = "opportunity_extend"

    if tighten_stop is not None:
        return LifecycleVerdict(
            action="TIGHTEN_SL",
            health_score=health,
            opportunity_score=opportunity,
            conviction_now=conviction_now,
            conviction_at_entry=conviction_at_entry,
            conviction_delta=conviction_delta,
            invalidation_reasons=inv_reasons,
            opportunity_reasons=opp_reasons,
            health_breakdown=health_breakdown,
            tighten_stop_to=tighten_stop,
            new_take_profit=new_tp,
            tp_direction=tp_dir,
            tp_reason=tp_reason,
            continuation=continuation,
            secondary_action=secondary_action,
            secondary_new_take_profit=secondary_tp,
        )

    if new_tp is not None and tp_dir:
        return LifecycleVerdict(
            action="MODIFY_TP",
            health_score=health,
            opportunity_score=opportunity,
            conviction_now=conviction_now,
            conviction_at_entry=conviction_at_entry,
            conviction_delta=conviction_delta,
            invalidation_reasons=inv_reasons,
            opportunity_reasons=opp_reasons,
            health_breakdown=health_breakdown,
            new_take_profit=new_tp,
            tp_direction=tp_dir,
            tp_reason=tp_reason,
            continuation=continuation,
        )

    return LifecycleVerdict(
        action="HOLD",
        health_score=health,
        opportunity_score=opportunity,
        conviction_now=conviction_now,
        conviction_at_entry=conviction_at_entry,
        conviction_delta=conviction_delta,
        invalidation_reasons=inv_reasons,
        opportunity_reasons=opp_reasons,
        health_breakdown=health_breakdown,
        continuation=continuation,
    )
