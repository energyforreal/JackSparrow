"""Reconcile in-memory positions with Delta testnet exchange snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import structlog

from agent.core.agent_order_registry import is_exchange_position_agent_attributed
from agent.core.config import settings
from agent.core.sl_tp import compute_stop_take_prices
from agent.events.event_bus import event_bus
from agent.events.schemas import PositionClosedEvent

logger = structlog.get_logger()

_reconcile_healthy: bool = True
_reconcile_block_reason: Optional[str] = None
_reconcile_divergence: List[str] = []


def is_reconcile_healthy() -> bool:
    """False when local vs exchange position sets disagree (blocks new entries)."""
    if not bool(getattr(settings, "exchange_position_reconcile_enabled", True)):
        return True
    if not bool(getattr(settings, "block_entries_on_reconcile_divergence", True)):
        return True
    return _reconcile_healthy


def get_reconcile_block_reason() -> str:
    return _reconcile_block_reason or "Position reconcile unhealthy — new entries blocked"


def get_reconcile_divergence() -> List[str]:
    return list(_reconcile_divergence)


def _set_reconcile_health(healthy: bool, reason: Optional[str] = None, divergence: Optional[List[str]] = None) -> None:
    global _reconcile_healthy, _reconcile_block_reason, _reconcile_divergence
    _reconcile_healthy = healthy
    _reconcile_block_reason = reason
    _reconcile_divergence = list(divergence or [])


def detect_position_divergence(
    execution_module: Any,
    exchange_rows: List[Dict[str, Any]],
) -> List[str]:
    """Return human-readable divergence messages (empty if aligned)."""
    issues: List[str] = []
    ex_map = exchange_open_symbols(exchange_rows)
    pm = execution_module.position_manager
    local_open = {
        sym: pos
        for sym, pos in pm.get_all_positions().items()
        if pos and str(pos.get("status") or "").lower() == "open"
    }
    for sym in set(local_open.keys()) | set(ex_map.keys()):
        local = local_open.get(sym)
        ex_row = ex_map.get(sym)
        if local and not ex_row:
            issues.append(f"{sym}: local OPEN, exchange flat")
        elif ex_row and not local:
            issues.append(f"{sym}: exchange OPEN, local flat")
        elif local and ex_row:
            ex_size = _coerce_float(ex_row.get("size"))
            local_side = str(local.get("side") or "").lower()
            ex_side = _side_from_signed_size(ex_size)
            if local_side and ex_side and local_side != ex_side:
                issues.append(f"{sym}: side mismatch local={local_side} exchange={ex_side}")
            local_lots = _coerce_float(local.get("lots") or local.get("quantity"))
            if local_lots > 0 and abs(abs(ex_size) - local_lots) > max(0.01, local_lots * 0.05):
                issues.append(
                    f"{sym}: size mismatch local_lots={local_lots} exchange_size={ex_size}"
                )
    return issues


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


def _compute_duration_seconds(entry_time: Any, exit_time: datetime) -> int:
    entry_dt = _parse_exchange_timestamp(entry_time)
    if entry_dt is None:
        return 0
    try:
        return max(0, int((exit_time - entry_dt).total_seconds()))
    except (TypeError, ValueError):
        return 0


def _infer_bracket_exit_reason(pos: Dict[str, Any], exit_price: float) -> str:
    """Guess SL vs TP when exchange bracket closed the leg."""
    sl = pos.get("stop_loss")
    tp = pos.get("take_profit")
    side = str(pos.get("side") or "").lower()
    if exit_price <= 0:
        return "exchange_bracket_exit"
    tol = max(exit_price * 0.001, 1.0)

    if sl is not None:
        sl_f = float(sl)
        if side == "long" and exit_price <= sl_f + tol:
            return "stop_loss_hit"
        if side == "short" and exit_price >= sl_f - tol:
            return "stop_loss_hit"

    if tp is not None:
        tp_f = float(tp)
        if side == "long" and exit_price >= tp_f - tol:
            return "take_profit_hit"
        if side == "short" and exit_price <= tp_f + tol:
            return "take_profit_hit"

    return "exchange_bracket_exit"


def _estimate_pnl_usd(pos: Dict[str, Any], entry_px: float, exit_px: float) -> tuple[float, float, float]:
    """Return (gross_pnl_usd, fees_usd, net_pnl_usd) using configured fee model."""
    lots = _coerce_float(pos.get("lots") or pos.get("quantity"))
    side = str(pos.get("side") or "long")
    cv = _coerce_float(
        pos.get("contract_value_btc") or getattr(settings, "contract_value_btc", 0.001),
        0.001,
    )
    taker = float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005)
    slip_bps = float(getattr(settings, "slippage_bps", 5.0) or 5.0)
    if entry_px <= 0 or exit_px <= 0 or lots <= 0:
        return 0.0, 0.0, 0.0
    try:
        from agent.core.futures_utils import net_pnl_usd_after_fees

        gross, fees, net = net_pnl_usd_after_fees(
            entry_px, exit_px, lots, side, cv, taker, slip_bps
        )
        return float(gross), float(fees), float(net)
    except Exception:
        return 0.0, 0.0, 0.0


def _fill_timestamp_seconds(row: Dict[str, Any]) -> float:
    created = row.get("created_at")
    if isinstance(created, (int, float)):
        ts = float(created)
        if ts > 1e12:
            ts /= 1_000_000.0
        return ts
    parsed = _parse_exchange_timestamp(created)
    if parsed is not None:
        return parsed.timestamp()
    return 0.0


def _fill_is_closing_leg(row: Dict[str, Any], pos: Dict[str, Any]) -> bool:
    """True when fill likely closes the given position (reduce-only or opposite side)."""
    meta = row.get("meta_data")
    if isinstance(meta, dict):
        ro = meta.get("reduce_only")
        if ro is True or str(ro).lower() in {"true", "1"}:
            return True
        ot = str(meta.get("order_type") or "").lower()
        if ot and any(token in ot for token in ("stop", "take", "close", "liquidation")):
            return True

    pos_side = str(pos.get("side") or "").lower()
    fill_side = str(row.get("side") or "").lower()
    if pos_side == "long" and fill_side in {"sell", "short"}:
        return True
    if pos_side == "short" and fill_side in {"buy", "long"}:
        return True
    return False


def _apply_fill_metadata_to_payload(payload: Dict[str, Any], fill_row: Dict[str, Any]) -> None:
    fill_px = _coerce_float(fill_row.get("price"))
    if fill_px > 0:
        payload["exit_price"] = fill_px
    fill_id = fill_row.get("id")
    if fill_id is not None:
        payload["fill_id"] = str(fill_id)
    commission = fill_row.get("commission")
    if commission is not None:
        try:
            payload["commission_usd"] = float(commission)
            payload["fees_usd"] = abs(float(commission))
        except (TypeError, ValueError):
            pass
    order_id = fill_row.get("order_id")
    if order_id is not None and not payload.get("exchange_order_id"):
        payload["exchange_order_id"] = str(order_id)

    meta = fill_row.get("meta_data")
    if isinstance(meta, dict):
        ot = str(meta.get("order_type") or "").lower()
        if "stop" in ot and payload.get("exit_reason") == "exchange_bracket_exit":
            payload["exit_reason"] = "stop_loss_hit"
        elif "take" in ot or "profit" in ot:
            if payload.get("exit_reason") == "exchange_bracket_exit":
                payload["exit_reason"] = "take_profit_hit"


async def _fetch_recent_fills(
    execution_module: Any,
    symbol: str,
    *,
    page_size: int = 20,
    start_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    client = getattr(execution_module, "delta_client", None)
    if client is None:
        return []
    try:
        product_id = await client.resolve_product_id(symbol)
        fills_resp = await client.get_fills(
            product_ids=str(product_id),
            page_size=page_size,
            start_time=start_time,
            contract_types="perpetual_futures",
        )
    except Exception as exc:
        logger.debug("reconcile_fill_fetch_skipped", symbol=symbol, error=str(exc))
        return []

    rows = fills_resp.get("result") if isinstance(fills_resp, dict) else None
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


async def _resolve_exit_from_closing_fill(
    execution_module: Any,
    symbol: str,
    pos: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve exit price from the most recent closing fill on the exchange."""
    sym_u = str(symbol or "").strip().upper()
    if not sym_u:
        return None

    entry_time = pos.get("entry_time") or pos.get("opened_at")
    entry_dt = _parse_exchange_timestamp(entry_time)
    start_time: Optional[int] = None
    if entry_dt is not None:
        start_time = int(entry_dt.timestamp())

    rows = await _fetch_recent_fills(
        execution_module,
        sym_u,
        page_size=50,
        start_time=start_time,
    )
    if not rows:
        return None

    closing_candidates: List[tuple[float, Dict[str, Any]]] = []
    fallback_candidates: List[tuple[float, Dict[str, Any]]] = []
    for row in rows:
        ps = str(row.get("product_symbol") or row.get("symbol") or "").upper()
        if ps and ps != sym_u:
            continue
        ts = _fill_timestamp_seconds(row)
        fill_px = _coerce_float(row.get("price"))
        if fill_px <= 0:
            continue
        if _fill_is_closing_leg(row, pos):
            closing_candidates.append((ts, row))
        else:
            fallback_candidates.append((ts, row))

    chosen: Optional[Dict[str, Any]] = None
    if closing_candidates:
        chosen = max(closing_candidates, key=lambda item: item[0])[1]
    elif fallback_candidates:
        chosen = max(fallback_candidates, key=lambda item: item[0])[1]

    if not chosen:
        return None

    exit_px = _coerce_float(chosen.get("price"))
    if exit_px <= 0:
        return None

    return {
        "exit_price": exit_px,
        "fill_row": chosen,
        "source": "closing_fill" if closing_candidates else "latest_fill",
    }


