"""
Continuation thesis evaluation for open positions.

Compares entry-time snapshot against live market context without using the
entry-path ``thesis_open_position`` short-circuit in AgentThesisEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.persistence.trade_snapshot import reconstruct_market_context_from_snapshot


@dataclass
class ContinuationResult:
    """Whether the original entry thesis still holds."""

    alignment: float  # 0.0–1.0
    would_enter_same_side_now: bool
    invalidation_codes: List[str] = field(default_factory=list)
    improvement_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alignment": self.alignment,
            "would_enter_same_side_now": self.would_enter_same_side_now,
            "invalidation_codes": list(self.invalidation_codes),
            "improvement_codes": list(self.improvement_codes),
        }


def _f(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _position_side(position: Dict[str, Any]) -> str:
    side = str(position.get("side") or "long").lower()
    if side in ("buy", "long"):
        return "long"
    return "short"


def _entry_features(entry_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    dc = entry_snapshot.get("decision_context")
    if isinstance(dc, dict):
        feats = dc.get("features")
        if isinstance(feats, dict):
            return feats
    mc = reconstruct_market_context_from_snapshot(entry_snapshot)
    feats = mc.get("features")
    return feats if isinstance(feats, dict) else {}


def _live_features(live_mc: Dict[str, Any]) -> Dict[str, Any]:
    feats = live_mc.get("features")
    return feats if isinstance(feats, dict) else {}


def _gate_categories(entry_snapshot: Dict[str, Any]) -> Dict[str, bool]:
    dc = entry_snapshot.get("decision_context")
    if not isinstance(dc, dict):
        return {}
    ge = dc.get("gate_evaluation")
    if isinstance(ge, dict) and isinstance(ge.get("categories"), dict):
        return {str(k): bool(v) for k, v in ge["categories"].items()}
    rb = dc.get("rule_based_pipeline")
    if isinstance(rb, dict):
        sg = rb.get("structural_gates")
        if isinstance(sg, dict) and isinstance(sg.get("categories"), dict):
            return {str(k): bool(v) for k, v in sg["categories"].items()}
    return {}


def _live_gate_categories(live_mc: Dict[str, Any]) -> Dict[str, bool]:
    rb = live_mc.get("rule_based_pipeline")
    if isinstance(rb, dict):
        sg = rb.get("structural_gates")
        if isinstance(sg, dict) and isinstance(sg.get("categories"), dict):
            return {str(k): bool(v) for k, v in sg["categories"].items()}
    return {}


def evaluate_continuation(
    position: Dict[str, Any],
    entry_snapshot: Dict[str, Any],
    live_mc: Dict[str, Any],
) -> ContinuationResult:
    """
    Compare entry snapshot to live context for position continuation.

    Args:
        position: Open position dict (side, entry_price, ...).
        entry_snapshot: Frozen entry_decision_snapshot from position.
        live_mc: Current market_context from DecisionReady reasoning chain.

    Returns:
        ContinuationResult with alignment score and invalidation codes.
    """
    pos_side = _position_side(position)
    entry_feats = _entry_features(entry_snapshot)
    live_feats = _live_features(live_mc)
    invalidations: List[str] = []
    improvements: List[str] = []
    alignment = 1.0

    entry_regime = str(
        (entry_snapshot.get("decision_context") or {}).get("signal") or ""
    ).lower()
    live_regime = str(live_mc.get("regime") or live_mc.get("v43_regime") or "").lower()
    entry_rb = (entry_snapshot.get("decision_context") or {}).get("rule_based_pipeline")
    if isinstance(entry_rb, dict):
        ms = entry_rb.get("market_state")
        if isinstance(ms, dict) and ms.get("regime"):
            entry_regime = str(ms.get("regime") or entry_regime).lower()

    if live_regime and entry_regime and live_regime != entry_regime:
        if live_regime in ("crisis", "ranging") and entry_regime == "trending":
            invalidations.append(f"regime_flip:{entry_regime}->{live_regime}")
            alignment -= 0.25

    entry_cats = _gate_categories(entry_snapshot)
    live_cats = _live_gate_categories(live_mc)
    for cat, was_ok in entry_cats.items():
        if was_ok and cat in live_cats and not live_cats[cat]:
            invalidations.append(f"gate_lost:{cat}")
            alignment -= 0.15

    entry_adx = _f(entry_feats, "adx_14", 25.0)
    live_adx = _f(live_feats, "adx_14", entry_adx)
    if entry_adx >= 20.0 and live_adx < 18.0:
        invalidations.append("adx_collapse")
        alignment -= 0.15
    elif live_adx > entry_adx + 3.0:
        improvements.append("adx_strengthening")
        alignment = min(1.0, alignment + 0.05)

    entry_rsi = _f(entry_feats, "rsi_14", 50.0)
    live_rsi = _f(live_feats, "rsi_14", entry_rsi)
    if pos_side == "long" and live_rsi < 40.0 and entry_rsi >= 45.0:
        invalidations.append("rsi_bearish_shift")
        alignment -= 0.10
    elif pos_side == "short" and live_rsi > 60.0 and entry_rsi <= 55.0:
        invalidations.append("rsi_bullish_shift")
        alignment -= 0.10

    entry_ema9 = _f(entry_feats, "ema_9", 0.0)
    entry_ema21 = _f(entry_feats, "ema_21", 0.0)
    live_ema9 = _f(live_feats, "ema_9", entry_ema9)
    live_ema21 = _f(live_feats, "ema_21", entry_ema21)
    if entry_ema9 > 0 and entry_ema21 > 0 and live_ema9 > 0 and live_ema21 > 0:
        if pos_side == "long" and entry_ema9 >= entry_ema21 and live_ema9 < live_ema21:
            invalidations.append("ema_death_cross")
            alignment -= 0.20
        elif pos_side == "short" and entry_ema9 <= entry_ema21 and live_ema9 > live_ema21:
            invalidations.append("ema_golden_cross")
            alignment -= 0.20
        elif pos_side == "long" and live_ema9 > live_ema21 and entry_ema9 < entry_ema21:
            improvements.append("ema_alignment_improved")
            alignment = min(1.0, alignment + 0.08)

    fsm = live_mc.get("rule_based_pipeline", {})
    if isinstance(fsm, dict):
        fsm_dec = fsm.get("fsm_decision")
        if isinstance(fsm_dec, dict):
            health = str(fsm_dec.get("thesis_health") or "healthy").lower()
            if health == "broken":
                invalidations.append("fsm_thesis_broken")
                alignment -= 0.25
            elif health == "weakening":
                invalidations.append("fsm_thesis_weakening")
                alignment -= 0.12
            elif health == "healthy":
                improvements.append("fsm_thesis_healthy")

    narrative = live_mc.get("narrative_tail") or []
    if isinstance(narrative, list):
        recent = {str(e.get("event_type") or "") for e in narrative[-10:] if isinstance(e, dict)}
        if "breakout_failed" in recent or "trend_exhaustion" in recent:
            invalidations.append("narrative_exhaustion")
            alignment -= 0.15
        if "breakout_confirmed" in recent:
            improvements.append("breakout_confirmed")
            alignment = min(1.0, alignment + 0.06)

    material = live_mc.get("market_intel_material_change")
    if isinstance(material, dict):
        for reason in material.get("reasons") or []:
            rs = str(reason).lower()
            if "regime:" in rs or "trend:" in rs or "structure:" in rs:
                if pos_side == "long" and "bear" in rs:
                    invalidations.append(f"intel_diff:{reason}")
                    alignment -= 0.10
                elif pos_side == "short" and "bull" in rs:
                    invalidations.append(f"intel_diff:{reason}")
                    alignment -= 0.10

    alignment = max(0.0, min(1.0, alignment))

    critical = {
        "ema_death_cross",
        "ema_golden_cross",
        "fsm_thesis_broken",
    }
    has_critical = any(code in critical for code in invalidations)
    would_enter = (
        not has_critical
        and alignment >= 0.55
        and len(invalidations) <= 2
    )

    return ContinuationResult(
        alignment=alignment,
        would_enter_same_side_now=would_enter,
        invalidation_codes=invalidations,
        improvement_codes=improvements,
    )
