"""Market structure evolution tracking for open positions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def derive_structure_state(market_state: Dict[str, Any]) -> str:
    """Map market_state to a compact structure label."""
    trend = str(market_state.get("trend") or "neutral").lower()
    strength = str(market_state.get("trend_strength") or "weak").lower()
    momentum = str(market_state.get("momentum") or "flat").lower()

    if trend == "bullish":
        if strength == "strong":
            return "bullish"
        if momentum == "decreasing":
            return "weak_bullish"
        return "bullish" if strength == "moderate" else "weak_bullish"
    if trend == "bearish":
        if strength == "strong":
            return "bearish"
        if momentum == "decreasing":
            return "weak_bearish"
        return "bearish" if strength == "moderate" else "weak_bearish"
    return "neutral"


def structure_transition(prev: Optional[str], current: str) -> str:
    """Label transition between structure states."""
    if not prev or prev == current:
        return "stable"
    return f"{prev}_to_{current}"


def build_monitoring_record(
    *,
    verdict: Any,
    live_mc: Dict[str, Any],
    position: Dict[str, Any],
    prior_structure: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one position_monitoring cycle record."""
    rb = live_mc.get("rule_based_pipeline") if isinstance(live_mc.get("rule_based_pipeline"), dict) else {}
    ms = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    structure_state = derive_structure_state(ms)
    trans = structure_transition(prior_structure, structure_state)

    entry_price = float(position.get("entry_price") or position.get("avg_price") or 0.0)
    current_price = float(position.get("current_price") or entry_price)
    tp = position.get("take_profit")
    sl = position.get("stop_loss")
    side = str(position.get("side") or "long").lower()
    is_long = side in ("long", "buy")

    bars_to_tp: Optional[float] = None
    bars_to_sl: Optional[float] = None
    expected_reward: Optional[float] = None
    try:
        if tp is not None and entry_price > 0:
            tp_f = float(tp)
            dist = abs(tp_f - current_price) / entry_price
            atr_pct = float((live_mc.get("features") or {}).get("atr_pct", 0.005) or 0.005)
            bars_to_tp = dist / max(atr_pct, 1e-6)
            if is_long:
                expected_reward = (tp_f - current_price) / entry_price
            else:
                expected_reward = (current_price - tp_f) / entry_price
        if sl is not None and entry_price > 0:
            sl_f = float(sl)
            dist_sl = abs(current_price - sl_f) / entry_price
            atr_pct = float((live_mc.get("features") or {}).get("atr_pct", 0.005) or 0.005)
            bars_to_sl = dist_sl / max(atr_pct, 1e-6)
    except (TypeError, ValueError):
        pass

    feats = live_mc.get("features") if isinstance(live_mc.get("features"), dict) else {}
    support = feats.get("support_level") or feats.get("low")
    resistance = feats.get("resistance_level") or feats.get("high")

    continuation = getattr(verdict, "continuation", None)
    cont_dict = continuation.to_dict() if continuation is not None and hasattr(continuation, "to_dict") else None

    prior_strength = str(ms.get("trend_strength") or "weak")
    trend_evolution = "stable"
    if prior_structure:
        if structure_state in ("bullish", "weak_bullish") and prior_structure == "neutral":
            trend_evolution = "strengthening"
        elif structure_state == "neutral" and prior_structure in ("bullish", "bearish"):
            trend_evolution = "weakening"

    return {
        "bar_index": live_mc.get("bar_index"),
        "health_score": getattr(verdict, "health_score", None),
        "opportunity_score": getattr(verdict, "opportunity_score", None),
        "action_would_be": getattr(verdict, "action", "HOLD"),
        "continuation": cont_dict,
        "market_state": ms,
        "trend_strength": prior_strength,
        "trend_evolution": trend_evolution,
        "support_resistance": {
            "support": support,
            "resistance": resistance,
        },
        "breakout_validity": ms.get("breakout_status"),
        "bars_to_tp": bars_to_tp,
        "bars_to_sl": bars_to_sl,
        "expected_reward_if_held": expected_reward,
        "regime_benchmark": ms.get("regime_benchmark"),
        "structure_state": structure_state,
        "structure_transition": trans,
    }


def condense_structure_timeline(monitoring: List[Dict[str, Any]]) -> List[str]:
    """Condense monitoring cycles into structure transition sequence."""
    if not monitoring:
        return []
    timeline: List[str] = []
    prev: Optional[str] = None
    for rec in monitoring:
        state = str(rec.get("structure_state") or "neutral")
        if state != prev:
            timeline.append(state)
            prev = state
    return timeline
