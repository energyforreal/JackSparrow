"""
FX rate service for USD/INR conversions.

Phase-1 behavior:
- Prioritize existing feed values pushed by market events.
- Fall back to cached last-good value.
- Final fallback to configured/default static rate.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog

from backend.core.redis import get_cache, set_cache

logger = structlog.get_logger()

USDINR_CACHE_KEY = "fx:usdinr:last"
USDINR_TTL_SECONDS = 3600
DEFAULT_USDINR_FALLBACK = 83.0


def _parse_rate(value: object) -> Optional[float]:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return rate


def get_fallback_usdinr_rate() -> float:
    env_val = os.getenv("USDINR_FALLBACK_RATE")
    parsed = _parse_rate(env_val)
    return parsed if parsed is not None else DEFAULT_USDINR_FALLBACK


async def update_usdinr_rate(rate: object) -> Optional[float]:
    parsed = _parse_rate(rate)
    if parsed is None:
        return None
    await set_cache(USDINR_CACHE_KEY, {"rate": parsed}, ttl=USDINR_TTL_SECONDS)
    return parsed


async def get_usdinr_rate() -> float:
    cached = await get_cache(USDINR_CACHE_KEY)
    if isinstance(cached, dict):
        parsed = _parse_rate(cached.get("rate"))
        if parsed is not None:
            return parsed

    fallback = get_fallback_usdinr_rate()
    logger.debug("fx_rate_fallback_used", usdinr=fallback)
    return fallback
