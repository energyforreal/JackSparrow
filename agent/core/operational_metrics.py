"""Publish operational metrics to Redis for backend health dashboards."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

MARKET_DATA_TICK_KEY_PREFIX = "market_data:last_tick:"
EXCHANGE_CONNECTIVITY_KEY = "exchange:connectivity"
LATENCY_METRICS_KEY = "metrics:latency:execution"


async def publish_market_data_tick(symbol: str) -> None:
    """Record last market tick timestamp (TTL 60s)."""
    try:
        from agent.core.redis_config import get_redis

        client = await get_redis()
        if client is None:
            return
        sym = (symbol or "BTCUSD").upper()
        ts = datetime.now(timezone.utc).isoformat()
        await client.setex(f"{MARKET_DATA_TICK_KEY_PREFIX}{sym}", 60, ts)
    except Exception as exc:
        logger.debug("market_data_tick_redis_publish_failed", error=str(exc))


async def publish_exchange_connectivity(ok: bool, detail: Optional[str] = None) -> None:
    """Record Delta REST reachability for health reporting (TTL 120s)."""
    try:
        from agent.core.redis_config import get_redis

        client = await get_redis()
        if client is None:
            return
        payload = {
            "ok": bool(ok),
            "detail": detail or "",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        await client.setex(EXCHANGE_CONNECTIVITY_KEY, 120, json.dumps(payload))
    except Exception as exc:
        logger.debug("exchange_connectivity_redis_publish_failed", error=str(exc))


async def publish_latency_metrics(snapshot: Dict[str, Any]) -> None:
    """Publish execution latency snapshot (TTL 120s)."""
    if not snapshot:
        return
    try:
        from agent.core.redis_config import get_redis

        client = await get_redis()
        if client is None:
            return
        payload = {
            **snapshot,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        await client.setex(LATENCY_METRICS_KEY, 120, json.dumps(payload, default=str))
    except Exception as exc:
        logger.debug("latency_metrics_redis_publish_failed", error=str(exc))
