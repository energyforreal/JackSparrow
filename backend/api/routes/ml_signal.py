"""
ML model status and v15 signal diagnostics (proxied from agent / Redis).
"""

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Query
import structlog

from backend.services.agent_service import agent_service
from backend.core.redis import get_redis

logger = structlog.get_logger()

router = APIRouter()


@router.get("/models/status")
async def models_status() -> Dict[str, Any]:
    """Summarize agent model registry health (includes v15 `model_format` when exposed)."""
    status = await agent_service.get_agent_status()
    if not status:
        return {"available": False, "model_nodes": {}, "model_format": None}
    detailed = status.get("detailed_health") or {}
    nodes = detailed.get("model_nodes") or {}
    return {
        "available": bool(status.get("available", True)),
        "agent_state": status.get("state"),
        "model_nodes": nodes,
        "model_format": nodes.get("model_format"),
        "latency_ms": status.get("latency_ms"),
        "status_stale": status.get("status_stale"),
    }


@router.get("/signal/edge-history")
async def edge_history(
    symbol: str = Query(default="BTCUSD"),
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """Recent v15 edge samples recorded by the backend subscriber (Redis list)."""
    out: List[Dict[str, Any]] = []
    try:
        r = await get_redis(required=False)
        if r:
            key = f"jacksparrow:v15:edge_history:{symbol}"
            raw_items = await r.lrange(key, 0, limit - 1)
            for raw in raw_items or []:
                try:
                    out.append(json.loads(raw))
                except (TypeError, json.JSONDecodeError):
                    continue
    except Exception as e:
        logger.warning("edge_history_redis_error", error=str(e), symbol=symbol)
    return {"symbol": symbol, "edges": out, "count": len(out)}
