"""v15 entry edge filters (percentile threshold, regime, volatility)."""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from agent.core.config import settings
from agent.core.futures_utils import per_leg_cost_rate

_edge_buffers: Dict[str, collections.deque] = {
    "5m": collections.deque(maxlen=200),
    "15m": collections.deque(maxlen=200),
}


def _tf_key(tf: Optional[str]) -> str:
    t = (tf or "15m").strip().lower()
    return t if t in _edge_buffers else "15m"


def pick_primary_v15_prediction(
    model_predictions: List[Dict[str, Any]],
) -> Tuple[float, str, Dict[str, Any]]:
    """Return edge, timeframe, and prediction dict for strongest |edge| v15 model."""
    v15 = []
    for p in model_predictions:
        ctx = p.get("context") if isinstance(p.get("context"), dict) else {}
        if ctx.get("format") != "v15_pipeline":
            continue
        try:
            edge = float(p.get("prediction", 0.0))
        except (TypeError, ValueError):
            edge = 0.0
        v15.append((abs(edge), edge, str(ctx.get("timeframe", "15m")), p))
    if not v15:
        return 0.0, "15m", {}
    v15.sort(key=lambda x: x[0], reverse=True)
    _, edge, tf, pred = v15[0]
    return edge, tf, pred


def rolling_edge_threshold(timeframe: str) -> float:
    pct = float(getattr(settings, "confidence_percentile", 90.0) or 90.0)
    floor = float(getattr(settings, "edge_floor", 0.15) or 0.15)
    buf = list(_edge_buffers[_tf_key(timeframe)])
    if len(buf) < 20:
        return floor
    return float(np.percentile([abs(x) for x in buf], pct))


def evaluate_v15_entry(
    timeframe: str,
    edge: float,
    features: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (BUY|SELL|HOLD, diagnostics).
    """
    tf = _tf_key(timeframe)
    _edge_buffers[tf].append(edge)
    threshold = rolling_edge_threshold(tf)
    edge_floor = float(getattr(settings, "edge_floor", 0.15) or 0.15)

    atr_pct = features.get("atr_pct")
    if atr_pct is None and features.get("atr_14") and features.get("close"):
        try:
            atr_pct = float(features["atr_14"]) / float(features["close"])
        except (TypeError, ValueError, ZeroDivisionError):
            atr_pct = None
    elif atr_pct is not None:
        try:
            atr_pct = float(atr_pct)
        except (TypeError, ValueError):
            atr_pct = None

    vol_ok = True
    if bool(getattr(settings, "volatility_filter_enabled", True)):
        floor_pct = float(getattr(settings, "v15_atr_pct_floor", 0.0005) or 0.0005)
        if atr_pct is not None:
            vol_ok = atr_pct >= floor_pct

    adx = features.get("adx_14")
    try:
        adx_f = float(adx) if adx is not None else None
    except (TypeError, ValueError):
        adx_f = None
    adx_max = float(getattr(settings, "v15_adx_ranging_max", 25.0) or 25.0)
    ranging_ok = True if adx_f is None else adx_f <= adx_max

    atr_14_raw = features.get("atr_14")
    try:
        atr_14_f = float(atr_14_raw) if atr_14_raw is not None else None
    except (TypeError, ValueError):
        atr_14_f = None

    diag = {
        "edge": edge,
        "edge_threshold": threshold,
        "edge_floor": edge_floor,
        "atr_pct": atr_pct,
        "atr_14": atr_14_f,
        "adx_14": adx_f,
        "v15_timeframe": tf,
        "volatility_filter_passed": vol_ok,
        "regime_filter_passed": ranging_ok,
        "_v15_filters": {
            "volatility_ok": vol_ok,
            "regime_ranging": ranging_ok,
            "edge_above_floor": abs(edge) >= edge_floor,
            "edge_above_percentile": abs(edge) >= threshold,
        },
    }

    if not vol_ok or not ranging_ok:
        return "HOLD", diag

    taker = float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005)
    slip = float(getattr(settings, "slippage_bps", 5.0) or 5.0)
    per_leg = per_leg_cost_rate(taker, slip)
    ratio = float(getattr(settings, "v15_min_edge_cost_ratio", 2.0) or 2.0)
    min_edge_vs_cost = per_leg * ratio
    edge_cost_ok = abs(edge) >= min_edge_vs_cost
    diag["_v15_filters"]["edge_vs_roundtrip_cost"] = edge_cost_ok
    diag["min_edge_vs_cost"] = min_edge_vs_cost

    if not edge_cost_ok:
        return "HOLD", diag

    if edge >= threshold and edge >= edge_floor:
        return "BUY", diag
    if edge <= -threshold and edge <= -edge_floor:
        return "SELL", diag
    return "HOLD", diag


def apply_v15_entry_gate(
    synthesis_signal: str,
    model_predictions: List[Dict[str, Any]],
    features: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """
    If v15 models are present and gate enabled, downgrades BUY/SELL to HOLD
    when v15 entry rules fail. Never promotes HOLD to trade.
    """
    if not bool(getattr(settings, "v15_signal_logic_enabled", True)):
        return synthesis_signal, {}
    if not model_predictions:
        return synthesis_signal, {}
    if not any(
        (p.get("context") or {}).get("format") == "v15_pipeline"
        for p in model_predictions
        if isinstance(p, dict)
    ):
        return synthesis_signal, {}

    if synthesis_signal in ("HOLD", None, ""):
        return synthesis_signal or "HOLD", {}

    edge, tf, _pred = pick_primary_v15_prediction(model_predictions)
    v15_sig, diag = evaluate_v15_entry(tf, edge, features)

    if v15_sig == "HOLD":
        return "HOLD", diag

    if synthesis_signal in ("BUY", "STRONG_BUY") and v15_sig != "BUY":
        return "HOLD", diag
    if synthesis_signal in ("SELL", "STRONG_SELL") and v15_sig != "SELL":
        return "HOLD", diag

    return synthesis_signal, diag
