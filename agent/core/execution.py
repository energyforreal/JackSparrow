"""
Execution Engine - Trade execution with order management.

Handles trade execution, order management, slippage control,
and integration with trading venues.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import math
import time
import uuid
import structlog

from agent.events.event_bus import event_bus
from agent.events.schemas import (
    RiskApprovedEvent,
    OrderFillEvent,
    PositionClosedEvent,
    PartialFillEvent,
    EventType,
)
from agent.core.config import settings
from agent.core.futures_utils import (
    net_pnl_usd_after_fees,
    net_pnl_usd_after_fees_split_legs,
    per_leg_cost_rate,
    entry_leg_fees_usd,
    isolated_equity_usd,
    round_to_tick,
)
from agent.core.sl_tp import (
    compute_stop_take_prices,
    parse_risk_approved_side,
    rebase_sl_tp_to_fill,
)
from agent.core.exchange_gateway import ExchangeGateway
from agent.core.agent_order_registry import (
    AGENT_DECISION_AUTHORITY,
    is_agent_controlled_authority,
    is_decision_already_executed,
    record_agent_order_fill,
    record_agent_order_intent,
    record_decision_execution,
)
from agent.core.ml_signal_guard import validate_ml_entry_signal

logger = structlog.get_logger()


class Order:
    """Represents a trading order."""

    def __init__(self, order_id: str, symbol: str, side: str, order_type: str,
                 quantity: float, price: Optional[float] = None,
                 stop_price: Optional[float] = None, time_in_force: str = "GTC",
                 exchange_order_id: Optional[int] = None):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side  # 'buy' or 'sell'
        self.order_type = order_type  # 'market', 'limit', 'stop', 'stop_limit'
        self.quantity = quantity
        self.price = price  # Limit price for limit orders
        self.exchange_order_id = exchange_order_id
        self.stop_price = stop_price  # Stop price for stop orders
        self.time_in_force = time_in_force  # 'GTC', 'IOC', 'FOK'
        self.status = "pending"  # 'pending', 'open', 'filled', 'cancelled', 'rejected'
        self.filled_quantity = 0.0
        self.average_fill_price = 0.0
        self.created_time = datetime.now(timezone.utc)
        self.updated_time = datetime.now(timezone.utc)
        self.fills: List[Dict[str, Any]] = []

    def is_complete(self) -> bool:
        """Check if order is completely filled."""
        return abs(self.filled_quantity - self.quantity) < 1e-8

    def remaining_quantity(self) -> float:
        """Get remaining quantity to fill."""
        return self.quantity - self.filled_quantity

    def update_fill(self, fill_quantity: float, fill_price: float, timestamp: Optional[datetime] = None):
        """Update order with a fill."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self.fills.append({
            "quantity": fill_quantity,
            "price": fill_price,
            "timestamp": timestamp
        })

        # Update filled quantity and average price
        total_value = self.average_fill_price * self.filled_quantity + fill_price * fill_quantity
        self.filled_quantity += fill_quantity
        self.average_fill_price = total_value / self.filled_quantity

        self.updated_time = timestamp

        if self.is_complete():
            self.status = "filled"
        else:
            self.status = "partially_filled"

    def cancel(self):
        """Cancel the order."""
        if self.status in ["pending", "open", "partially_filled"]:
            self.status = "cancelled"
            self.updated_time = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": self.average_fill_price,
            "created_time": self.created_time.isoformat(),
            "updated_time": self.updated_time.isoformat(),
            "fills": self.fills
        }


class PositionManager:
    """Manages trading positions."""

    def __init__(self):
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position details

    def open_position(self, symbol: str, side: str, quantity: float,
                     entry_price: float, order_id: str,
                     stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None,
                     position_extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Open a new position. Optionally store stop_loss and take_profit for monitoring."""
        contract_value_btc = float(getattr(settings, "contract_value_btc", 0.001))
        if position_extras and position_extras.get("contract_value_btc") is not None:
            try:
                contract_value_btc = float(position_extras["contract_value_btc"])
            except (TypeError, ValueError):
                pass

        position = {
            "symbol": symbol,
            "side": side,
            "lots": quantity,
            "contract_value_btc": contract_value_btc,
            "entry_price": entry_price,
            "entry_time": datetime.now(timezone.utc),
            "current_price": entry_price,
            "unrealized_pnl": 0.0,
            "entry_order_id": order_id,
            "exit_order_id": None,
            "status": "open",
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
        if position_extras:
            position.update(position_extras)
            if position_extras.get("paper_usdinr_entry") is not None:
                position["paper_usdinr_entry"] = float(position_extras["paper_usdinr_entry"])
            et_override = position_extras.get("entry_time")
            if et_override is not None:
                if isinstance(et_override, datetime):
                    position["entry_time"] = (
                        et_override.replace(tzinfo=timezone.utc)
                        if et_override.tzinfo is None
                        else et_override
                    )
                elif isinstance(et_override, str):
                    try:
                        position["entry_time"] = datetime.fromisoformat(
                            et_override.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
        # Ensure contract_value wins over extras keys if both present
        position["contract_value_btc"] = contract_value_btc

        self.positions[symbol] = position

        logger.info("position_opened",
                   symbol=symbol,
                   side=side,
                   quantity=quantity,
                   entry_price=entry_price)

        return position.copy()

    def update_position(self, symbol: str, current_price: float):
        """Update position with current price."""
        if symbol in self.positions:
            position = self.positions[symbol]
            position["current_price"] = current_price

            # Calculate unrealized P&L for perpetual futures using lot size
            contract_value_btc = position.get("contract_value_btc", float(getattr(settings, "contract_value_btc", 0.001)))
            entry_value = position["entry_price"] * position.get("lots", position.get("quantity", 0)) * contract_value_btc
            current_value = current_price * position.get("lots", position.get("quantity", 0)) * contract_value_btc

            if position["side"] == "long":
                position["unrealized_pnl"] = current_value - entry_value
            else:  # short
                position["unrealized_pnl"] = entry_value - current_value

            position["updated_time"] = datetime.now(timezone.utc)

    def close_position(self, symbol: str, exit_price: float,
                      exit_order_id: str) -> Optional[Dict[str, Any]]:
        """Close an existing position and remove it from the open map (ledger elsewhere)."""
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]
        if position.get("status") != "open":
            return None

        # Calculate realized P&L for perpetual futures using lot size
        contract_value_btc = position.get("contract_value_btc", float(getattr(settings, "contract_value_btc", 0.001)))
        lots = position.get("lots", position.get("quantity", 0))
        entry_value = position["entry_price"] * lots * contract_value_btc
        exit_value = exit_price * lots * contract_value_btc

        if position["side"] == "long":
            realized_pnl = exit_value - entry_value
        else:  # short
            realized_pnl = entry_value - exit_value

        # Update position snapshot, then drop from in-memory map so stale closed
        # rows cannot be mistaken for an open leg (execute_trade / monitors).
        position.update({
            "exit_price": exit_price,
            "exit_time": datetime.now(timezone.utc),
            "realized_pnl": realized_pnl,
            "exit_order_id": exit_order_id,
            "status": "closed"
        })

        closed_snapshot = position.copy()
        del self.positions[symbol]

        logger.info("position_closed",
                   symbol=symbol,
                   realized_pnl=realized_pnl,
                   exit_price=exit_price)

        return closed_snapshot

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get position details."""
        return self.positions.get(symbol)

    def get_all_positions(self) -> Dict[str, Any]:
        """Get all open positions."""
        return {symbol: pos for symbol, pos in self.positions.items()
                if pos["status"] == "open"}

    def get_position_summary(self) -> Dict[str, Any]:
        """Get positions summary."""
        open_positions = self.get_all_positions()

        total_exposure = sum(
            pos.get("entry_price", 0) * pos.get("lots", pos.get("quantity", 0)) * pos.get("contract_value_btc", float(getattr(settings, "contract_value_btc", 0.001)))
            for pos in open_positions.values()
        )
        total_unrealized_pnl = sum(pos.get("unrealized_pnl", 0) for pos in open_positions.values())

        return {
            "open_positions_count": len(open_positions),
            "total_exposure": total_exposure,
            "total_unrealized_pnl": total_unrealized_pnl,
            "positions": open_positions
        }


class ExecutionResult:
    """Result of a trade execution attempt."""

    def __init__(self, success: bool, order_id: Optional[str] = None,
                 error_message: Optional[str] = None):
        self.success = success
        self.order_id = order_id
        self.error_message = error_message
        self.execution_time = datetime.now(timezone.utc)
        self.details: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "order_id": self.order_id,
            "error_message": self.error_message,
            "execution_time": self.execution_time.isoformat(),
            "details": self.details
        }


