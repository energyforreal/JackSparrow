"""Track orders placed by the JackSparrow agent (not external Delta UI fills)."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

AGENT_CLIENT_ORDER_PREFIX = "js_"
AGENT_DECISION_AUTHORITY = "agent_decision"

# Recent agent fills (newest last); capped ring buffer.
_recent_fills: Deque[Dict[str, Any]] = deque(maxlen=256)
# Latest agent entry intent per symbol (before fill confirms).
_pending_entry_by_symbol: Dict[str, Dict[str, Any]] = {}
# decision_event_id -> unix timestamp (idempotent entry guard)
_executed_decision_ids: Dict[str, float] = {}


def _attribution_window_seconds() -> float:
    return float(getattr(settings, "agent_order_attribution_window_seconds", 3600.0) or 3600.0)


def _decision_idempotency_ttl_seconds() -> float:
    return float(getattr(settings, "agent_decision_idempotency_ttl_seconds", 300.0) or 300.0)


def _prune_executed_decision_ids() -> None:
    ttl = _decision_idempotency_ttl_seconds()
    now = time.time()
    stale = [k for k, ts in _executed_decision_ids.items() if (now - ts) > ttl]
    for k in stale:
        _executed_decision_ids.pop(k, None)


def is_decision_already_executed(decision_event_id: Optional[str]) -> bool:
    """True if this decision event id was already used for an agent entry."""
    if not decision_event_id:
        return False
    _prune_executed_decision_ids()
    key = str(decision_event_id).strip()
    if not key:
        return False
    return key in _executed_decision_ids


def record_decision_execution(decision_event_id: Optional[str]) -> None:
    """Mark a decision event id as consumed for entry execution."""
    if not decision_event_id:
        return
    key = str(decision_event_id).strip()
    if not key:
        return
    _executed_decision_ids[key] = time.time()


def _normalize_side_pm(signed_size: float) -> str:
    return "long" if signed_size >= 0 else "short"


def record_agent_order_intent(
    *,
    symbol: str,
    side: str,
    quantity: float,
    execution_authority: str,
    internal_order_id: Optional[str] = None,
    reasoning_chain_id: Optional[str] = None,
) -> None:
    """Register intent immediately before placing an exchange order."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return
    side_pm = "long" if str(side).lower() in ("buy", "long") else "short"
    _pending_entry_by_symbol[sym] = {
        "symbol": sym,
        "side": side_pm,
        "quantity": float(quantity),
        "execution_authority": str(execution_authority),
        "internal_order_id": internal_order_id,
        "reasoning_chain_id": reasoning_chain_id,
        "recorded_at": time.time(),
        "recorded_at_iso": datetime.now(timezone.utc).isoformat(),
    }


def record_agent_order_fill(
    *,
    symbol: str,
    side: str,
    quantity: float,
    fill_price: float,
    execution_authority: str,
    internal_order_id: Optional[str] = None,
    exchange_order_id: Optional[Any] = None,
    client_order_id: Optional[str] = None,
    reduce_only: bool = False,
    reasoning_chain_id: Optional[str] = None,
) -> None:
    """Record a fill from an agent-authorized ``js_`` order."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return
    side_pm = "long" if str(side).lower() in ("buy", "long") else "short"
    row = {
        "symbol": sym,
        "side": side_pm,
        "quantity": float(quantity),
        "fill_price": float(fill_price),
        "execution_authority": str(execution_authority),
        "internal_order_id": internal_order_id,
        "exchange_order_id": str(exchange_order_id) if exchange_order_id is not None else None,
        "client_order_id": str(client_order_id) if client_order_id else None,
        "reduce_only": bool(reduce_only),
        "reasoning_chain_id": reasoning_chain_id,
        "recorded_at": time.time(),
        "recorded_at_iso": datetime.now(timezone.utc).isoformat(),
    }
    _recent_fills.append(row)
    if not reduce_only:
        _pending_entry_by_symbol.pop(sym, None)
    logger.info(
        "agent_order_fill_registered",
        symbol=sym,
        side=side_pm,
        quantity=quantity,
        exchange_order_id=exchange_order_id,
        client_order_id=client_order_id,
        execution_authority=execution_authority,
        reduce_only=reduce_only,
    )


def _registry_matches(symbol: str, side_pm: str) -> bool:
    window = _attribution_window_seconds()
    now = time.time()
    pending = _pending_entry_by_symbol.get(symbol)
    if pending and pending.get("side") == side_pm:
        if (now - float(pending.get("recorded_at") or 0)) <= window:
            return True
    for row in reversed(_recent_fills):
        if row.get("symbol") != symbol:
            continue
        if row.get("reduce_only"):
            continue
        if row.get("side") != side_pm:
            continue
        if (now - float(row.get("recorded_at") or 0)) <= window:
            return True
    return False


def _order_row_is_agent(order: Dict[str, Any]) -> bool:
    cid = str(
        order.get("client_order_id")
        or order.get("client_order_id_str")
        or ""
    )
    if cid.startswith(AGENT_CLIENT_ORDER_PREFIX):
        return True
    meta = order.get("meta_data") or order.get("metadata")
    if isinstance(meta, dict):
        inner = str(meta.get("client_order_id") or "")
        if inner.startswith(AGENT_CLIENT_ORDER_PREFIX):
            return True
    return False


async def _delta_history_supports_position(
    execution_module: Any,
    symbol: str,
    side_pm: str,
) -> bool:
    """True if recent Delta order history shows an agent ``js_`` entry fill for symbol/side."""
    client = getattr(execution_module, "delta_client", None)
    if client is None:
        return False
    window = _attribution_window_seconds()
    cutoff = time.time() - window
    try:
        product_id = await client.resolve_product_id(symbol)
        hist = await client.get_orders_history(
            product_ids=str(product_id),
            page_size=50,
        )
    except Exception as exc:
        logger.debug("agent_order_history_attribution_failed", symbol=symbol, error=str(exc))
        return False

    rows = hist.get("result") if isinstance(hist, dict) else None
    if not isinstance(rows, list):
        return False

    want_buy = side_pm == "long"
    for order in rows:
        if not isinstance(order, dict):
            continue
        if not _order_row_is_agent(order):
            continue
        state = str(order.get("state") or order.get("status") or "").lower()
        if state not in ("closed", "filled"):
            continue
        side_raw = str(order.get("side") or "").lower()
        is_buy = side_raw.startswith("b")
        if is_buy != want_buy:
            continue
        ts_raw = order.get("updated_at") or order.get("created_at")
        if ts_raw is None:
            continue
        try:
            if isinstance(ts_raw, (int, float)):
                ts = float(ts_raw)
                if ts > 1e12:
                    ts /= 1000.0
            else:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            return True
    return False


async def is_exchange_position_agent_attributed(
    execution_module: Any,
    symbol: str,
    exchange_row: Dict[str, Any],
) -> bool:
    """Return True only if this exchange leg plausibly came from an agent-placed order."""
    if not bool(getattr(settings, "agent_only_delta_orders", True)):
        return True

    sym = str(symbol or "").strip().upper()
    signed_size = float(exchange_row.get("size") or 0)
    if abs(signed_size) <= 0:
        return False
    side_pm = _normalize_side_pm(signed_size)

    if _registry_matches(sym, side_pm):
        return True

    return await _delta_history_supports_position(execution_module, sym, side_pm)


def is_agent_controlled_authority(execution_authority: Optional[str]) -> bool:
    return str(execution_authority or "").strip().lower() == AGENT_DECISION_AUTHORITY


def clear_registry() -> None:
    """Test helper."""
    _recent_fills.clear()
    _pending_entry_by_symbol.clear()
