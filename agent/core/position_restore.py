"""Restore open paper positions from PostgreSQL into the execution engine."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent.persistence.db_writes import _sync_database_url

logger = structlog.get_logger()


def _fetch_open_positions_sync(database_url: str) -> List[Dict[str, Any]]:
    engine = create_engine(
        _sync_database_url(database_url),
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT position_id, symbol, side::text AS side,
                       quantity, entry_price, stop_loss, take_profit
                FROM positions
                WHERE status::text = 'OPEN'
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def restore_open_positions_from_db(execution_module: Any, database_url: str) -> int:
    """Load OPEN rows from `positions` into the in-memory position manager. Returns count restored."""
    if not database_url:
        return 0
    try:
        rows = await asyncio.to_thread(_fetch_open_positions_sync, database_url)
    except Exception as e:
        logger.warning(
            "position_restore_query_failed",
            error=str(e),
            exc_info=True,
        )
        return 0

    restored = 0
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        if execution_module.position_manager.get_position(sym):
            continue
        side_db = (r.get("side") or "").upper()
        side = "long" if side_db == "BUY" else "short"
        try:
            qty = float(r["quantity"])
            ep = float(r["entry_price"])
        except (TypeError, ValueError, KeyError):
            continue
        if qty <= 0 or ep <= 0:
            continue
        oid = str(r.get("position_id") or "restored")[:12]
        sl = float(r["stop_loss"]) if r.get("stop_loss") is not None else None
        tp = float(r["take_profit"]) if r.get("take_profit") is not None else None
        execution_module.position_manager.open_position(
            symbol=sym,
            side=side,
            quantity=qty,
            entry_price=ep,
            order_id=oid,
            stop_loss=sl,
            take_profit=tp,
        )
        restored += 1
        logger.info(
            "position_restored_from_db",
            symbol=sym,
            side=side,
            quantity=qty,
            entry_price=ep,
        )
    return restored