class ExecutionEngine:
    """
    Trade execution engine with order management and slippage control.

    Handles order routing, position management, and execution monitoring.
    """

    def __init__(self):
        self.order_manager = OrderManager()
        self.position_manager = PositionManager()
        self.execution_config = {
            "max_slippage_percent": 0.5,  # Maximum allowed slippage
            "min_order_size": 0.001,      # Minimum order size
            "max_order_size": 1.0,        # Maximum order size as portfolio fraction
            "default_time_in_force": "GTC",
            "retry_attempts": 3,
            "retry_delay_seconds": 1.0
        }
        self._initialized = False
        self.delta_client = None  # Injected for paper/live trading
        self.risk_manager = None  # Injected for portfolio sync
        self.exchange_gateway: Optional[ExchangeGateway] = None

        # Mock exchange integration (would be replaced with real exchange API)
        self.exchange_connected = False
        self._position_lock = asyncio.Lock()
        self._inflight_lock = asyncio.Lock()
        self._inflight_symbols: set[str] = set()
        self._last_ws_sltp_check_ts: Dict[str, float] = {}
        self._partial_fill_tasks: Dict[str, asyncio.Task] = {}

    async def initialize(self, delta_client=None, risk_manager=None, exchange_gateway: Optional[ExchangeGateway] = None):
        """Initialize execution engine.

        Args:
            delta_client: Optional DeltaExchangeClient for paper/live trading
            risk_manager: Optional RiskManager for portfolio sync on fill/close
        """
        self.delta_client = delta_client
        self.risk_manager = risk_manager
        self.exchange_gateway = exchange_gateway
        # Initialize mock exchange connection
        await self._connect_exchange()
        self._initialized = True

        # Subscribe to RiskApprovedEvent for automatic trade execution
        event_bus.subscribe(EventType.RISK_APPROVED, self._handle_risk_approved)
        event_bus.subscribe(EventType.PARTIAL_FILL, self._handle_partial_fill)

        logger.info("execution_engine_initialized",
                   config=self.execution_config,
                   exchange_connected=self.exchange_connected,
                   trading_mode=settings.trading_mode,
                   delta_env=settings.delta_env,
                   exchange_gateway_class=(
                       self.exchange_gateway.__class__.__name__
                       if self.exchange_gateway is not None
                       else None
                   ))

    async def shutdown(self):
        """Shutdown execution engine."""
        await self._disconnect_exchange()
        self._initialized = False
        logger.info("execution_engine_shutdown")

    async def _connect_exchange(self):
        """Verify Delta testnet connectivity via wallet balances API."""
        try:
            if self.delta_client:
                await self.delta_client.get_wallet_balances()
                self.exchange_connected = True
                logger.info("exchange_connected", source="delta_wallet_ping")
            else:
                self.exchange_connected = False
                logger.warning("exchange_connection_skipped", reason="no_delta_client")
        except Exception as e:
            logger.error("exchange_connection_failed", error=str(e))
            self.exchange_connected = False

    async def _disconnect_exchange(self):
        """Disconnect from trading exchange."""
        self.exchange_connected = False
        logger.info("exchange_disconnected")

    async def _handle_partial_fill(self, event: PartialFillEvent) -> None:
        """Complete or close a partial fill after a short timeout."""
        payload = event.payload if isinstance(event.payload, dict) else {}
        symbol = str(payload.get("symbol") or "")
        order_id = str(payload.get("order_id") or "")
        if not symbol or not order_id:
            return
        if order_id in self._partial_fill_tasks and not self._partial_fill_tasks[order_id].done():
            return

        async def _resolve_partial() -> None:
            timeout_s = float(getattr(settings, "partial_fill_timeout_seconds", 10.0) or 10.0)
            await asyncio.sleep(timeout_s)
            requested = float(payload.get("requested_quantity") or 0.0)
            filled = float(payload.get("filled_quantity") or 0.0)
            remainder = max(0.0, requested - filled)
            if remainder <= 0:
                return
            side = str(payload.get("side") or "buy").lower()
            try:
                retry = await self._place_order(
                    symbol=symbol,
                    side=side,
                    quantity=remainder,
                    order_type="market",
                )
                if retry.get("success") and (
                    retry.get("filled_immediately") or float(retry.get("filled_quantity") or 0) > 0
                ):
                    add_qty = float(retry.get("filled_quantity") or remainder)
                    pos = self.position_manager.get_position(symbol)
                    if pos and str(pos.get("status") or "").lower() == "open":
                        pos["quantity"] = float(pos.get("quantity") or 0) + add_qty
                        self.position_manager.update_position(symbol, pos.get("current_price"))
                    logger.info(
                        "partial_fill_completed",
                        symbol=symbol,
                        order_id=order_id,
                        added_quantity=add_qty,
                    )
                    return
            except Exception as exc:
                logger.warning(
                    "partial_fill_retry_failed",
                    symbol=symbol,
                    order_id=order_id,
                    error=str(exc),
                )
            await self.close_position(symbol, exit_reason="partial_fill_timeout")

        self._partial_fill_tasks[order_id] = asyncio.create_task(_resolve_partial())

    async def _handle_risk_approved(self, event: RiskApprovedEvent):
        """Handle RiskApprovedEvent - execute trade and publish OrderFillEvent on success.

        Args:
            event: RiskApprovedEvent with symbol, side, quantity, price
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            side_upper = parse_risk_approved_side(payload.get("side", "BUY"))
            if side_upper is None:
                logger.warning(
                    "execution_risk_approved_invalid_side",
                    raw_side=payload.get("side"),
                    event_id=event.event_id,
                )
                logger.warning(
                    "trading_execution_rejected",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=payload.get("side"),
                    stage="invalid_side",
                    reason="side_must_be_buy_or_sell",
                    trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                )
                return
            side_raw = side_upper
            quantity = payload.get("quantity", 0)
            price = payload.get("price", 0)

            if not symbol or quantity <= 0:
                logger.warning(
                    "execution_risk_approved_invalid_payload",
                    symbol=symbol,
                    quantity=quantity,
                    event_id=event.event_id,
                )
                logger.warning(
                    "trading_execution_rejected",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=side_raw,
                    stage="invalid_payload",
                    reason="missing_symbol_or_nonpositive_quantity",
                    trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                )
                return

            # Enforce one open position per symbol (same as _validate_trade / execute_trade).
            # Sequential paper trades are still allowed after the prior position is closed.
            existing = self.position_manager.get_position(symbol)
            if existing and existing.get("status") == "open":
                logger.info(
                    "execution_risk_approved_overlap_rejected",
                    symbol=symbol,
                    side=side_raw,
                    existing_side=existing.get("side"),
                    event_id=event.event_id,
                    message="Open position exists for symbol; rejecting overlapping entry",
                )
                logger.warning(
                    "trading_execution_rejected",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=side_raw,
                    stage="overlap_open_position",
                    reason="open_position_exists_for_symbol",
                    trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                )
                return

            # Normalize side to lowercase for execute_trade
            side = "buy" if side_raw == "BUY" else "sell"

            # Use payload stop_loss/take_profit when present (e.g. ATR-based), else shared helper
            stop_loss = payload.get("stop_loss")
            take_profit = payload.get("take_profit")
            if stop_loss is None or take_profit is None:
                tick_fb = payload.get("tick_size")
                tick_sz_opt: Optional[float] = None
                if tick_fb is not None:
                    try:
                        tick_sz_opt = float(tick_fb)
                    except (TypeError, ValueError):
                        tick_sz_opt = None
                atr_fb = payload.get("atr_14")
                atr_14_opt: Optional[float] = None
                if atr_fb is not None:
                    try:
                        atr_14_opt = float(atr_fb)
                    except (TypeError, ValueError):
                        atr_14_opt = None
                try:
                    pf = float(price)
                except (TypeError, ValueError):
                    pf = 0.0
                stop_loss, take_profit = compute_stop_take_prices(
                    pf,
                    side_raw,
                    float(settings.stop_loss_percentage),
                    float(settings.take_profit_percentage),
                    use_atr_scaled=bool(getattr(settings, "use_atr_scaled_sl_tp", False))
                    and atr_14_opt is not None,
                    atr_14=atr_14_opt,
                    atr_sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
                    atr_tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
                    tick_size=tick_sz_opt,
                )

            trade = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "market",
                "price": price,
                "reference_price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "execution_authority": AGENT_DECISION_AUTHORITY,
                "decision_event_id": event.correlation_id or event.event_id,
            }

            pex = dict(trade.get("position_extras") or {})
            pex["agent_controlled"] = True
            if payload.get("contract_value_btc") is not None:
                try:
                    pex["contract_value_btc"] = float(payload["contract_value_btc"])
                except (TypeError, ValueError):
                    pass
            if payload.get("tick_size") is not None:
                try:
                    pex["tick_size"] = float(payload["tick_size"])
                except (TypeError, ValueError):
                    pass
            uir = payload.get("usd_inr_rate")
            if uir is not None:
                try:
                    pex["paper_usdinr_entry"] = float(uir)
                except (TypeError, ValueError):
                    pass
            if pex:
                trade["position_extras"] = pex

            try:
                pf = float(price)
            except (TypeError, ValueError):
                pf = 0.0
            if pf <= 0:
                logger.warning(
                    "execution_risk_approved_invalid_price",
                    symbol=symbol,
                    price=price,
                    event_id=event.event_id,
                )
                logger.warning(
                    "trading_execution_rejected",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=side_raw,
                    stage="invalid_price",
                    reason="price_missing_or_nonpositive",
                    trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                )
                return
            trade["price"] = pf

            rc_raw = payload.get("reasoning_chain_id")
            eff_reasoning_chain_id = (
                str(rc_raw).strip()
                if rc_raw is not None and str(rc_raw).strip() != ""
                else (str(event.event_id) if getattr(event, "event_id", None) else None)
            )
            if eff_reasoning_chain_id:
                payload["reasoning_chain_id"] = eff_reasoning_chain_id
                trade["reasoning_chain_id"] = eff_reasoning_chain_id

            if not payload.get("ml_signal_validated"):
                model_preds = payload.get("model_predictions") or []
                ml_ok, ml_reason = validate_ml_entry_signal(
                    signal=side_raw,
                    side=side_raw,
                    model_predictions=model_preds,
                    market_context=payload.get("market_context")
                    if isinstance(payload.get("market_context"), dict)
                    else {},
                    ml_evidence_snapshot=payload.get("ml_evidence_snapshot")
                    if isinstance(payload.get("ml_evidence_snapshot"), dict)
                    else None,
                    policy_verdict=payload.get("policy_verdict")
                    if isinstance(payload.get("policy_verdict"), dict)
                    else None,
                )
                if not ml_ok:
                    logger.warning(
                        "execution_risk_approved_ml_signal_rejected",
                        symbol=symbol,
                        side=side_raw,
                        reason=ml_reason,
                        event_id=event.event_id,
                    )
                    logger.warning(
                        "trading_execution_rejected",
                        correlation_id=event.event_id,
                        symbol=symbol,
                        side=side_raw,
                        stage="ml_signal_guard",
                        reason=ml_reason,
                        trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                    )
                    return
            trade["ml_signal_validated"] = True
            trade["ml_signal_source"] = payload.get("ml_signal_source") or "ml_models"
            if payload.get("model_predictions"):
                trade["model_predictions"] = payload.get("model_predictions")

            result = await self.execute_trade(trade)

            if not result.success:
                logger.warning(
                    "execution_risk_approved_trade_failed",
                    symbol=symbol,
                    side=side,
                    error=result.error_message,
                    event_id=event.event_id,
                )
                logger.warning(
                    "trading_execution_rejected",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=side_raw,
                    stage="execute_trade",
                    reason=result.error_message or "execute_trade_failed",
                    trading_mode=str(getattr(settings, "trading_mode", "testnet")),
                )
                return

            fill_price = result.details.get("average_fill_price") or price
            # SL/TP rebased to fill inside execute_trade when order fills immediately
            pos = self.position_manager.get_position(symbol)
            if pos:
                if pos.get("stop_loss") is not None:
                    stop_loss = pos.get("stop_loss")
                if pos.get("take_profit") is not None:
                    take_profit = pos.get("take_profit")
            # Enrich position with metadata for learning and sync RiskManager portfolio
            if pos:
                pos["model_predictions"] = payload.get("model_predictions")
                pos["reasoning_chain_id"] = payload.get("reasoning_chain_id")
                pos["predicted_signal"] = payload.get("side", "")
                if payload.get("memory_context_id") is not None:
                    pos["memory_context_id"] = payload.get("memory_context_id")
                if payload.get("agent_introspection_at_entry") is not None:
                    pos["agent_introspection_at_entry"] = payload.get(
                        "agent_introspection_at_entry"
                    )
                if payload.get("confidence") is not None:
                    pos["confidence_at_entry"] = payload.get("confidence")
            if self.risk_manager and getattr(self.risk_manager, "portfolio", None):
                from agent.risk.risk_manager import Position as RMPosition
                rm_pos = RMPosition(
                    symbol=symbol,
                    side="long" if side == "buy" else "short",
                    size=quantity,
                    entry_price=fill_price,
                    entry_time=datetime.now(timezone.utc),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                self.risk_manager.portfolio.add_position(rm_pos)

            # Publish OrderFillEvent for backend persistence and WebSocket broadcast
            order_id = result.order_id or str(uuid.uuid4())[:8]
            trade_id = f"trade_{order_id}_{datetime.now(timezone.utc).timestamp()}"

            ex_raw = result.details.get("exchange_order_id")
            exchange_order_id = str(ex_raw) if ex_raw is not None else None

            order_fill = OrderFillEvent(
                source="execution_engine",
                correlation_id=event.event_id,
                payload={
                    "order_id": order_id,
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "side": side_raw,
                    "quantity": quantity,
                    "fill_price": fill_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "timestamp": datetime.now(timezone.utc),
                    "exchange_order_id": exchange_order_id,
                    "client_order_id": f"js_{order_id}",
                    "reasoning_chain_id": payload.get("reasoning_chain_id"),
                },
            )
            await event_bus.publish(order_fill)

            if getattr(settings, "signal_audit_md_enabled", True):
                try:
                    from agent.core.paper_trade_entry import compute_paper_entry_ledger
                    from agent.core.paper_trade_logger import paper_trade_logger

                    pos_audit = self.position_manager.get_position(symbol)
                    position_id = f"pos_{order_id}"
                    cv = float(
                        (pos_audit or {}).get("contract_value_btc")
                        or getattr(settings, "contract_value_btc", 0.001)
                    )
                    payload_usdinr = payload.get("usd_inr_rate")
                    if payload_usdinr is not None:
                        try:
                            usdinr = float(payload_usdinr)
                        except (TypeError, ValueError):
                            usdinr = await self._resolve_usdinr_paper()
                    else:
                        usdinr = await self._resolve_usdinr_paper()
                    trade_value_inr, fees_inr, _ = compute_paper_entry_ledger(
                        quantity=float(quantity),
                        fill_price=float(fill_price),
                        contract_value_btc=cv,
                        usd_inr_rate=usdinr,
                    )
                    sl_audit = stop_loss
                    tp_audit = take_profit
                    if pos_audit:
                        if pos_audit.get("stop_loss") is not None:
                            sl_audit = pos_audit.get("stop_loss")
                        if pos_audit.get("take_profit") is not None:
                            tp_audit = pos_audit.get("take_profit")
                    ref_px = payload.get("price")
                    paper_trade_logger.log_trade(
                        trade_id=trade_id,
                        symbol=symbol,
                        side=side_raw,
                        quantity=quantity,
                        fill_price=fill_price,
                        order_id=order_id,
                        position_id=position_id,
                        reasoning_chain_id=payload.get("reasoning_chain_id"),
                        usd_inr_rate=usdinr,
                        trade_value_inr=trade_value_inr,
                        fees_inr=fees_inr,
                        reference_price=float(ref_px) if ref_px is not None else None,
                        stop_loss=float(sl_audit) if sl_audit is not None else None,
                        take_profit=float(tp_audit) if tp_audit is not None else None,
                    )
                except Exception:
                    pass

            v43_bar = payload.get("v43_closed_bar_index")
            if v43_bar is not None:
                try:
                    from agent.core.mcp_orchestrator import mcp_orchestrator

                    mcp_orchestrator.record_v43_trade_executed(int(v43_bar))
                    asyncio.create_task(
                        mcp_orchestrator.persist_v43_gate_state_after_trade(symbol)
                    )
                except Exception:
                    pass

            logger.info(
                "execution_order_fill_published",
                trade_id=trade_id,
                symbol=symbol,
                side=side_raw,
                quantity=quantity,
                fill_price=fill_price,
                event_id=event.event_id,
            )

        except Exception as e:
            logger.error(
                "execution_handle_risk_approved_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True,
            )
            logger.error(
                "execution_failed",
                correlation_id=event.event_id,
                error=str(e),
                trading_mode=str(getattr(settings, "trading_mode", "testnet")),
            )

    async def execute_trade(self, trade: Dict[str, Any]) -> ExecutionResult:
        """
        Execute a trade with comprehensive order management.

        Args:
            trade: Trade specification with symbol, side, size, etc.

        Returns:
            ExecutionResult with success status and details
        """
        if not self._initialized:
            return ExecutionResult(False, error_message="Execution engine not initialized")

        if not self.exchange_connected:
            return ExecutionResult(
                False,
                error_message="Delta testnet connection is down; trading halted",
            )

        symbol = str(trade.get("symbol") or "").strip()
        if not symbol:
            return ExecutionResult(False, error_message="Missing required trade parameter: symbol")

        execution_authority = trade.get("execution_authority")
        agent_only = bool(getattr(settings, "agent_only_delta_orders", True))
        block_manual = bool(getattr(settings, "block_manual_execute_trade", True))
        if agent_only and block_manual and not is_agent_controlled_authority(execution_authority):
            logger.warning(
                "trade_execution_rejected_non_agent_authority",
                symbol=symbol,
                execution_authority=execution_authority,
            )
            return ExecutionResult(
                False,
                error_message=(
                    "Only autonomous agent decisions may place Delta orders "
                    "(AGENT_ONLY_DELTA_ORDERS)."
                ),
            )

        if bool(getattr(settings, "require_ml_signal_for_orders", True)):
            if not trade.get("ml_signal_validated"):
                logger.warning(
                    "trade_execution_rejected_no_ml_signal",
                    symbol=symbol,
                    execution_authority=execution_authority,
                )
                return ExecutionResult(
                    False,
                    error_message=(
                        "Entry orders require a validated ML model signal "
                        "(REQUIRE_ML_SIGNAL_FOR_ORDERS)."
                    ),
                )

        if is_agent_controlled_authority(execution_authority):
            pex_auth = dict(trade.get("position_extras") or {})
            pex_auth["agent_controlled"] = True
            trade["position_extras"] = pex_auth

        decision_event_id = trade.get("decision_event_id")
        if is_agent_controlled_authority(execution_authority) and is_decision_already_executed(
            decision_event_id
        ):
            logger.warning(
                "duplicate_decision_entry_blocked",
                symbol=symbol,
                decision_event_id=decision_event_id,
            )
            return ExecutionResult(
                False,
                error_message=f"Duplicate decision_event_id: {decision_event_id}",
            )

        async with self._inflight_lock:
            if symbol in self._inflight_symbols:
                return ExecutionResult(
                    False,
                    error_message=f"Trade already in progress for {symbol}",
                )
            self._inflight_symbols.add(symbol)

        trade["submitted_at_monotonic"] = time.perf_counter()

        try:
            side = trade["side"]  # 'buy' or 'sell'
            quantity = trade["quantity"]
            order_type = trade.get("order_type", "market")
            price = trade.get("price")
            stop_loss = trade.get("stop_loss")
            take_profit = trade.get("take_profit")
            pex_pre = trade.get("position_extras") or {}
            tick_pre: Optional[float] = None
            if pex_pre.get("tick_size") is not None:
                try:
                    tick_pre = float(pex_pre["tick_size"])
                except (TypeError, ValueError):
                    tick_pre = None
            if (stop_loss is None or take_profit is None) and price is not None:
                try:
                    pf0 = float(price)
                except (TypeError, ValueError):
                    pf0 = 0.0
                if pf0 > 0:
                    sl_c, tp_c = compute_stop_take_prices(
                        pf0,
                        "BUY" if side == "buy" else "SELL",
                        float(settings.stop_loss_percentage),
                        float(settings.take_profit_percentage),
                        use_atr_scaled=False,
                        atr_14=None,
                        atr_sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
                        atr_tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
                        tick_size=tick_pre,
                    )
                    if stop_loss is None:
                        stop_loss = sl_c
                    if take_profit is None:
                        take_profit = tp_c
                    trade["stop_loss"] = stop_loss
                    trade["take_profit"] = take_profit

            # Check if we need to close existing position first (BEFORE validation)
            existing_position = self.position_manager.get_position(symbol)
            if (
                existing_position
                and existing_position.get("status") == "open"
                and existing_position["side"] != ("long" if side == "buy" else "short")
            ):
                # Close opposite position first
                await self.close_position(symbol, order_type="market")

            # Validate trade parameters (after potential position close)
            validation_result = await self._validate_trade(trade)
            if not validation_result["valid"]:
                return ExecutionResult(False, error_message=validation_result["error"])

            if is_agent_controlled_authority(execution_authority):
                record_agent_order_intent(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    execution_authority=str(execution_authority),
                    reasoning_chain_id=trade.get("reasoning_chain_id"),
                )

            # Execute the order
            order_result = await self._place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price
            )

            if not order_result["success"]:
                return ExecutionResult(False, error_message=order_result["error"])

            order_id = order_result["order_id"]

            filled_qty = float(order_result.get("filled_quantity") or 0.0)
            position_opened = False
            if order_result.get("filled_immediately") or filled_qty > 0:
                raw_fill = order_result.get("average_fill_price")
                if raw_fill is None:
                    return ExecutionResult(
                        False,
                        error_message="Order filled but no average_fill_price returned",
                    )
                fill_price = float(raw_fill)
                open_qty = filled_qty if filled_qty > 0 else quantity
                pex = trade.get("position_extras") or {}
                tick_sz: Optional[float] = None
                if pex.get("tick_size") is not None:
                    try:
                        tick_sz = float(pex["tick_size"])
                    except (TypeError, ValueError):
                        tick_sz = None
                try:
                    planned_entry = float(
                        trade.get("reference_price") or trade.get("price") or fill_price
                    )
                except (TypeError, ValueError):
                    planned_entry = fill_price
                if (stop_loss is not None or take_profit is not None) and planned_entry > 0:
                    stop_loss, take_profit = rebase_sl_tp_to_fill(
                        planned_entry,
                        fill_price,
                        stop_loss,
                        take_profit,
                        tick_size=tick_sz,
                    )
                    trade["stop_loss"] = stop_loss
                    trade["take_profit"] = take_profit
                position = self.position_manager.open_position(
                    symbol=symbol,
                    side="long" if side == "buy" else "short",
                    quantity=open_qty,
                    entry_price=fill_price,
                    order_id=order_id,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_extras=trade.get("position_extras"),
                )
                position_opened = True
                if self.exchange_gateway and hasattr(self.exchange_gateway, "register_position_opened"):
                    try:
                        getattr(self.exchange_gateway, "register_position_opened")(position)
                    except Exception as e:
                        logger.debug("exchange_gateway_register_open_failed", error=str(e), symbol=symbol)

                if is_agent_controlled_authority(execution_authority):
                    record_agent_order_fill(
                        symbol=symbol,
                        side=side,
                        quantity=open_qty,
                        fill_price=fill_price,
                        execution_authority=str(execution_authority),
                        internal_order_id=order_id,
                        exchange_order_id=order_result.get("exchange_order_id"),
                        client_order_id=f"js_{order_id}",
                        reduce_only=False,
                        reasoning_chain_id=trade.get("reasoning_chain_id"),
                    )

            if order_result.get("partial_fill"):
                partial_event = PartialFillEvent(
                    source="execution_engine",
                    payload={
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                        "requested_quantity": float(order_result.get("requested_quantity") or quantity),
                        "filled_quantity": filled_qty,
                        "fill_price": float(order_result.get("average_fill_price") or 0.0),
                        "timestamp": datetime.now(timezone.utc),
                        "exchange_order_id": order_result.get("exchange_order_id"),
                        "execution_authority": execution_authority,
                        "reasoning_chain_id": trade.get("reasoning_chain_id"),
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "position_extras": trade.get("position_extras"),
                    },
                )
                await event_bus.publish(partial_event)

            result = ExecutionResult(True, order_id=order_id)
            result.details = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "filled_immediately": order_result["filled_immediately"],
                "partial_fill": bool(order_result.get("partial_fill")),
                "filled_quantity": filled_qty,
                "average_fill_price": order_result.get("average_fill_price"),
                "position_opened": position_opened,
            }

            base_url = getattr(self.delta_client, "base_url", None) if self.delta_client else None
            log_extra: Dict[str, Any] = {}
            ref_price = trade.get("reference_price") or trade.get("price")
            fill_px = order_result.get("average_fill_price")
            if ref_price is not None and fill_px is not None:
                try:
                    ref_f = float(ref_price)
                    fill_f = float(fill_px)
                    if ref_f > 0:
                        slip_bps = (fill_f - ref_f) / ref_f * 10000.0
                        if side == "sell":
                            slip_bps = -slip_bps
                        log_extra["execution_slippage_bps"] = round(slip_bps, 4)
                        log_extra["reference_price"] = ref_f
                except (TypeError, ValueError):
                    pass
            submitted_at = trade.get("submitted_at_monotonic")
            if submitted_at is not None:
                try:
                    log_extra["execution_latency_ms"] = round(
                        (time.perf_counter() - float(submitted_at)) * 1000.0, 2
                    )
                except (TypeError, ValueError):
                    pass
            if is_agent_controlled_authority(execution_authority):
                record_decision_execution(decision_event_id)

            logger.info(
                "trade_executed",
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_id=order_id,
                exchange_order_id=order_result.get("exchange_order_id"),
                delta_exchange_base_url=base_url,
                filled_immediately=order_result["filled_immediately"],
                average_fill_price=order_result.get("average_fill_price"),
                decision_event_id=decision_event_id,
                **log_extra,
            )

            return result

        except Exception as e:
            logger.error("trade_execution_failed",
                        trade=trade,
                        error=str(e))
            return ExecutionResult(False, error_message=f"Execution failed: {str(e)}")
        finally:
            async with self._inflight_lock:
                self._inflight_symbols.discard(symbol)

    async def _resolve_usdinr_paper(self) -> float:
        """Live USDINR from Redis cache, else config fallback."""
        from agent.core.paper_trade_entry import resolve_paper_usdinr_rate

        return await resolve_paper_usdinr_rate(None)

    async def close_position(self, symbol: str, order_type: str = "market",
                           price: Optional[float] = None,
                           exit_reason: str = "market_close") -> ExecutionResult:
        """Close an existing position. exit_reason: market_close, stop_loss_hit, take_profit_hit, signal_reversal, time_limit."""
        async with self._position_lock:
            return await self._close_position_impl(symbol, order_type, price, exit_reason)

    async def _close_position_impl(self, symbol: str, order_type: str = "market",
                                   price: Optional[float] = None,
                                   exit_reason: str = "market_close") -> ExecutionResult:
        """Close position (caller must hold _position_lock via close_position)."""
        position = self.position_manager.get_position(symbol)
        if not position:
            return ExecutionResult(False, error_message=f"No open position for {symbol}")

        if position.get("status") != "open":
            logger.info(
                "position_close_skipped_already_closed",
                symbol=symbol,
                status=position.get("status"),
                exit_reason=exit_reason,
            )
            return ExecutionResult(False, error_message="already_closed")

        try:
            entry_px = float(position["entry_price"])
        except (TypeError, ValueError):
            entry_px = 0.0
        lots = float(position.get("lots", position.get("quantity", 0)))
        if (
            entry_px <= 0
            or not math.isfinite(entry_px)
            or lots <= 0
            or not math.isfinite(lots)
        ):
            logger.error(
                "close_aborted_invalid_entry_state",
                symbol=symbol,
                entry_price=entry_px,
                lots=lots,
            )
            return ExecutionResult(
                False,
                error_message="Invalid entry_price or quantity; close aborted without clearing state",
            )

        model_predictions = position.get("model_predictions")
        reasoning_chain_id = position.get("reasoning_chain_id")
        predicted_signal = position.get("predicted_signal")
        entry_time = position.get("entry_time")
        memory_context_id = position.get("memory_context_id")
        agent_introspection_at_entry = position.get("agent_introspection_at_entry")
        confidence_at_entry = position.get("confidence_at_entry")

        try:
            close_side = "sell" if position["side"] == "long" else "buy"

            order_result = await self._place_order(
                symbol=symbol,
                side=close_side,
                quantity=position.get("lots", position.get("quantity", 0)),
                order_type=order_type,
                price=price,
                reduce_only=True,
            )

            if order_result["success"] and order_result.get("filled_immediately", False):
                raw_exit = order_result.get("average_fill_price")
                if raw_exit is None:
                    return ExecutionResult(
                        False,
                        error_message="Close order filled but no average_fill_price returned",
                    )
                exit_price = float(raw_exit)
                if exit_price <= 0 or not math.isfinite(exit_price):
                    logger.error("close_aborted_invalid_exit_price", symbol=symbol, exit_price=exit_price)
                    return ExecutionResult(False, error_message="Invalid exit fill price")

                cv = float(
                    position.get("contract_value_btc")
                    or getattr(settings, "contract_value_btc", 0.001)
                )
                taker = float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005)
                slip_bps = float(getattr(settings, "slippage_bps", 5.0) or 5.0)
                mode = (getattr(settings, "fee_accounting_mode", "split") or "split").lower()
                if mode == "round_trip":
                    gross_usd, fees_usd, net_usd = net_pnl_usd_after_fees(
                        entry_px,
                        exit_price,
                        lots,
                        position["side"],
                        cv,
                        taker,
                        slip_bps,
                    )
                    fees_exit_usd = fees_usd
                else:
                    gross_usd, _fe_in, fees_exit_usd, fees_usd, net_usd = (
                        net_pnl_usd_after_fees_split_legs(
                            entry_px,
                            exit_price,
                            lots,
                            position["side"],
                            cv,
                            taker,
                            slip_bps,
                        )
                    )

                closed_position = self.position_manager.close_position(
                    symbol=symbol,
                    exit_price=exit_price,
                    exit_order_id=order_result["order_id"]
                )
                if self.exchange_gateway and hasattr(self.exchange_gateway, "register_position_closed"):
                    try:
                        getattr(self.exchange_gateway, "register_position_closed")(symbol, net_usd)
                    except Exception as e:
                        logger.debug("exchange_gateway_register_close_failed", error=str(e), symbol=symbol)

                if self.risk_manager and getattr(self.risk_manager, "portfolio", None):
                    self.risk_manager.portfolio.remove_position(symbol)

                logger.info(
                    "position_closed_successfully",
                    symbol=symbol,
                    exit_price=exit_price,
                    realized_pnl_gross_usd=gross_usd,
                    fees_usd=fees_usd,
                    realized_pnl_net_usd=net_usd,
                )

                position_id = f"pos_{closed_position.get('entry_order_id', order_result.get('order_id', ''))}"
                usdinr_exit = await self._resolve_usdinr_paper()
                try:
                    usdinr_entry = float(position.get("paper_usdinr_entry")) if position.get("paper_usdinr_entry") is not None else usdinr_exit
                except (TypeError, ValueError):
                    usdinr_entry = usdinr_exit

                notional_usd_entry = lots * entry_px * cv
                fx_pnl_inr = notional_usd_entry * (usdinr_exit - usdinr_entry)

                exit_ex = order_result.get("exchange_order_id")
                payload_data: Dict[str, Any] = {
                    "position_id": position_id,
                    "symbol": symbol,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "quantity": position.get("lots", position.get("quantity", 0)),
                    "pnl": net_usd,
                    "gross_pnl_usd": gross_usd,
                    "fees_usd": fees_usd,
                    "usdinr_at_entry": usdinr_entry,
                    "usdinr_at_exit": usdinr_exit,
                    "fx_pnl_inr": fx_pnl_inr,
                    "exit_reason": exit_reason,
                    "timestamp": datetime.now(timezone.utc),
                    "exchange_order_id": str(exit_ex) if exit_ex is not None else None,
                }
                if model_predictions is not None:
                    payload_data["model_predictions"] = model_predictions
                if reasoning_chain_id is not None:
                    payload_data["reasoning_chain_id"] = reasoning_chain_id
                if predicted_signal is not None:
                    payload_data["predicted_signal"] = predicted_signal
                if entry_time is not None:
                    payload_data["entry_time"] = entry_time
                if memory_context_id is not None:
                    payload_data["memory_context_id"] = memory_context_id
                if agent_introspection_at_entry is not None:
                    payload_data["agent_introspection_at_entry"] = (
                        agent_introspection_at_entry
                    )
                if confidence_at_entry is not None:
                    payload_data["confidence_at_entry"] = confidence_at_entry
                if entry_time is not None:
                    try:
                        closed_ts = payload_data["timestamp"]
                        if hasattr(closed_ts, "timestamp") and hasattr(entry_time, "timestamp"):
                            payload_data["duration_seconds"] = (
                                closed_ts - entry_time
                            ).total_seconds()
                    except Exception:
                        pass
                try:
                    from agent.core.agent_self_awareness_hooks import (
                        enrich_position_closed_payload,
                    )

                    await enrich_position_closed_payload(payload_data)
                except Exception as e:
                    logger.warning(
                        "position_closed_self_awareness_hooks_failed",
                        error=str(e),
                    )

                if getattr(settings, "signal_audit_md_enabled", True):
                    try:
                        from agent.core.paper_trade_logger import paper_trade_logger

                        duration_s = payload_data.get("duration_seconds")
                        net_pnl_inr = float(net_usd) * float(usdinr_exit) + float(fx_pnl_inr)
                        paper_trade_logger.log_position_close(
                            position_id=position_id,
                            symbol=symbol,
                            side=position["side"],
                            entry_price=float(position["entry_price"]),
                            exit_price=exit_price,
                            quantity=lots,
                            pnl=net_usd,
                            exit_reason=exit_reason,
                            net_pnl_inr=net_pnl_inr,
                            duration_seconds=duration_s,
                            gross_pnl_usd=gross_usd,
                            usdinr_at_entry=usdinr_entry,
                            usd_inr_rate=usdinr_exit,
                            fx_pnl_inr=fx_pnl_inr,
                            reasoning_chain_id=reasoning_chain_id,
                        )
                    except Exception:
                        pass

                pos_closed = PositionClosedEvent(
                    source="execution_engine",
                    payload=payload_data,
                )
                await event_bus.publish(pos_closed)

                return ExecutionResult(True, order_id=order_result.get("order_id"))

            return ExecutionResult(
                False,
                error_message=order_result.get("error", "Close order did not fill"),
                order_id=order_result.get("order_id"),
            )

        except Exception as e:
            logger.error("position_close_failed",
                        symbol=symbol,
                        error=str(e))
            return ExecutionResult(False, error_message=f"Close failed: {str(e)}")

    async def get_positions_view(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Return Delta-compatible position view via active exchange gateway."""
        if self.exchange_gateway:
            return await self.exchange_gateway.get_positions(symbol=symbol)
        rows: List[Dict[str, Any]] = []
        for sym, pos in self.position_manager.get_all_positions().items():
            if symbol and sym != symbol:
                continue
            signed = float(pos.get("lots", pos.get("quantity", 0.0)) or 0.0)
            if pos.get("side") == "short":
                signed = -signed
            rows.append(
                {
                    "product_symbol": sym,
                    "size": signed,
                    "entry_price": float(pos.get("entry_price", 0.0) or 0.0),
                    "margin": 0.0,
                    "liquidation_price": float(pos.get("entry_price", 0.0) or 0.0),
                    "realized_pnl": 0.0,
                    "realized_funding": 0.0,
                    "adl_level": 1,
                }
            )
        return {"success": True, "result": rows}

    async def get_margined_positions_view(self) -> Dict[str, Any]:
        """Return Delta-compatible margined portfolio view."""
        if self.exchange_gateway:
            return await self.exchange_gateway.get_margined_positions()
        return await self.get_positions_view()

    async def get_assets_view(self) -> Dict[str, Any]:
        """Return assets metadata from active gateway."""
        if self.exchange_gateway:
            return await self.exchange_gateway.get_assets()
        return {"success": True, "result": []}

    async def get_wallet_balances_view(self) -> Dict[str, Any]:
        """Return wallet balances from active gateway."""
        if self.exchange_gateway:
            return await self.exchange_gateway.get_wallet_balances()
        return {"success": True, "result": []}

    async def get_exchange_portfolio_snapshot(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Fetch margined positions, wallet balances, and optional order history from testnet."""
        symbol = symbol or str(getattr(settings, "trading_symbol", "BTCUSD") or "BTCUSD")
        margined = await self.get_margined_positions_view()
        wallet = await self.get_wallet_balances_view()
        assets = await self.get_assets_view()
        order_history: Dict[str, Any] = {"success": True, "result": []}
        if self.delta_client:
            try:
                product_id = await self.delta_client.resolve_product_id(symbol)
                order_history = await self.delta_client.get_orders_history(
                    product_ids=str(product_id),
                    page_size=50,
                )
            except Exception as exc:
                logger.warning(
                    "exchange_portfolio_order_history_failed",
                    symbol=symbol,
                    error=str(exc),
                )
        return {
            "success": True,
            "margined_positions": margined,
            "wallet_balances": wallet,
            "assets": assets,
            "order_history": order_history,
        }

    async def adopt_exchange_position(
        self,
        symbol: str,
        row: Dict[str, Any],
    ) -> bool:
        """Register an exchange margined leg in position_manager for SL/TP monitoring."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return False
        existing = self.position_manager.get_position(sym)
        if existing and str(existing.get("status") or "").lower() == "open":
            return False

        signed_size = float(row.get("size") or 0)
        lots = abs(signed_size)
        if lots <= 0:
            return False

        entry_price = float(row.get("entry_price") or row.get("avg_entry_price") or 0)
        if entry_price <= 0:
            mark = float(row.get("mark_price") or row.get("index_price") or 0)
            entry_price = mark if mark > 0 else 0.0
        if entry_price <= 0:
            logger.warning("adopt_exchange_position_no_entry_price", symbol=sym)
            return False

        side_pm = "long" if signed_size >= 0 else "short"
        side_risk = "BUY" if side_pm == "long" else "SELL"
        tick_sz: Optional[float] = None
        try:
            from agent.core.product_specs import get_contract_specs

            specs = await get_contract_specs(sym)
            tick_sz = float(specs.tick_size)
        except Exception:
            tick_sz = None
        stop_loss, take_profit = compute_stop_take_prices(
            entry_price,
            side_risk,
            float(settings.stop_loss_percentage),
            float(settings.take_profit_percentage),
            use_atr_scaled=False,
            atr_14=None,
            atr_sl_mult=float(getattr(settings, "atr_sl_distance_mult", 1.0) or 1.0),
            atr_tp_mult=float(getattr(settings, "atr_tp_distance_mult", 1.5) or 1.5),
            tick_size=tick_sz,
        )

        created = row.get("created_at") or row.get("updated_at")
        entry_time: Optional[datetime] = None
        if isinstance(created, datetime):
            entry_time = created
        elif isinstance(created, str):
            try:
                entry_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                entry_time = None

        cv = float(getattr(settings, "contract_value_btc", 0.001))
        product = row.get("product")
        if isinstance(product, dict) and product.get("contract_value") is not None:
            try:
                cv = float(product["contract_value"])
            except (TypeError, ValueError):
                pass

        order_id = f"reconcile_{row.get('id') or sym}"
        extras: Dict[str, Any] = {
            "contract_value_btc": cv,
            "exchange_reconciled": True,
            "exchange_position_id": row.get("id"),
            "agent_controlled": True,
        }
        if entry_time is not None:
            extras["entry_time"] = entry_time

        self.position_manager.open_position(
            symbol=sym,
            side=side_pm,
            quantity=lots,
            entry_price=entry_price,
            order_id=str(order_id)[:32],
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_extras=extras,
        )

        if self.exchange_gateway and hasattr(self.exchange_gateway, "register_position_opened"):
            pos = self.position_manager.get_position(sym)
            if pos:
                try:
                    getattr(self.exchange_gateway, "register_position_opened")(pos)
                except Exception as exc:
                    logger.debug(
                        "adopt_exchange_register_gateway_failed",
                        symbol=sym,
                        error=str(exc),
                    )

        logger.info(
            "exchange_position_adopted",
            symbol=sym,
            side=side_pm,
            lots=lots,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return True

    async def close_exchange_position(
        self,
        symbol: str,
        *,
        row: Optional[Dict[str, Any]] = None,
        exit_reason: str = "exchange_reconcile",
    ) -> "ExecutionResult":
        """Flatten an exchange leg with reduce-only order (no local position required)."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return ExecutionResult(False, error_message="missing_symbol")

        if row is None:
            try:
                view = await self.get_margined_positions_view()
            except Exception as exc:
                return ExecutionResult(False, error_message=f"fetch_failed:{exc}")
            from agent.core.position_reconcile import exchange_open_symbols, parse_margined_rows

            ex_map = exchange_open_symbols(parse_margined_rows(view))
            row = ex_map.get(sym)
            if not row:
                return ExecutionResult(False, error_message=f"no_exchange_position_for_{sym}")

        signed_size = float(row.get("size") or 0)
        lots = abs(signed_size)
        if lots <= 0:
            return ExecutionResult(False, error_message="zero_size")

        close_side = "sell" if signed_size > 0 else "buy"
        async with self._position_lock:
            order_result = await self._place_order(
                symbol=sym,
                side=close_side,
                quantity=lots,
                order_type="market",
                reduce_only=True,
            )
            if not order_result.get("success"):
                return ExecutionResult(
                    False,
                    error_message=order_result.get("error", "close_order_failed"),
                )

            local = self.position_manager.get_position(sym)
            if local and str(local.get("status") or "").lower() == "open":
                fill = order_result.get("average_fill_price")
                if fill is not None:
                    await self._close_position_impl(
                        sym,
                        "market",
                        float(fill),
                        exit_reason,
                    )
                else:
                    self.position_manager.close_position(
                        sym,
                        float(local.get("current_price") or local.get("entry_price") or 0),
                        str(order_result.get("order_id") or "reconcile"),
                    )

            logger.info(
                "exchange_position_closed",
                symbol=sym,
                lots=lots,
                side=close_side,
                exit_reason=exit_reason,
                exchange_order_id=order_result.get("exchange_order_id"),
            )
            return ExecutionResult(True, order_id=order_result.get("order_id"))

    async def change_position_margin(self, symbol: str, margin_delta: float) -> Dict[str, Any]:
        """Change margin for a symbol using active gateway."""
        if not self.exchange_gateway:
            return {"success": False, "error": "Exchange gateway not configured"}
        return await self.exchange_gateway.change_margin(product_symbol=symbol, margin=margin_delta)

    async def close_all_positions(self, exit_reason: str = "emergency_exit") -> Dict[str, Any]:
        """Close all open positions; uses gateway in paper/live parity mode."""
        if self.exchange_gateway:
            return await self.exchange_gateway.close_all_positions()
        open_symbols = list(self.position_manager.get_all_positions().keys())
        closed: List[str] = []
        failed: Dict[str, str] = {}
        for symbol in open_symbols:
            res = await self.close_position(symbol, exit_reason=exit_reason)
            if res.success:
                closed.append(symbol)
            else:
                failed[symbol] = str(res.error_message or "close_failed")
        return {"success": len(failed) == 0, "result": {"closed_symbols": closed, "failed": failed}}

    async def manage_position(self, position_symbol: str) -> Dict[str, Any]:
        """
        Manage an existing position (check stops, etc.).

        Returns:
            Management actions taken
        """
        position = self.position_manager.get_position(position_symbol)
        if not position or position.get("status") != "open":
            out: Dict[str, Any] = {"action": "none", "reason": "position_not_open"}
            if position is not None:
                out["status"] = position.get("status")
            return out

        actions_taken: List[Dict[str, Any]] = []

        current_price = position.get("current_price", position["entry_price"])
        entry_price = position["entry_price"]

        trail_pct = getattr(settings, "trailing_stop_percentage", 0.015) or 0.015
        act_pct = float(
            getattr(settings, "trailing_stop_activation_profit_pct", 0.0) or 0.0
        )

        past_min_hold = True

        if past_min_hold and position["side"] == "long" and current_price > entry_price:
            profit_pct = (current_price - entry_price) / entry_price
            if act_pct <= 0 or profit_pct >= act_pct:
                new_trail_stop = current_price * (1 - trail_pct)
                if new_trail_stop > (position.get("stop_loss") or 0):
                    position["stop_loss"] = new_trail_stop
                    logger.info(
                        "trailing_stop_updated",
                        symbol=position_symbol,
                        new_stop=new_trail_stop,
                    )
        elif past_min_hold and position["side"] == "short" and current_price < entry_price:
            profit_pct = (entry_price - current_price) / entry_price
            if act_pct <= 0 or profit_pct >= act_pct:
                new_trail_stop = current_price * (1 + trail_pct)
                current_sl = position.get("stop_loss")
                if current_sl is None or new_trail_stop < current_sl:
                    position["stop_loss"] = new_trail_stop
                    logger.info(
                        "trailing_stop_updated",
                        symbol=position_symbol,
                        new_stop=new_trail_stop,
                    )

        stop_loss = position.get("stop_loss")
        take_profit = position.get("take_profit")

        if stop_loss:
            should_stop = (position["side"] == "long" and current_price <= stop_loss) or (
                position["side"] == "short" and current_price >= stop_loss
            )
            if should_stop:
                sl_reason = "stop_loss_hit"
                close_result = await self.close_position(position_symbol, exit_reason=sl_reason)
                if close_result.success:
                    actions_taken.append(
                        {
                            "action": "stop_loss_triggered",
                            "symbol": position_symbol,
                            "exit_price": current_price,
                        }
                    )
                    return {
                        "symbol": position_symbol,
                        "actions_taken": actions_taken,
                        "position_status": "closed",
                    }

        if take_profit and past_min_hold:
            should_tp = (position["side"] == "long" and current_price >= take_profit) or (
                position["side"] == "short" and current_price <= take_profit
            )
            if should_tp:
                close_result = await self.close_position(
                    position_symbol, exit_reason="take_profit_hit"
                )
                if close_result.success:
                    actions_taken.append(
                        {
                            "action": "take_profit_triggered",
                            "symbol": position_symbol,
                            "exit_price": current_price,
                        }
                    )

        return {
            "symbol": position_symbol,
            "actions_taken": actions_taken,
            "position_status": position["status"],
        }

    async def update_position_price_and_check(self, symbol: str, price: float) -> None:
        """Update position price and run SL/TP check (for WebSocket-driven path)."""
        self.position_manager.update_position(symbol, price)
        await self.manage_position(symbol)

    async def _validate_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Validate trade parameters."""
        symbol = trade.get("symbol")
        side = trade.get("side")
        quantity = trade.get("quantity")

        if not symbol or not side or quantity is None:
            return {"valid": False, "error": "Missing required trade parameters"}

        if side not in ["buy", "sell"]:
            return {"valid": False, "error": f"Invalid side: {side}"}

        if quantity <= 0:
            return {"valid": False, "error": f"Invalid quantity: {quantity}"}

        existing_position = self.position_manager.get_position(symbol)
        if existing_position and existing_position.get("status") == "open":
            return {"valid": False, "error": f"Open position already exists for {symbol}"}

        if quantity < self.execution_config["min_order_size"]:
            return {"valid": False, "error": f"Quantity below minimum: {quantity}"}

        # Additional validation could include:
        # - Account balance checks
        # - Position limits
        # - Symbol availability
        # - Market hours

        return {"valid": True}

    @staticmethod
    def _parse_delta_order_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Delta place_order response to a single order dict."""
        payload = result.get("result") if isinstance(result, dict) else None
        if not isinstance(payload, dict):
            return {}
        nested = payload.get("order")
        if isinstance(nested, dict):
            return nested
        return payload

    @staticmethod
    def _extract_filled_quantity(order_obj: Dict[str, Any], requested_qty: float) -> float:
        """Best-effort filled size from Delta order payload."""
        for key in ("filled_size", "filled_quantity", "filled_qty"):
            raw = order_obj.get(key)
            if raw is not None:
                try:
                    val = float(raw)
                    if val > 0:
                        return min(val, requested_qty)
                except (TypeError, ValueError):
                    continue
        try:
            total = float(order_obj.get("size") or requested_qty)
            unfilled = float(order_obj.get("unfilled_size") or 0.0)
            filled = max(0.0, total - unfilled)
            if filled > 0:
                return min(filled, requested_qty)
        except (TypeError, ValueError):
            pass
        state = str(order_obj.get("state") or "").lower()
        if state in ("closed", "filled"):
            return requested_qty
        return 0.0

    async def _poll_order_fill_status(
        self,
        *,
        symbol: str,
        exchange_order_id: Optional[int],
        requested_qty: float,
        attempts: int = 3,
        delay_seconds: float = 1.0,
    ) -> Tuple[float, Optional[float], str]:
        """Poll exchange for order fill progress."""
        if self.delta_client is None or exchange_order_id is None:
            return 0.0, None, "unknown"
        filled_qty = 0.0
        fill_price: Optional[float] = None
        state = "open"
        for _ in range(max(1, attempts)):
            await asyncio.sleep(delay_seconds)
            try:
                resp = await self.delta_client.get_orders(page_size=50)
                rows = resp.get("result") if isinstance(resp, dict) else None
                if not isinstance(rows, list):
                    continue
                match = next(
                    (r for r in rows if isinstance(r, dict) and r.get("id") == exchange_order_id),
                    None,
                )
                if not isinstance(match, dict):
                    continue
                state = str(match.get("state") or "open").lower()
                filled_qty = self._extract_filled_quantity(match, requested_qty)
                for key in ("average_fill_price", "avg_fill_price", "price"):
                    raw = match.get(key)
                    if raw is not None:
                        try:
                            fill_price = float(raw)
                            break
                        except (TypeError, ValueError):
                            continue
                if state in ("closed", "filled") or filled_qty >= requested_qty * 0.999:
                    break
            except Exception as exc:
                logger.debug(
                    "order_fill_poll_failed",
                    symbol=symbol,
                    exchange_order_id=exchange_order_id,
                    error=str(exc),
                )
        return filled_qty, fill_price, state

    @staticmethod
    def _delta_order_type_label(order_type: str) -> str:
        """Map internal order type to Delta API order_type string."""
        normalized = str(order_type or "market").lower()
        if normalized == "limit":
            return "LIMIT"
        if normalized == "stop":
            return "MARKET"
        return "MARKET"

    async def _place_order(self, symbol: str, side: str, quantity: float,
                          order_type: str, price: Optional[float] = None,
                          stop_price: Optional[float] = None,
                          reduce_only: bool = False) -> Dict[str, Any]:
        """Place market/limit/stop orders on Delta testnet via delta_client.place_order()."""
        try:
            order_id = str(uuid.uuid4())[:8]
            normalized_type = str(order_type or "market").lower()

            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=normalized_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
            )

            await asyncio.sleep(0.05)

            if not self.delta_client:
                return {"success": False, "error": "Delta client not configured for testnet trading"}

            if normalized_type == "limit" and (price is None or price <= 0):
                return {"success": False, "error": "Limit order requires a positive price"}
            if normalized_type == "stop" and (stop_price is None or stop_price <= 0):
                return {"success": False, "error": "Stop order requires a positive stop_price"}

            client_order_id = f"js_{order_id}"
            delta_order_type = self._delta_order_type_label(normalized_type)
            limit_price = float(price) if normalized_type == "limit" and price is not None else None
            trigger_price = (
                float(stop_price) if normalized_type == "stop" and stop_price is not None else None
            )

            result = await self.delta_client.place_order(
                symbol=symbol,
                side=side.upper(),
                quantity=quantity,
                order_type=delta_order_type,
                price=limit_price,
                stop_price=trigger_price,
                reduce_only=reduce_only,
                client_order_id=client_order_id,
            )
            order_obj = self._parse_delta_order_result(result)
            exchange_order_id = order_obj.get("id")
            if exchange_order_id is not None:
                try:
                    order.exchange_order_id = int(exchange_order_id)
                except (TypeError, ValueError):
                    pass

            fill_price: Optional[float] = None
            fill_keys = ("average_fill_price", "avg_fill_price", "price")
            if normalized_type != "market":
                fill_keys = fill_keys + ("limit_price",)
            for key in fill_keys:
                raw = order_obj.get(key)
                if raw is not None:
                    try:
                        fill_price = float(raw)
                        break
                    except (TypeError, ValueError):
                        continue
            if fill_price is None and limit_price is not None and limit_price > 0:
                fill_price = limit_price
            state = str(order_obj.get("state") or "").lower()
            filled_qty = self._extract_filled_quantity(order_obj, quantity)
            filled_immediately = state in ("closed", "filled") or filled_qty >= quantity * 0.999
            if not filled_immediately and filled_qty <= 0:
                polled_qty, polled_px, polled_state = await self._poll_order_fill_status(
                    symbol=symbol,
                    exchange_order_id=order.exchange_order_id,
                    requested_qty=quantity,
                    attempts=3,
                    delay_seconds=1.0,
                )
                if polled_qty > 0:
                    filled_qty = polled_qty
                    state = polled_state
                if polled_px is not None:
                    fill_price = polled_px
                filled_immediately = state in ("closed", "filled") or filled_qty >= quantity * 0.999
            partial_fill = filled_qty > 0 and not filled_immediately
            if filled_immediately and fill_price is None and normalized_type == "market":
                raise ValueError(
                    "Exchange order returned no fill price and no price parameter provided"
                )
            if filled_qty > 0 and fill_price is not None:
                order.update_fill(filled_qty, fill_price)
            self.order_manager.add_order(order)
            base_url = getattr(self.delta_client, "base_url", None)
            logger.info(
                "delta_testnet_order_placed",
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=normalized_type,
                reduce_only=reduce_only,
                exchange_order_id=order.exchange_order_id,
                delta_exchange_base_url=base_url,
                filled_immediately=filled_immediately,
                partial_fill=partial_fill,
                filled_quantity=filled_qty,
                average_fill_price=fill_price,
                exchange_state=state or None,
                stop_price=trigger_price,
            )
            return {
                "success": True,
                "order_id": order_id,
                "exchange_order_id": order.exchange_order_id,
                "filled_immediately": filled_immediately,
                "partial_fill": partial_fill,
                "filled_quantity": filled_qty,
                "requested_quantity": quantity,
                "average_fill_price": fill_price,
                "exchange_state": state or None,
            }

        except Exception as e:
            logger.error("order_placement_failed",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        order_type=order_type,
                        error=str(e))
            return {
                "success": False,
                "error": f"Order placement failed: {str(e)}"
            }

    async def _place_stop_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        label: str,
        tick_size: Optional[float] = None,
    ) -> Optional[str]:
        """Place a stop order."""
        if tick_size is not None and tick_size > 0:
            stop_price = round_to_tick(float(stop_price), float(tick_size))
        order_result = await self._place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="stop",
            stop_price=stop_price
        )

        if order_result["success"]:
            logger.debug("stop_order_placed",
                        symbol=symbol,
                        side=side,
                        stop_price=stop_price,
                        label=label)
            return order_result["order_id"]

        return None

    async def _place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        limit_price: float,
        label: str,
        tick_size: Optional[float] = None,
    ) -> Optional[str]:
        """Place a limit order."""
        if tick_size is not None and tick_size > 0:
            limit_price = round_to_tick(float(limit_price), float(tick_size))
        order_result = await self._place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type="limit",
            price=limit_price
        )

        if order_result["success"]:
            logger.debug("limit_order_placed",
                        symbol=symbol,
                        side=side,
                        limit_price=limit_price,
                        label=label)
            return order_result["order_id"]

        return None

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Cancel an open order (exchange API in live mode, local OrderManager otherwise)."""
        order = self.order_manager.get_order(order_id)
        sym = symbol or (order.symbol if order else None)

        if self.delta_client and sym:
            exchange_id: Optional[int] = None
            if order and order.exchange_order_id is not None:
                exchange_id = int(order.exchange_order_id)
            else:
                try:
                    exchange_id = int(order_id)
                except (TypeError, ValueError):
                    exchange_id = None
            if exchange_id is not None:
                try:
                    product_id = await self.delta_client.resolve_product_id(sym)
                    await self.delta_client.cancel_order(
                        exchange_id, product_id=product_id
                    )
                except Exception as exc:
                    logger.warning(
                        "exchange_cancel_order_failed",
                        order_id=order_id,
                        exchange_order_id=exchange_id,
                        symbol=sym,
                        error=str(exc),
                    )
                    return False

        return self.order_manager.cancel_order(order_id)

    async def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancel all open orders for a symbol on the exchange (live mode)."""
        if not self.delta_client:
            open_orders = self.order_manager.get_open_orders()
            cancelled = 0
            for oid, ord_obj in list(open_orders.items()):
                if ord_obj.symbol == symbol and self.order_manager.cancel_order(oid):
                    cancelled += 1
            return {"success": True, "cancelled_count": cancelled}

        try:
            product_id = await self.delta_client.resolve_product_id(symbol)
            result = await self.delta_client.cancel_all_orders(product_id=product_id)
            return {"success": True, "result": result}
        except Exception as exc:
            logger.error(
                "exchange_cancel_all_orders_failed",
                symbol=symbol,
                error=str(exc),
            )
            return {"success": False, "error": str(exc)}

    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an order."""
        order = self.order_manager.get_order(order_id)
        return order.to_dict() if order else None

    async def get_portfolio_status(self) -> Dict[str, Any]:
        """Get current portfolio status."""
        return {
            "positions": self.position_manager.get_all_positions(),
            "summary": self.position_manager.get_position_summary(),
            "open_orders": self.order_manager.get_open_orders()
        }

    async def get_health_status(self) -> Dict[str, Any]:
        """Get execution engine health status."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "initialized": self._initialized,
            "exchange_connected": self.exchange_connected,
            "open_positions": len(self.position_manager.get_all_positions()),
            "open_orders": len(self.order_manager.get_open_orders()),
            "execution_config": self.execution_config
        }


class OrderManager:
    """Manages trading orders."""

    def __init__(self):
        self.orders: Dict[str, Order] = {}

    def add_order(self, order: Order):
        """Add an order to management."""
        self.orders[order.order_id] = order

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        order = self.orders.get(order_id)
        if order:
            order.cancel()
            return True
        return False

    def get_open_orders(self) -> Dict[str, Any]:
        """Get all open orders."""
        return {order_id: order.to_dict() for order_id, order in self.orders.items()
                if order.status in ["pending", "open", "partially_filled"]}

    def update_order_fill(self, order_id: str, fill_quantity: float, fill_price: float):
        """Update order with a fill."""
        order = self.orders.get(order_id)
        if order:
            order.update_fill(fill_quantity, fill_price)


# Create global execution module instance
execution_module = ExecutionEngine()