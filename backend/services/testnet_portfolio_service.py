"""
Testnet portfolio service — maps Delta exchange snapshots to API response shapes.

Portfolio balances and open positions are sourced from the agent's exchange gateway
(Delta India testnet private APIs), not from INITIAL_BALANCE + local DB ledger math.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.redis import get_cache, set_cache
from backend.services.agent_service import agent_service
from backend.services.fx_rate_service import get_usdinr_rate
from backend.services.time_service import time_service

logger = structlog.get_logger()

_CACHE_KEY = "portfolio:testnet:summary"
_CACHE_TTL_SECONDS = 5
_CONNECTIVITY_CACHE_KEY = "testnet:exchange:connected"


class TestnetExchangeUnavailableError(Exception):
    """Delta testnet private API is unreachable; trading must halt."""

    def __init__(self, message: str = "Delta testnet connection is down"):
        self.message = message
        super().__init__(message)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_result_list(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        return [result]
    return []


def _wallet_totals_usd(wallet_payload: Any) -> Dict[str, float]:
    """Sum USD/USDT wallet rows into balance and available USD."""
    rows = _extract_result_list(wallet_payload)
    balance_usd = 0.0
    available_usd = 0.0
    for row in rows:
        sym = str(row.get("asset_symbol") or row.get("symbol") or "").upper()
        if sym not in ("USD", "USDT", "USDC"):
            continue
        balance_usd += _coerce_float(row.get("balance") or row.get("total_balance"))
        available_usd += _coerce_float(
            row.get("available_balance") or row.get("available") or row.get("balance")
        )
    return {"balance_usd": balance_usd, "available_usd": available_usd}


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


def _map_margined_position(row: Dict[str, Any], cv: float) -> Dict[str, Any]:
    symbol = str(row.get("product_symbol") or row.get("symbol") or "UNKNOWN")
    signed_size = _coerce_float(row.get("size"))
    lots = abs(int(signed_size)) if signed_size else 0
    side = "LONG" if signed_size >= 0 else "SHORT"
    entry_price = _coerce_float(row.get("entry_price"))
    mark_price = _coerce_float(row.get("mark_price") or row.get("index_price") or entry_price)
    margin_usd = _coerce_float(row.get("margin"))
    unrealized = _coerce_float(row.get("unrealized_pnl") or row.get("unrealized_funding_pnl"))
    exchange_id = row.get("id") or row.get("position_id")
    position_id = f"ex_{exchange_id}" if exchange_id is not None else f"ex_{symbol}_{lots}"
    opened_at = (
        _parse_exchange_timestamp(row.get("created_at"))
        or _parse_exchange_timestamp(row.get("updated_at"))
        or datetime.now(timezone.utc)
    )

    return {
        "position_id": str(position_id),
        "exchange_position_id": str(exchange_id) if exchange_id is not None else None,
        "product_id": row.get("product_id"),
        "symbol": symbol,
        "side": side,
        "quantity": lots,
        "lots": lots,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "current_price": mark_price,
        "liquidation_price": _coerce_float(row.get("liquidation_price")) or None,
        "liquidation_price_usd": _coerce_float(row.get("liquidation_price")) or None,
        "unrealized_pnl": unrealized,
        "leverage": int(_coerce_float(row.get("leverage"), 0)) or None,
        "notional_usd": entry_price * lots * cv if lots and entry_price else None,
        "margin_used_position_usd": margin_usd,
        "status": "OPEN",
        "opened_at": opened_at,
        "stop_loss": None,
        "take_profit": None,
    }


def _parse_order_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _map_order_history_row(row: Dict[str, Any], usdinr: Decimal) -> Dict[str, Any]:
    from backend.services.portfolio_service import PortfolioService

    order_id = row.get("id") or row.get("order_id")
    symbol = str(row.get("product_symbol") or row.get("symbol") or "BTCUSD")
    side_raw = str(row.get("side") or "buy").upper()
    side = "BUY" if side_raw.startswith("B") else "SELL"
    size = _coerce_float(row.get("size") or row.get("filled_size") or row.get("unfilled_size"))
    price = _coerce_float(
        row.get("average_fill_price")
        or row.get("avg_fill_price")
        or row.get("limit_price")
        or row.get("price")
    )
    entry_time = (
        _parse_order_timestamp(row.get("created_at"))
        or _parse_order_timestamp(row.get("updated_at"))
        or datetime.now(timezone.utc)
    )
    exit_time = (
        _parse_order_timestamp(row.get("updated_at"))
        or _parse_order_timestamp(row.get("created_at"))
        or entry_time
    )
    duration_seconds = PortfolioService._compute_duration_seconds(entry_time, exit_time)

    pnl_usd = _coerce_float(row.get("realized_pnl") or row.get("pnl"))
    return {
        "trade_id": f"order_{order_id}" if order_id is not None else f"order_{symbol}_{int(exit_time.timestamp())}",
        "position_id": str(order_id) if order_id is not None else "",
        "exchange_order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol,
        "side": side,
        "quantity": size,
        "entry_price": price,
        "exit_price": price,
        "pnl": float(Decimal(str(pnl_usd)) * usdinr),
        "pnl_usd": pnl_usd,
        "status": "CLOSED",
        "entry_time": entry_time,
        "exit_time": exit_time,
        "duration_seconds": duration_seconds,
        "executed_at": exit_time,
    }


class TestnetPortfolioService:
    """Build portfolio API payloads from Delta testnet exchange snapshots."""

    def __init__(self) -> None:
        self._contract_value_btc = float(getattr(settings, "contract_value_btc", 0.001))
        self._last_unavailable_log_at: float = 0.0

    def _log_exchange_unavailable(self, agent_error: Optional[str] = None) -> None:
        """Rate-limit repeated unavailable logs when private Delta API is down."""
        import time

        now = time.time()
        if (now - self._last_unavailable_log_at) < 120.0:
            return
        self._last_unavailable_log_at = now
        extra: Dict[str, Any] = {}
        if agent_error and "ip whitelist" in agent_error.lower():
            extra["hint"] = (
                "Whitelist the client IP shown in agent logs on your Delta API key settings."
            )
            extra["agent_error"] = agent_error
        logger.error(
            "testnet_exchange_unavailable",
            message="Delta testnet snapshot unavailable; trading halted",
            **extra,
        )

    async def fetch_exchange_snapshot(self, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        symbol = symbol or str(getattr(settings, "trading_symbol", "BTCUSD") or "BTCUSD")
        snapshot = await agent_service.get_exchange_portfolio(symbol=symbol)
        if not snapshot or not isinstance(snapshot, dict):
            await set_cache(_CONNECTIVITY_CACHE_KEY, {"connected": False}, ttl=10)
            return None
        if snapshot.get("success") is False:
            await set_cache(_CONNECTIVITY_CACHE_KEY, {"connected": False}, ttl=10)
            return None
        await set_cache(_CONNECTIVITY_CACHE_KEY, {"connected": True}, ttl=10)
        return snapshot

    async def is_exchange_available(self, symbol: Optional[str] = None) -> bool:
        cached = await get_cache(_CONNECTIVITY_CACHE_KEY)
        if isinstance(cached, dict) and cached.get("connected") is True:
            return True
        snapshot = await self.fetch_exchange_snapshot(symbol=symbol)
        return snapshot is not None

    def build_summary_from_snapshot(
        self,
        snapshot: Dict[str, Any],
        *,
        sync_status: str = "live",
    ) -> Dict[str, Any]:
        cv = self._contract_value_btc
        margined_rows = _extract_result_list(snapshot.get("margined_positions"))
        open_rows = [r for r in margined_rows if abs(_coerce_float(r.get("size"))) > 0]

        positions_list = [_map_margined_position(r, cv) for r in open_rows]
        total_unrealized_usd = sum(_coerce_float(p.get("unrealized_pnl")) for p in positions_list)
        margin_used_usd = sum(
            _coerce_float(p.get("margin_used_position_usd")) for p in positions_list
        )

        wallet = _wallet_totals_usd(snapshot.get("wallet_balances"))
        balance_usd = wallet["balance_usd"]
        available_usd = wallet["available_usd"]

        if balance_usd <= 0 and margin_used_usd > 0:
            balance_usd = available_usd + margin_used_usd + total_unrealized_usd
        if available_usd <= 0 and balance_usd > 0:
            available_usd = max(0.0, balance_usd - margin_used_usd)

        return {
            "total_value_usd": balance_usd,
            "available_usd": available_usd,
            "margin_used_usd": margin_used_usd,
            "total_unrealized_usd": total_unrealized_usd,
            "positions_list": positions_list,
            "sync_status": sync_status,
            "order_history": snapshot.get("order_history"),
        }

    async def _finalize_summary_inr(self, partial: Dict[str, Any]) -> Dict[str, Any]:
        usdinr_rate = Decimal(str(await get_usdinr_rate()))
        total_usd = Decimal(str(partial.get("total_value_usd", 0)))
        available_usd = Decimal(str(partial.get("available_usd", 0)))
        margin_usd = Decimal(str(partial.get("margin_used_usd", 0)))
        unrealized_usd = Decimal(str(partial.get("total_unrealized_usd", 0)))

        total_inr = total_usd * usdinr_rate
        available_inr = available_usd * usdinr_rate
        margin_inr = margin_usd * usdinr_rate
        unrealized_inr = unrealized_usd * usdinr_rate

        positions_list = partial.get("positions_list") or []
        for pos in positions_list:
            u = Decimal(str(pos.get("unrealized_pnl") or 0))
            pos["unrealized_pnl"] = float(u * usdinr_rate)
            pos["unrealized_pnl_usd"] = float(u)
            pos["unrealized_pnl_inr"] = float(u * usdinr_rate)
            ep = Decimal(str(pos.get("entry_price") or 0))
            mp = Decimal(str(pos.get("mark_price") or ep))
            pos["entry_price_usd"] = float(ep)
            pos["current_price_usd"] = float(mp)
            pos["entry_price"] = float(ep * usdinr_rate)
            pos["current_price"] = float(mp * usdinr_rate)
            pos["mark_price"] = float(mp * usdinr_rate)

        synced_at = time_service.get_time_info()["server_time"]
        return {
            "total_value": float(total_inr),
            "available_balance": float(available_inr),
            "margin_used": float(margin_inr),
            "usd_inr_rate": float(usdinr_rate),
            "open_positions": len(positions_list),
            "total_unrealized_pnl": float(unrealized_inr),
            "total_realized_pnl": 0.0,
            "positions": positions_list,
            "data_source": "delta_testnet",
            "sync_status": partial.get("sync_status", "live"),
            "exchange_synced_at": synced_at,
            "contract_value_btc": self._contract_value_btc,
            "timestamp": synced_at,
        }

    async def get_portfolio_summary(self, db: AsyncSession) -> Optional[Dict[str, Any]]:
        _ = db  # testnet portfolio is exchange-only; no local DB ledger
        cached = await get_cache(_CACHE_KEY)
        if cached and isinstance(cached, dict) and cached.get("sync_status") == "live":
            return cached

        snapshot = await self.fetch_exchange_snapshot()
        if not snapshot:
            self._log_exchange_unavailable()
            raise TestnetExchangeUnavailableError()

        try:
            partial = self.build_summary_from_snapshot(snapshot, sync_status="live")
            summary = await self._finalize_summary_inr(partial)
            await set_cache(_CACHE_KEY, summary, ttl=_CACHE_TTL_SECONDS)
            return summary
        except TestnetExchangeUnavailableError:
            raise
        except Exception as exc:
            logger.error(
                "testnet_portfolio_build_failed",
                error=str(exc),
                exc_info=True,
            )
            raise TestnetExchangeUnavailableError(
                "Delta testnet connection is down (portfolio mapping failed)"
            ) from exc

    async def list_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        snapshot = await self.fetch_exchange_snapshot(symbol=symbol)
        if not snapshot:
            raise TestnetExchangeUnavailableError()
        partial = self.build_summary_from_snapshot(snapshot, sync_status="live")
        positions = partial.get("positions_list") or []
        if symbol:
            sym = symbol.upper()
            positions = [p for p in positions if str(p.get("symbol", "")).upper() == sym]
        return positions

    async def get_recent_closed_trades_from_exchange(
        self,
        *,
        symbol: Optional[str] = None,
        limit: int = 50,
        db: Optional[AsyncSession] = None,
    ) -> List[Dict[str, Any]]:
        _ = db
        snapshot = await self.fetch_exchange_snapshot(symbol=symbol)
        if not snapshot:
            raise TestnetExchangeUnavailableError()

        usdinr_rate = Decimal(str(await get_usdinr_rate()))
        history = snapshot.get("order_history") or {}
        rows = _extract_result_list(history)
        closed_states = {"closed", "filled"}
        mapped: List[Dict[str, Any]] = []
        for row in rows:
            state = str(row.get("state") or row.get("status") or "").lower()
            if state and state not in closed_states:
                continue
            mapped.append(_map_order_history_row(row, usdinr_rate))
        mapped.sort(
            key=lambda r: r.get("exit_time") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return mapped[:limit]


testnet_portfolio_service = TestnetPortfolioService()