async def _enrich_payload_from_fills(
    execution_module: Any,
    symbol: str,
    payload: Dict[str, Any],
    *,
    pos: Optional[Dict[str, Any]] = None,
    skip_if_resolved: bool = False,
) -> None:
    """Best-effort fill metadata; prefers closing fills over arbitrary latest fill."""
    if skip_if_resolved and payload.get("exit_price_resolved_from_fill"):
        return

    sym_u = symbol.upper()
    pos_ctx = pos or {"side": payload.get("side")}

    resolved = await _resolve_exit_from_closing_fill(execution_module, sym_u, pos_ctx)
    if resolved:
        _apply_fill_metadata_to_payload(payload, resolved["fill_row"])
        payload["exit_price_resolved_from_fill"] = True
        return

    rows = await _fetch_recent_fills(execution_module, sym_u, page_size=20)
    if not rows:
        return

    latest: Optional[Dict[str, Any]] = None
    latest_ts = 0.0
    for row in rows:
        ps = str(row.get("product_symbol") or row.get("symbol") or "").upper()
        if ps and ps != sym_u:
            continue
        ts = _fill_timestamp_seconds(row)
        if ts >= latest_ts:
            latest_ts = ts
            latest = row

    if latest:
        _apply_fill_metadata_to_payload(payload, latest)


