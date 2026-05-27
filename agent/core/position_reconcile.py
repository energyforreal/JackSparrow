"""Reconcile in-memory positions with Delta testnet exchange snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import structlog

from agent.core.agent_order_registry import is_exchange_position_agent_attributed
from agent.core.config import settings
from agent.core.sl_tp import compute_stop_take_prices
from agent.events.event_bus import event_bus

logger = structlog.get_logger()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_exchange_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def parse_margined_rows(view: Any) -> List[Dict[str, Any]]:
    """Extract position dict rows from a Delta margined-positions payload."""
    if not isinstance(view, dict):
        return []
    result = view.get("result")
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        return [result]
    return []


def exchange_open_symbols(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map symbol -> exchange row for non-zero margined positions."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("product_symbol") or row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        size = _coerce_float(row.get("size"))
        if abs(size) <= 0:
            continue
        out[sym] = row
    return out


def _side_from_signed_size(size: float) -> str:
    return "long" if size >= 0 else "short"


async def reconcile_positions_with_exchange(execution_module: Any) -> Dict[str, Any]:
    """Align position_manager with exchange margined positions.

    - Adopt exchange legs missing locally (so SL/TP monitoring applies).
    - Optionally flatten exchange-only orphans when mode is ``close_orphan``.
    - Clear stale local OPEN rows when exchange is flat for that symbol.
    """
    summary: Dict[str, Any] = {
        "adopted": [],
        "closed_exchange": [],
        "cleared_local": [],
        "skipped": [],
    }

    if not bool(getattr(settings, "exchange_position_reconcile_enabled", True)):
        summary["skipped"].append("disabled")
        return summary

    try:
        view = await execution_module.get_margined_positions_view()
    except Exception as exc:
        logger.warning("position_reconcile_fetch_failed", error=str(exc))
        summary["skipped"].append("fetch_failed")
        return summary

    rows = parse_margined_rows(view)
    ex_map = exchange_open_symbols(rows)
    ex_syms: Set[str] = set(ex_map.keys())

    mode = str(
        getattr(settings, "exchange_position_reconcile_orphan_mode", "close_orphan")
        or "close_orphan"
    ).lower()
    agent_only = bool(getattr(settings, "agent_only_delta_orders", True))

    pm = execution_module.position_manager
    local_open = {
        sym: pos
        for sym, pos in pm.get_all_positions().items()
        if pos and str(pos.get("status") or "").lower() == "open"
    }

    for sym, row in ex_map.items():
        if sym in local_open:
            continue

        attributed = True
        if agent_only:
            attributed = await is_exchange_position_agent_attributed(
                execution_module, sym, row
            )

        if agent_only and not attributed:
            result = await execution_module.close_exchange_position(
                sym, row=row, exit_reason="unattributed_exchange_position"
            )
            if getattr(result, "success", False):
                summary["closed_exchange"].append(sym)
            else:
                logger.warning(
                    "position_reconcile_close_unattributed_failed",
                    symbol=sym,
                    error=getattr(result, "error_message", None),
                )
            continue

        if mode == "close_orphan" and not agent_only:
            result = await execution_module.close_exchange_position(
                sym, row=row, exit_reason="exchange_orphan_close"
            )
            if getattr(result, "success", False):
                summary["closed_exchange"].append(sym)
            else:
                logger.warning(
                    "position_reconcile_close_orphan_failed",
                    symbol=sym,
                    error=getattr(result, "error_message", None),
                )
            continue

        adopted = await execution_module.adopt_exchange_position(sym, row)
        if adopted:
            summary["adopted"].append(sym)

    for sym in list(local_open.keys()):
        if sym in ex_syms:
            continue
        pos = local_open[sym]
        entry_px = float(pos.get("entry_price") or 0)
        exit_px = float(pos.get("current_price") or entry_px)
        if exit_px <= 0:
            exit_px = entry_px
        logger.warning(
            "position_reconcile_local_without_exchange",
            symbol=sym,
            side=pos.get("side"),
            entry_price=entry_px,
            exit_price=exit_px,
        )
        closed = pm.close_position(
            symbol=sym,
            exit_price=exit_px,
            exit_order_id="reconcile_local_stale",
        )
        summary["cleared_local"].append(sym)

        # Emit PositionClosedEvent so the backend ledger, Redis and frontend
        # all receive the close notification — prevents ghost open positions.
        try:
            from agent.events.event_types import PositionClosedEvent

            pos_id = f"pos_reconcile_{sym}"
            entry_time = pos.get("entry_time") or pos.get("opened_at")
            payload: Dict[str, Any] = {
                "position_id": pos_id,
                "symbol": sym,
                "side": pos.get("side", ""),
                "entry_price": entry_px,
                "exit_price": exit_px,
                "quantity": float(pos.get("lots") or pos.get("quantity") or 0),
                "pnl": 0.0,
                "gross_pnl_usd": 0.0,
                "fees_usd": 0.0,
                "exit_reason": "reconcile_exchange_flat",
                "timestamp": datetime.now(timezone.utc),
            }
            if entry_time is not None:
                payload["entry_time"] = entry_time
            if closed and isinstance(closed, dict):
                order_id = closed.get("entry_order_id") or closed.get("exit_order_id")
                if order_id:
                    payload["exchange_order_id"] = str(order_id)
            ev = PositionClosedEvent(source="position_reconcile", payload=payload)
            await event_bus.publish(ev)
        except Exception as _ev_err:
            logger.warning(
                "position_reconcile_position_closed_event_failed",
                symbol=sym,
                error=str(_ev_err),
            )

    if summary["adopted"] or summary["closed_exchange"] or summary["cleared_local"]:
        logger.info("position_reconcile_complete", **summary)

    try:
        from agent.core.mcp_orchestrator import mark_position_reconcile_completed

        mark_position_reconcile_completed()
    except Exception:
        pass

    return summary


def symbols_to_monitor(
    execution_module: Any,
    exchange_rows: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Symbols with a local OPEN position (only these receive manage_position)."""
    pm = execution_module.position_manager
    symbols: Set[str] = set()
    for sym, pos in pm.get_all_positions().items():
        if pos and str(pos.get("status") or "").lower() == "open":
            symbols.add(str(sym))
    return sorted(symbols)
