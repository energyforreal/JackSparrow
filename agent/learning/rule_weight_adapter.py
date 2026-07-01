"""Bounded adaptive gate category weights from rule evaluation evidence."""

from __future__ import annotations

import json
from typing import Any, Dict

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend": 0.30,
    "structure": 0.15,
    "breakout": 0.25,
    "liquidity": 0.15,
    "volatility": 0.10,
    "risk": 0.05,
}

_MIN_W = 0.10
_MAX_W = 0.50
_NUDGE = 0.05


def get_gate_weights() -> Dict[str, float]:
    """Return current gate category weights (env override or defaults)."""
    raw = getattr(settings, "gate_category_weights", None)
    if isinstance(raw, dict) and raw:
        return {str(k): float(v) for k, v in raw.items()}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): float(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_WEIGHTS)


def nudge_weights(rule_eval: Dict[str, Any]) -> Dict[str, float]:
    """Nudge weights based on per-rule false positive rates."""
    weights = get_gate_weights()
    per_rule = rule_eval.get("per_rule") if isinstance(rule_eval.get("per_rule"), dict) else {}

    for cat, stats in per_rule.items():
        if cat not in weights:
            continue
        if not isinstance(stats, dict):
            continue
        fpr = stats.get("false_positive_rate")
        fnr = stats.get("false_negative_rate")
        try:
            if fpr is not None and float(fpr) > 0.4:
                weights[cat] = max(_MIN_W, weights[cat] - _NUDGE)
            elif fnr is not None and float(fnr) > 0.4:
                weights[cat] = min(_MAX_W, weights[cat] + _NUDGE)
        except (TypeError, ValueError):
            continue

    total = sum(weights.values()) or 1.0
    return {k: round(v / total, 4) for k, v in weights.items()}
