"""
Redis-backed overrides for reasoning hold-band and trading confidence gates.

Safe bounds prevent runaway threshold drift when Redis is empty or invalid.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

REDIS_KEY_MILD = "learning:mild_thresh"
REDIS_KEY_STRONG = "learning:strong_thresh"
REDIS_KEY_MIN_CONF = "learning:min_confidence"

# Align with ThresholdAdapter.BOUNDS
MILD_BOUNDS = (0.10, 0.28)
STRONG_BOUNDS = (0.30, 0.52)
MIN_CONF_BOUNDS = (0.46, 0.62)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


async def _redis_get_float(key: str) -> Optional[float]:
    try:
        from agent.core.redis_config import get_redis

        r = await get_redis()
        if not r:
            return None
        raw = await r.get(key)
        if raw is None:
            return None
        return float(raw)
    except Exception as e:
        logger.debug("dynamic_threshold_redis_read_failed", key=key, error=str(e))
        return None


async def apply_redis_hold_band_overrides(
    strong_thresh: float,
    mild_thresh: float,
) -> Tuple[float, float]:
    """Apply optional Redis overrides to legacy-path hold band thresholds."""
    try:
        rm = await _redis_get_float(REDIS_KEY_MILD)
        rs = await _redis_get_float(REDIS_KEY_STRONG)
        if rm is not None:
            mild_thresh = _clamp(rm, MILD_BOUNDS[0], MILD_BOUNDS[1])
        if rs is not None:
            strong_thresh = _clamp(rs, STRONG_BOUNDS[0], STRONG_BOUNDS[1])
        if rs is not None and rm is not None and strong_thresh < (mild_thresh + 0.05):
            strong_thresh = mild_thresh + 0.05
    except Exception as e:
        logger.debug("apply_redis_hold_band_overrides_failed", error=str(e))
    return strong_thresh, mild_thresh


async def get_effective_min_confidence_threshold() -> float:
    """Minimum confidence for trade entry; Redis may nudge within bounds."""
    base = float(getattr(settings, "min_confidence_threshold", 0.52) or 0.52)
    rv = await _redis_get_float(REDIS_KEY_MIN_CONF)
    if rv is None:
        return base
    return _clamp(rv, MIN_CONF_BOUNDS[0], MIN_CONF_BOUNDS[1])


def resolve_metadata_recommended_threshold(
    signal: str,
    model_predictions: List[Dict[str, Any]],
) -> Optional[float]:
    """Resolve median recommended threshold from model prediction metadata/context.

    Accepts either:
    - `RECOMMENDED_LONG_THRESHOLD` / `RECOMMENDED_SHORT_THRESHOLD`
    - `runtime_threshold_hints.mtf_entry_min_buy_prob` / `...sell_prob`
    """
    target_key = (
        "RECOMMENDED_LONG_THRESHOLD"
        if signal in ("BUY", "STRONG_BUY")
        else "RECOMMENDED_SHORT_THRESHOLD"
    )
    hint_key = (
        "mtf_entry_min_buy_prob"
        if signal in ("BUY", "STRONG_BUY")
        else "mtf_entry_min_sell_prob"
    )
    values: List[float] = []
    for pred in model_predictions or []:
        if not isinstance(pred, dict):
            continue
        ctx = pred.get("context")
        if not isinstance(ctx, dict):
            continue
        raw = ctx.get(target_key)
        if raw is None:
            hints = ctx.get("runtime_threshold_hints")
            if isinstance(hints, dict):
                raw = hints.get(hint_key)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    values.sort()
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 == 1 else (values[mid - 1] + values[mid]) / 2.0
    return _clamp(float(median), MIN_CONF_BOUNDS[0], MIN_CONF_BOUNDS[1])