def _build_position_closed_payload(
    sym: str,
    pos: Dict[str, Any],
    *,
    exit_price: float,
    exit_reason: str,
    closed_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry_px = float(pos.get("entry_price") or 0)
    exit_px = exit_price if exit_price > 0 else float(pos.get("current_price") or entry_px)
    if exit_px <= 0:
        exit_px = entry_px
    exit_time = datetime.now(timezone.utc)
    entry_time = pos.get("entry_time") or pos.get("opened_at")
    gross, fees, net = _estimate_pnl_usd(pos, entry_px, exit_px)

    pos_id = f"pos_reconcile_{sym}"
    if closed_record and isinstance(closed_record, dict):
        eid = closed_record.get("entry_order_id") or closed_record.get("exit_order_id")
        if eid:
            pos_id = f"pos_{eid}"

    payload: Dict[str, Any] = {
        "position_id": pos_id,
        "symbol": sym,
        "side": pos.get("side", ""),
        "entry_price": entry_px,
        "exit_price": exit_px,
        "quantity": float(pos.get("lots") or pos.get("quantity") or 0),
        "pnl": net,
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "pnl_usd": net,
        "exit_reason": exit_reason,
        "timestamp": exit_time,
        "duration_seconds": float(_compute_duration_seconds(entry_time, exit_time)),
    }
    if entry_time is not None:
        payload["entry_time"] = entry_time

    if closed_record and isinstance(closed_record, dict):
        order_id = closed_record.get("entry_order_id") or closed_record.get("exit_order_id")
        if order_id:
            payload["exchange_order_id"] = str(order_id)

    for key in (
        "reasoning_chain_id",
        "model_predictions",
        "predicted_signal",
        "memory_context_id",
        "agent_introspection_at_entry",
        "confidence_at_entry",
    ):
        if pos.get(key) is not None:
            payload[key] = pos.get(key)

    return payload


async def emit_position_closed_from_exchange_flat(
    execution_module: Any,
    symbol: str,
    pos: Dict[str, Any],
    *,
    exit_price: Optional[float] = None,
    exit_reason: str = "reconcile_exchange_flat",
    closed_record: Optional[Dict[str, Any]] = None,
    source: str = "position_reconcile",
    skip_fill_enrichment: bool = False,
) -> bool:
    """Publish PositionClosedEvent after exchange bracket / reconcile detected a flat leg."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return False

    exit_px = float(exit_price) if exit_price is not None else 0.0
    if exit_px <= 0:
        exit_px = float(pos.get("current_price") or pos.get("entry_price") or 0)

    payload = _build_position_closed_payload(
        sym,
        pos,
        exit_price=exit_px,
        exit_reason=exit_reason,
        closed_record=closed_record,
    )
    await _enrich_payload_from_fills(
        execution_module,
        sym,
        payload,
        pos=pos,
        skip_if_resolved=skip_fill_enrichment,
    )

    try:
        from agent.core.agent_self_awareness_hooks import enrich_position_closed_payload

        await enrich_position_closed_payload(payload)
    except Exception as exc:
        logger.debug(
            "position_reconcile_self_awareness_hooks_skipped",
            symbol=sym,
            error=str(exc),
        )

    try:
        ev = PositionClosedEvent(source=source, payload=payload)
        await event_bus.publish(ev)
        logger.info(
            "position_closed_event_published",
            symbol=sym,
            exit_reason=exit_reason,
            source=source,
            position_id=payload.get("position_id"),
        )
        return True
    except Exception as exc:
        logger.warning(
            "position_reconcile_position_closed_event_failed",
            symbol=sym,
            error=str(exc),
        )
        return False


async def is_exchange_position_flat(execution_module: Any, symbol: str) -> bool:
    """True when Delta margined positions show no open size for symbol."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return False
    try:
        view = await execution_module.get_margined_positions_view()
    except Exception:
        return False
    rows = parse_margined_rows(view)
    ex_map = exchange_open_symbols(rows)
    return sym not in ex_map


async def notify_exchange_flat_position_closed(
    execution_module: Any,
    symbol: str,
    pos: Dict[str, Any],
    *,
    exit_reason: Optional[str] = None,
    close_local_if_open: bool = True,
    source: str = "position_reconcile",
) -> bool:
    """Close local OPEN row (optional) and publish PositionClosedEvent."""
    sym = str(symbol or "").strip().upper()
    pm = execution_module.position_manager
    current = pm.get_position(sym) or pos
    entry_px = float(current.get("entry_price") or 0)

    resolved = await _resolve_exit_from_closing_fill(execution_module, sym, current)
    exit_from_fill = False
    if resolved:
        exit_px = float(resolved["exit_price"])
        exit_from_fill = True
    else:
        exit_px = float(current.get("current_price") or entry_px)
        if exit_px <= 0:
            exit_px = entry_px

    reason = exit_reason or _infer_bracket_exit_reason(current, exit_px)

    closed_record: Optional[Dict[str, Any]] = None
    if close_local_if_open:
        live = pm.get_position(sym)
        if live and str(live.get("status") or "").lower() == "open":
            closed_record = pm.close_position(
                symbol=sym,
                exit_price=exit_px,
                exit_order_id="exchange_flat_detected",
            )
        elif live:
            closed_record = live

    return await emit_position_closed_from_exchange_flat(
        execution_module,
        sym,
        current,
        exit_price=exit_px,
        exit_reason=reason,
        closed_record=closed_record,
        source=source,
        skip_fill_enrichment=exit_from_fill,
    )


async def maybe_handle_exchange_bracket_flat_exit(
    execution_module: Any,
    symbol: str,
    position: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """If exchange bracket closed the leg, sync local state and notify backend/UI."""
    if not bool(getattr(settings, "bracket_exit_poll_enabled", True)):
        return None

    sym = str(symbol or "").strip().upper()
    if not sym:
        return None

    if not await is_exchange_position_flat(execution_module, sym):
        return None

    exit_px = float(position.get("current_price") or position.get("entry_price") or 0)
    reason = _infer_bracket_exit_reason(position, exit_px)

    published = await notify_exchange_flat_position_closed(
        execution_module,
        sym,
        position,
        exit_reason=reason,
        close_local_if_open=True,
        source="execution_bracket_poll",
    )
    if not published:
        return None

    return {
        "action": "exchange_bracket_closed",
        "symbol": sym,
        "exit_reason": reason,
        "position_status": "closed",
    }


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
        _set_reconcile_health(True)
        return summary

    try:
        view = await execution_module.get_margined_positions_view()
    except Exception as exc:
        from agent.data.delta_client import CircuitBreakerOpenError

        is_cb = isinstance(exc, CircuitBreakerOpenError)
        logger.warning(
            "position_reconcile_fetch_failed",
            error=str(exc),
            circuit_breaker_open=is_cb,
            recovery_hint=(
                "Delta circuit breaker will retry after timeout; "
                "check API keys, testnet reachability, and rate limits"
                if is_cb
                else None
            ),
        )
        summary["skipped"].append("fetch_failed")
        if bool(getattr(settings, "block_entries_on_reconcile_divergence", True)):
            _set_reconcile_health(
                False,
                reason=f"Exchange position fetch failed: {exc}",
            )
        return summary

    rows = parse_margined_rows(view)
    pre_divergence = detect_position_divergence(execution_module, rows)
    if pre_divergence:
        logger.warning("position_reconcile_pre_divergence", issues=pre_divergence)
        summary["pre_divergence"] = pre_divergence
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
        reason = _infer_bracket_exit_reason(pos, exit_px)
        if reason == "exchange_bracket_exit":
            reason = "reconcile_exchange_flat"

        published = await notify_exchange_flat_position_closed(
            execution_module,
            sym,
            pos,
            exit_reason=reason,
            close_local_if_open=True,
            source="position_reconcile",
        )
        summary["cleared_local"].append(sym)
        if not published:
            summary.setdefault("event_publish_failed", []).append(sym)

    if summary["adopted"] or summary["closed_exchange"] or summary["cleared_local"]:
        logger.info("position_reconcile_complete", **summary)

    post_divergence = detect_position_divergence(execution_module, rows)
    summary["post_divergence"] = post_divergence
    if post_divergence and bool(getattr(settings, "block_entries_on_reconcile_divergence", True)):
        _set_reconcile_health(
            False,
            reason="; ".join(post_divergence[:5]),
            divergence=post_divergence,
        )
        logger.error("position_reconcile_unresolved_divergence", issues=post_divergence)
    else:
        _set_reconcile_health(True)

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
