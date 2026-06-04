"""Build and broadcast performance metrics over WebSocket after position close."""

from typing import Any, Dict, Optional

import structlog

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.core.websocket_messages import create_performance_update
from backend.services.portfolio_fetch import is_testnet_trading_mode

logger = structlog.get_logger()


async def build_performance_metrics_snapshot(*, days: int = 30) -> Dict[str, Any]:
    """Aggregate performance metrics for WS / chart consumers."""
    if is_testnet_trading_mode():
        from backend.services.agent_trade_ledger_service import get_agent_closed_trades

        rows = await get_agent_closed_trades(limit=500)
        realized_inr = sum(float(r.get("pnl") or 0) for r in rows)
        realized_usd = sum(float(r.get("pnl_usd") or 0) for r in rows)
        total_trades = len(rows)
        winning = sum(1 for r in rows if float(r.get("pnl_usd") or r.get("pnl") or 0) > 0)
        losing = sum(1 for r in rows if float(r.get("pnl_usd") or r.get("pnl") or 0) < 0)
        initial_balance = float(getattr(settings, "initial_balance", 20000.0) or 20000.0)
        total_return_pct = (
            (realized_inr / initial_balance * 100.0) if initial_balance > 0 else 0.0
        )
        win_rate = winning / total_trades if total_trades else 0.0
        return {
            "total_return": realized_inr,
            "total_return_pct": total_return_pct,
            "total_return_usd": realized_usd,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "winning_trades": winning,
            "losing_trades": losing,
        }

    from backend.services.portfolio_service import portfolio_service

    async with AsyncSessionLocal() as db:
        metrics = await portfolio_service.get_performance_metrics(db, days=days)
    if not metrics:
        return {
            "total_return": 0,
            "total_return_pct": 0,
            "win_rate": 0,
            "total_trades": 0,
        }
    return metrics


async def broadcast_performance_update(*, days: int = 30) -> None:
    """Push performance snapshot to frontend via unified WebSocket manager."""
    try:
        from backend.api.websocket.unified_manager import unified_websocket_manager

        metrics = await build_performance_metrics_snapshot(days=days)
        envelope = create_performance_update(metrics)
        await unified_websocket_manager.broadcast(envelope, channel="system_update")
        logger.debug("performance_update_broadcast", total_trades=metrics.get("total_trades"))
    except Exception as exc:
        logger.warning("performance_update_broadcast_failed", error=str(exc))
