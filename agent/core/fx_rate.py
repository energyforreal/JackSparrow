"""USD/INR rate resolution and periodic refresh for agent lot sizing."""

from __future__ import annotations

import math
from typing import Any, Optional

import structlog

from agent.core.config import settings
from agent.core.redis_config import get_cache, set_cache

logger = structlog.get_logger()

USDINR_CACHE_KEY = "fx:usdinr:last"
USDINR_CACHE_TTL_SECONDS = 300


def _parse_rate(value: Any) -> Optional[float]:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 0 or not math.isfinite(rate):
        return None
    return rate


def fallback_usdinr_rate() -> float:
    return float(getattr(settings, "usdinr_fallback_rate", 86.0) or 86.0)


async def resolve_usdinr_rate(
    *,
    payload_rate: Optional[Any] = None,
    state_market_data: Optional[dict] = None,
) -> float:
    """Context → Redis cache → config fallback."""
    if payload_rate is not None:
        parsed = _parse_rate(payload_rate)
        if parsed is not None:
            return parsed
    if isinstance(state_market_data, dict):
        for key in ("usd_inr", "usd_inr_rate", "usdinr", "inr_per_usd"):
            parsed = _parse_rate(state_market_data.get(key))
            if parsed is not None:
                return parsed
    try:
        cached = await get_cache(USDINR_CACHE_KEY)
        if isinstance(cached, dict):
            parsed = _parse_rate(cached.get("rate"))
            if parsed is not None:
                return parsed
    except Exception as e:
        logger.debug("fx_rate_cache_lookup_failed", error=str(e))
    return fallback_usdinr_rate()


async def store_usdinr_rate(rate: float) -> bool:
    parsed = _parse_rate(rate)
    if parsed is None:
        return False
    ttl = int(getattr(settings, "usdinr_cache_ttl_seconds", USDINR_CACHE_TTL_SECONDS) or USDINR_CACHE_TTL_SECONDS)
    return await set_cache(USDINR_CACHE_KEY, {"rate": parsed}, ttl=ttl)


async def refresh_usdinr_rate(delta_client: Any = None) -> float:
    """Fetch best-effort live rate and cache; returns rate used."""
    rate: Optional[float] = None
    if delta_client is not None:
        for symbol in ("USDTUSD", "USDINR", "USDTINR"):
            try:
                ticker = await delta_client.get_ticker(symbol)
                if isinstance(ticker, dict):
                    result = ticker.get("result") or ticker
                    if isinstance(result, dict):
                        for key in (
                            "spot_price",
                            "mark_price",
                            "price",
                            "usd_inr",
                            "usd_inr_rate",
                        ):
                            parsed = _parse_rate(result.get(key))
                            if parsed is not None:
                                rate = parsed
                                break
            except Exception:
                continue
            if rate is not None:
                break
    if rate is None:
        rate = fallback_usdinr_rate()
        logger.debug("fx_rate_refresh_used_fallback", usdinr=rate)
    else:
        logger.info("fx_rate_refresh_ok", usdinr=rate)
    await store_usdinr_rate(rate)
    return rate
