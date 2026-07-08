"""Map cognition expectation forecasts to post-entry lifecycle hints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from agent.core.config import settings

ForecastHint = Literal["hold", "tighten", "extend_tp", "reduce_tp", "exit_candidate"]


@dataclass
class ForecastAdjustment:
    """Lifecycle hints derived from live expectation vs entry snapshot."""

    hint: ForecastHint
    confidence_delta: float
    reason_codes: List[str]
    dominant_expectation: str = ""
    expectation_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hint": self.hint,
            "confidence_delta": self.confidence_delta,
            "reason_codes": list(self.reason_codes),
            "dominant_expectation": self.dominant_expectation,
            "expectation_confidence": self.expectation_confidence,
        }


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _expectation_from_context(live_mc: Dict[str, Any]) -> Dict[str, Any]:
    dc = live_mc.get("decision_context_v3")
    if isinstance(dc, dict):
        exp = dc.get("expectation")
        if isinstance(exp, dict):
            return exp
    forecast = live_mc.get("market_forecast")
    if isinstance(forecast, dict):
        return forecast
    return {}


def _direction_bias_from_context(mc: Dict[str, Any]) -> str:
    """Read the present-tense directional lean (LONG/SHORT/HOLD) from a decision_context_v3 dict."""
    dc = mc.get("decision_context_v3")
    if isinstance(dc, dict):
        understanding = dc.get("understanding")
        if isinstance(understanding, dict):
            bias = understanding.get("direction_bias")
            if isinstance(bias, str) and bias:
                return bias.upper()
    return ""


def _entry_expectation(entry_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    dc = entry_snapshot.get("decision_context")
    if not isinstance(dc, dict):
        return {}
    # Real entry snapshots nest expectation under decision_context["decision_context_v3"]
    # (see agent/persistence/trade_snapshot.py: decision_context["decision_context_v3"] = dict(dc_v3)).
    exp = _expectation_from_context(dc)
    if exp:
        return exp
    # Legacy/flat fallback for any producer that writes expectation at the top level.
    flat = dc.get("expectation") or dc.get("last_expectation")
    return flat if isinstance(flat, dict) else {}


def _entry_direction_bias(entry_snapshot: Dict[str, Any]) -> str:
    dc = entry_snapshot.get("decision_context")
    if isinstance(dc, dict):
        return _direction_bias_from_context(dc)
    return ""


def _position_side(position: Dict[str, Any]) -> str:
    side = str(position.get("side") or "long").lower()
    return "long" if side in ("long", "buy") else "short"


# Labels that are already directional in themselves (legacy/explicit producers).
_LONG_LABELS = ("bullish", "long", "up", "rise", "markup")
_SHORT_LABELS = ("bearish", "short", "down", "fall", "markdown")

# Real expectation-engine labels (expectation_engine.py) describe a *type* of move,
# not a *direction* — trend_continuation/breakout persist whatever direction is already
# prevailing; reversal works against it; vol_expansion has no directional meaning at all.
_CONTINUATION_LABELS = ("trend_continuation", "breakout")
_REVERSAL_LABELS = ("reversal",)


def _aligned_with_position(
    dominant: str, pos_side: str, direction_bias: str = ""
) -> Optional[bool]:
    """
    Whether the dominant expectation favors the side the position is already on.

    Returns True/False when the forecast has a clear directional read, or None when
    the read is directionally ambiguous (e.g. vol_expansion, or no direction_bias
    available) — callers should treat None as "unknown", not as "misaligned".
    """
    d = dominant.lower()
    if d in _LONG_LABELS:
        return pos_side == "long"
    if d in _SHORT_LABELS:
        return pos_side == "short"

    bias = str(direction_bias or "").upper()
    if bias not in ("LONG", "SHORT"):
        return None

    if d in _CONTINUATION_LABELS:
        favors = bias
    elif d in _REVERSAL_LABELS:
        favors = "SHORT" if bias == "LONG" else "LONG"
    else:
        # vol_expansion / neutral / unrecognized — no directional signal to extract.
        return None

    return favors == pos_side.upper()


def evaluate_forecast_adjustment(
    position: Dict[str, Any],
    entry_snapshot: Dict[str, Any],
    live_mc: Dict[str, Any],
) -> ForecastAdjustment:
    """
    Compare live cognition expectation to entry-time expectation.

    Returns advisory hints consumed by Trade Lifecycle Engine.
    """
    if not bool(getattr(settings, "position_forecast_adapter_enabled", True)):
        return ForecastAdjustment(
            hint="hold",
            confidence_delta=0.0,
            reason_codes=[],
        )

    live_exp = _expectation_from_context(live_mc)
    entry_exp = _entry_expectation(entry_snapshot)
    if not live_exp:
        return ForecastAdjustment(hint="hold", confidence_delta=0.0, reason_codes=[])

    pos_side = _position_side(position)
    dominant = str(live_exp.get("dominant_expectation") or live_exp.get("direction") or "")
    entry_dom = str(
        entry_exp.get("dominant_expectation") or entry_exp.get("direction") or ""
    )
    conf = _f(live_exp.get("confidence") or live_exp.get("expectation_confidence"), 0.5)
    entry_conf = _f(entry_exp.get("confidence") or entry_exp.get("expectation_confidence"), conf)
    conf_delta = conf - entry_conf

    live_bias = _direction_bias_from_context(live_mc)
    entry_bias = _entry_direction_bias(entry_snapshot) or live_bias

    reasons: List[str] = []
    aligned = _aligned_with_position(dominant, pos_side, live_bias)
    entry_aligned = (
        _aligned_with_position(entry_dom, pos_side, entry_bias) if entry_dom else None
    )

    if dominant and entry_dom and dominant != entry_dom:
        reasons.append(f"forecast_shift:{entry_dom}->{dominant}")

    if aligned is False and conf >= 0.55:
        return ForecastAdjustment(
            hint="exit_candidate",
            confidence_delta=conf_delta,
            reason_codes=reasons + ["forecast_opposes_position"],
            dominant_expectation=dominant,
            expectation_confidence=conf,
        )

    if aligned is True and conf_delta >= 0.08 and conf >= 0.6:
        return ForecastAdjustment(
            hint="extend_tp",
            confidence_delta=conf_delta,
            reason_codes=reasons + ["forecast_upgrade_aligned"],
            dominant_expectation=dominant,
            expectation_confidence=conf,
        )

    if entry_aligned is True and aligned is False and conf_delta <= -0.08:
        return ForecastAdjustment(
            hint="reduce_tp",
            confidence_delta=conf_delta,
            reason_codes=reasons + ["forecast_downgrade_misaligned"],
            dominant_expectation=dominant,
            expectation_confidence=conf,
        )

    if conf_delta <= -0.12:
        return ForecastAdjustment(
            hint="tighten",
            confidence_delta=conf_delta,
            reason_codes=reasons + ["forecast_confidence_drop"],
            dominant_expectation=dominant,
            expectation_confidence=conf,
        )

    return ForecastAdjustment(
        hint="hold",
        confidence_delta=conf_delta,
        reason_codes=reasons,
        dominant_expectation=dominant,
        expectation_confidence=conf,
    )
