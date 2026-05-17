"""
Agent-executed closed trades ledger for performance monitoring.

Stores round-trip trades closed by Jack Sparrow (PositionClosedEvent), not all
Delta account order history. Redis list with JSONL file fallback when Redis is down.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from backend.services.fx_rate_service import get_usdinr_rate
from backend.services.portfolio_service import PortfolioService

logger = structlog.get_logger()

_REDIS_LIST_KEY = "agent:closed_trades"
_MAX_ROWS = 500
_LEDGER_FILE = Path(__file__).resolve().parents[2] / "data" / "agent_closed_trades.jsonl"

AGENT_CLIENT_ORDER_PREFIX = "js_"


def _normalize_side(side: Any) -> str:
    raw = str(side or "").strip().lower()
    if raw in ("long", "buy"):
        return "LONG"
    if raw in ("short", "sell"):
        return "SHORT"
    return str(side or "").upper()


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


async def build_closed_trade_from_position_event(
    payload: Dict[str, Any],
    *,
    usdinr_rate: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """Map PositionClosedEvent payload to ClosedTradeResponse-shaped dict."""
    position_id = str(payload.get("position_id") or "")
    symbol = str(payload.get("symbol") or "BTCUSD")
    side = _normalize_side(payload.get("side"))
    quantity = float(payload.get("quantity") or 0)
    entry_price = float(payload.get("entry_price") or 0)
    exit_price = float(payload.get("exit_price") or 0)
    pnl_usd = float(payload.get("pnl") or payload.get("net_pnl_usd") or 0)
    exit_time = _parse_ts(payload.get("timestamp"))
    entry_time = _parse_ts(payload.get("entry_time") or exit_time)

    rate = usdinr_rate if usdinr_rate is not None else Decimal(str(await get_usdinr_rate()))
    fx_pnl_inr = float(payload.get("fx_pnl_inr") or 0)
    pnl_inr = float(Decimal(str(pnl_usd)) * rate) + fx_pnl_inr

    trade_id = f"agent_{position_id}" if position_id else f"agent_{symbol}_{int(exit_time.timestamp())}"

    row: Dict[str, Any] = {
        "trade_id": trade_id,
        "position_id": position_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl_inr,
        "pnl_usd": pnl_usd,
        "status": "CLOSED",
        "entry_time": entry_time,
        "exit_time": exit_time,
        "duration_seconds": PortfolioService._compute_duration_seconds(entry_time, exit_time),
        "executed_at": exit_time,
        "data_source": "agent",
        "exit_reason": payload.get("exit_reason"),
        "gross_pnl_usd": payload.get("gross_pnl_usd"),
        "fees_usd": payload.get("fees_usd"),
        "reasoning_chain_id": payload.get("reasoning_chain_id"),
        "exchange_order_id": payload.get("exchange_order_id"),
    }
    return row


def _append_file(row: Dict[str, Any]) -> None:
    _LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LEDGER_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def _read_file(*, limit: int, symbol: Optional[str]) -> List[Dict[str, Any]]:
    if not _LEDGER_FILE.is_file():
        return []
    lines = _LEDGER_FILE.read_text(encoding="utf-8").strip().splitlines()
    rows: List[Dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if symbol and str(row.get("symbol", "")).upper() != symbol.upper():
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


async def _redis_lpush_row(row: Dict[str, Any]) -> bool:
    from backend.core.redis import get_redis

    try:
        client = await get_redis()
        if client is None:
            return False
        raw = json.dumps(row, default=str)
        await client.lpush(_REDIS_LIST_KEY, raw)
        await client.ltrim(_REDIS_LIST_KEY, 0, _MAX_ROWS - 1)
        return True
    except Exception as exc:
        logger.warning("agent_trade_ledger_redis_push_failed", error=str(exc))
        return False


async def _redis_read_rows(*, limit: int, offset: int, symbol: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    from backend.core.redis import get_redis

    try:
        client = await get_redis()
        if client is None:
            return None
        end = offset + limit - 1
        raw_items = await client.lrange(_REDIS_LIST_KEY, offset, end)
        rows: List[Dict[str, Any]] = []
        for raw in raw_items:
            try:
                row = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if symbol and str(row.get("symbol", "")).upper() != symbol.upper():
                continue
            rows.append(row)
        return rows
    except Exception as exc:
        logger.warning("agent_trade_ledger_redis_read_failed", error=str(exc))
        return None


async def record_closed_trade(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist one agent closed round-trip for Recent Trades / performance."""
    row = await build_closed_trade_from_position_event(payload)
    redis_ok = await _redis_lpush_row(row)
    _append_file(row)
    logger.info(
        "agent_trade_ledger_recorded",
        trade_id=row.get("trade_id"),
        symbol=row.get("symbol"),
        pnl_usd=row.get("pnl_usd"),
        redis=redis_ok,
    )
    return row


async def get_agent_closed_trades(
    *,
    symbol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return recent agent-executed closed trades (newest first)."""
    limit = max(1, min(limit, _MAX_ROWS))
    redis_rows = await _redis_read_rows(limit=limit + offset, offset=0, symbol=symbol)
    if redis_rows is not None and len(redis_rows) > 0:
        return redis_rows[offset : offset + limit]
    file_rows = _read_file(limit=limit + offset, symbol=symbol)
    return file_rows[offset : offset + limit]


async def clear_agent_trade_ledger() -> None:
    """Remove all agent closed-trade history."""
    from backend.core.redis import delete_cache, get_redis

    try:
        client = await get_redis()
        if client is not None:
            await client.delete(_REDIS_LIST_KEY)
    except Exception:
        pass
    await delete_cache(_REDIS_LIST_KEY)
    if _LEDGER_FILE.is_file():
        _LEDGER_FILE.unlink()


def is_agent_client_order_id(client_order_id: Optional[str]) -> bool:
    return bool(client_order_id) and str(client_order_id).startswith(AGENT_CLIENT_ORDER_PREFIX)
