"""Persist and rehydrate in-flight orders for crash recovery (JSON file + exchange)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_OPEN_STATUSES = frozenset({"pending", "open", "partially_filled"})


def _orders_path() -> Path:
    root = Path(getattr(settings, "data_dir", "data") or "data")
    root.mkdir(parents=True, exist_ok=True)
    return root / "agent_open_orders.json"


def persist_open_order_records(orders: Dict[str, Any]) -> None:
    """Persist open orders from Order.to_dict() records."""
    if not bool(getattr(settings, "order_persistence_enabled", True)):
        return
    open_records: List[Dict[str, Any]] = []
    for order in orders.values():
        to_dict = getattr(order, "to_dict", None)
        if not callable(to_dict):
            continue
        rec = to_dict()
        if rec.get("status") in _OPEN_STATUSES:
            if hasattr(order, "bracket_sl_tp_active"):
                rec["bracket_sl_tp_active"] = bool(getattr(order, "bracket_sl_tp_active"))
            open_records.append(rec)
    try:
        _orders_path().write_text(
            json.dumps(
                {"updated_at": datetime.now(timezone.utc).isoformat(), "orders": open_records}
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("order_persistence_write_failed", error=str(exc))


def load_persisted_order_records() -> List[Dict[str, Any]]:
    path = _orders_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("order_persistence_read_failed", error=str(exc))
        return []
    orders_raw = raw.get("orders") if isinstance(raw, dict) else []
    return [r for r in orders_raw if isinstance(r, dict) and r.get("order_id")]


async def rehydrate_orders_from_exchange(
    order_manager: Any,
    delta_client: Any,
    order_factory: Any,
    symbol: Optional[str] = None,
) -> int:
    """Merge Delta open orders into OrderManager via order_factory(record)."""
    if delta_client is None:
        return 0
    sym = symbol or str(getattr(settings, "agent_symbol", "BTCUSD") or "BTCUSD")
    try:
        result = await delta_client.get_orders(states="open")
    except Exception as exc:
        logger.warning("order_rehydrate_exchange_failed", error=str(exc))
        return 0
    rows: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, list):
            rows = [r for r in payload if isinstance(r, dict)]
        elif isinstance(payload, dict):
            rows = [payload]
    added = 0
    for row in rows:
        row_sym = str(row.get("product_symbol") or row.get("symbol") or "").strip().upper()
        if row_sym and row_sym != sym.upper():
            continue
        ex_id = row.get("id")
        if ex_id is None:
            continue
        order_id = f"ex_{ex_id}"
        if order_manager.get_order(order_id):
            continue
        try:
            qty = float(row.get("size") or row.get("unfilled_size") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        side = str(row.get("side") or "buy").lower()
        record = {
            "order_id": order_id,
            "symbol": sym,
            "side": side,
            "order_type": str(row.get("order_type") or "market").lower(),
            "quantity": qty,
            "exchange_order_id": int(ex_id) if str(ex_id).isdigit() else ex_id,
            "status": "open",
        }
        state = str(row.get("state") or "open").lower()
        if state in ("closed", "filled"):
            record["status"] = "filled"
        elif state in ("cancelled", "rejected"):
            record["status"] = state
        order_manager.add_order(order_factory(record))
        added += 1
    if added:
        logger.info("order_rehydrate_exchange_complete", symbol=sym, added=added)
    return added


async def sync_open_orders_with_exchange(
    order_manager: Any,
    delta_client: Any,
    symbol: Optional[str] = None,
) -> int:
    """Reconcile in-flight local orders against Delta open-order state."""
    if delta_client is None or order_manager is None:
        return 0
    sym = symbol or str(getattr(settings, "agent_symbol", "BTCUSD") or "BTCUSD")
    open_local = {
        oid: order
        for oid, order in getattr(order_manager, "orders", {}).items()
        if str(getattr(order, "status", "")).lower() in _OPEN_STATUSES
    }
    if not open_local:
        return 0
    try:
        result = await delta_client.get_orders(states="open")
    except Exception as exc:
        logger.debug("order_sync_exchange_failed", error=str(exc))
        return 0
    rows: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        payload = result.get("result")
        if isinstance(payload, list):
            rows = [r for r in payload if isinstance(r, dict)]
    exchange_by_id: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        row_sym = str(row.get("product_symbol") or row.get("symbol") or "").strip().upper()
        if row_sym and row_sym != sym.upper():
            continue
        ex_id = row.get("id")
        if ex_id is not None:
            exchange_by_id[f"ex_{ex_id}"] = row
    updated = 0
    for order_id, order in list(open_local.items()):
        ex_id = getattr(order, "exchange_order_id", None)
        lookup_id = order_id
        if ex_id is not None:
            lookup_id = f"ex_{ex_id}"
        row = exchange_by_id.get(lookup_id)
        if row is None:
            if ex_id is not None and f"ex_{ex_id}" not in exchange_by_id:
                order.transition_to("filled")
                updated += 1
            continue
        state = str(row.get("state") or "open").lower()
        if state in ("closed", "filled"):
            try:
                fill_px = float(row.get("average_fill_price") or row.get("limit_price") or 0)
            except (TypeError, ValueError):
                fill_px = 0.0
            try:
                fill_qty = float(row.get("size") or order.quantity or 0)
            except (TypeError, ValueError):
                fill_qty = float(getattr(order, "quantity", 0) or 0)
            if fill_qty > 0 and fill_px > 0 and hasattr(order, "update_fill"):
                order.update_fill(fill_qty, fill_px)
            else:
                order.transition_to("filled")
            updated += 1
        elif state in ("cancelled", "rejected"):
            order.transition_to(state)
            updated += 1
    if updated:
        logger.info("order_sync_exchange_complete", symbol=sym, updated=updated)
        try:
            persist_open_order_records(order_manager.orders)
        except Exception:
            pass
    return updated
