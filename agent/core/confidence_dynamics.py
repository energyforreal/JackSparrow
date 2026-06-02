"""Shared helpers for dynamic trading-signal confidence (entry_proba margins, floors)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def entry_proba_from_context(ctx: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not isinstance(ctx, dict):
        return None
    raw = ctx.get("entry_proba")
    if not isinstance(raw, dict):
        return None
    try:
        return {
            "sell": float(raw.get("sell", 0.0)),
            "hold": float(raw.get("hold", 0.0)),
            "buy": float(raw.get("buy", 0.0)),
        }
    except (TypeError, ValueError):
        return None


def entry_proba_margin(proba: Dict[str, float]) -> float:
    """Directional separation: |buy - sell|."""
    return abs(float(proba.get("buy", 0.0)) - float(proba.get("sell", 0.0)))


def max_class_probability(proba: Dict[str, float]) -> float:
    return max(
        float(proba.get("buy", 0.0)),
        float(proba.get("sell", 0.0)),
        float(proba.get("hold", 0.0)),
    )


def aggregate_entry_proba_strength(
    model_predictions: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """Summarize entry_proba margins across models for reasoning and UI."""
    margins: List[float] = []
    max_probs: List[float] = []
    for pred in model_predictions or []:
        if not isinstance(pred, dict):
            continue
        ctx = pred.get("context") if isinstance(pred.get("context"), dict) else {}
        proba = entry_proba_from_context(ctx)
        if not proba:
            continue
        margins.append(entry_proba_margin(proba))
        max_probs.append(max_class_probability(proba))

    if not margins:
        return {
            "entry_proba_margin_mean": None,
            "entry_proba_margin_max": None,
            "entry_proba_max_class_mean": None,
            "signal_strength": None,
        }

    margin_mean = sum(margins) / len(margins)
    margin_max = max(margins)
    max_class_mean = sum(max_probs) / len(max_probs) if max_probs else margin_mean
    # Primary display strength: emphasize peak conviction with mean margin.
    signal_strength = max(
        0.0,
        min(1.0, 0.55 * margin_max + 0.30 * margin_mean + 0.15 * max_class_mean),
    )
    return {
        "entry_proba_margin_mean": margin_mean,
        "entry_proba_margin_max": margin_max,
        "entry_proba_max_class_mean": max_class_mean,
        "signal_strength": signal_strength,
    }


def margin_enhanced_confidence(
    model_predictions: List[Dict[str, Any]],
    *,
    fallback_avg: float,
    margin_weight: float = 0.45,
) -> float:
    """Blend mean model confidence with entry_proba-derived strength when available."""
    try:
        base = max(0.0, min(1.0, float(fallback_avg)))
    except (TypeError, ValueError):
        base = 0.0

    strength = aggregate_entry_proba_strength(model_predictions)
    sig = strength.get("signal_strength")
    if sig is None:
        return base

    w = max(0.0, min(1.0, float(margin_weight)))
    blended = (1.0 - w) * base + w * float(sig)
    return max(0.0, min(1.0, blended))


def proportional_v43_entry_floor(
    final_confidence: float,
    base_confidence: float,
    margin_mean: float,
    *,
    ai_floor: float = 0.7,
) -> float:
    """Raise confidence toward ai_floor proportionally to buy/sell margin (no flat ~0.6895 plateau)."""
    try:
        fc = max(0.0, min(1.0, float(final_confidence)))
        bc = max(0.0, min(1.0, float(base_confidence)))
        floor = max(0.0, min(1.0, float(ai_floor)))
    except (TypeError, ValueError):
        return final_confidence

    floor_threshold = floor * 0.85
    if bc < floor_threshold:
        return fc

    # margin 0.08..0.32 maps to blend weight 0..1
    m = max(0.0, min(1.0, (float(margin_mean) - 0.08) / 0.24))
    target_low = floor * 0.72
    target_high = floor * 0.98
    target = target_low + (target_high - target_low) * m
    if fc >= target:
        return fc
    return fc + (target - fc) * m


def adjudication_confidence(
    trade_score: float,
    *,
    verdict: str,
) -> float:
    """Map trade score (0–100) and adjudication verdict to continuous step-6 confidence."""
    try:
        score = max(0.0, min(100.0, float(trade_score)))
    except (TypeError, ValueError):
        score = 0.0
    t = score / 100.0

    if verdict == "agree":
        return max(0.0, min(1.0, 0.52 + 0.43 * t))
    if verdict == "ml_reject":
        return max(0.0, min(1.0, 0.28 + 0.22 * t))
    if verdict == "conflict":
        return max(0.0, min(1.0, 0.24 + 0.18 * t))
    if verdict == "score_reject":
        return max(0.0, min(1.0, 0.20 + 0.20 * t))
    return max(0.0, min(1.0, 0.15 + 0.12 * t))


def synthetic_entry_proba_from_ic(
    thesis_signal: str,
    edge: float,
    threshold: float,
    unc_scale: float,
) -> Dict[str, float]:
    """Emit buy/sell/hold simplex for IC path so reasoning can use margin logic."""
    thr = max(float(threshold), 1e-6)
    ratio = float(np.tanh(float(edge) / thr))
    hold = max(0.05, min(0.5, 0.35 * max(0.3, min(1.0, float(unc_scale)))))
    rem = max(0.0, 1.0 - hold)
    sig = str(thesis_signal or "HOLD").upper()
    if sig in ("BUY", "STRONG_BUY"):
        buy = rem * (0.55 + 0.45 * min(1.0, abs(ratio)))
        sell = rem - buy
    elif sig in ("SELL", "STRONG_SELL"):
        sell = rem * (0.55 + 0.45 * min(1.0, abs(ratio)))
        buy = rem - sell
    else:
        buy = rem * 0.5
        sell = rem * 0.5
    total = buy + sell + hold
    if total <= 0:
        return {"buy": 0.33, "sell": 0.33, "hold": 0.34}
    return {"buy": buy / total, "sell": sell / total, "hold": hold / total}
