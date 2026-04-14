"""
Execution Engine - Trade execution with order management.

Handles trade execution, order management, slippage control,
and integration with trading venues.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio
import math
import random
import time
import uuid
import structlog

from agent.events.event_bus import event_bus
from agent.events.schemas import RiskApprovedEvent, OrderFillEvent, PositionClosedEvent, EventType
from agent.core.config import settings
from agent.core.context_manager import context_manager
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

logger = structlog.get_logger()


class Order:
    """Represents a trading order."""

    def __init__(self, order_id: str, symbol: str, side: str, order_type: str,
                 quantity: float, price: Optional[float] = None,
                 stop_price: Optional[float] = None, time_in_force: str = "GTC"):
        self.order_id = order_id
        self.symbol = symbol
        self.side = side  # 'buy' or 'sell'
        self.order_type = order_type  # 'market', 'limit', 'stop', 'stop_limit'
        self.quantity = quantity
        self.price = price  # Limit price for limit orders
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

            position["updated_time"] = datetime.utcnow()

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
            "exit_time": datetime.utcnow(),
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
        self.execution_time = datetime.utcnow()
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

        # Mock exchange integration (would be replaced with real exchange API)
        self.exchange_connected = False
        self._position_lock = asyncio.Lock()

    async def initialize(self, delta_client=None, risk_manager=None):
        """Initialize execution engine.

        Args:
            delta_client: Optional DeltaExchangeClient for paper/live trading
            risk_manager: Optional RiskManager for portfolio sync on fill/close
        """
        self.delta_client = delta_client
        self.risk_manager = risk_manager
        # Initialize mock exchange connection
        await self._connect_exchange()
        self._initialized = True

        if getattr(settings, "paper_trading_mode", False):
            seed = getattr(settings, "paper_trading_random_seed", None)
            if seed is not None:
                random.seed(int(seed))

        # Subscribe to RiskApprovedEvent for automatic trade execution
        event_bus.subscribe(EventType.RISK_APPROVED, self._handle_risk_approved)

        logger.info("execution_engine_initialized",
                   config=self.execution_config,
                   exchange_connected=self.exchange_connected,
                   paper_trading_mode=settings.paper_trading_mode)

    async def shutdown(self):
        """Shutdown execution engine."""
        await self._disconnect_exchange()
        self._initialized = False
        logger.info("execution_engine_shutdown")

    async def _connect_exchange(self):
        """Connect to trading exchange (mock implementation)."""
        try:
            # Simulate connection delay
            await asyncio.sleep(0.1)
            self.exchange_connected = True
            logger.info("exchange_connected")
        except Exception as e:
            logger.error("exchange_connection_failed", error=str(e))
            self.exchange_connected = False

    async def _disconnect_exchange(self):
        """Disconnect from trading exchange."""
        self.exchange_connected = False
        logger.info("exchange_disconnected")

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
                    paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
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
                    paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
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
                    paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
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
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

            vd = payload.get("v15_diagnostics") or {}
            if vd and bool(getattr(settings, "v15_signal_logic_enabled", True)):
                extras: Dict[str, Any] = {}
                atr_raw = vd.get("atr_14")
                if atr_raw is not None:
                    try:
                        atr_f = float(atr_raw)
                        if atr_f > 0:
                            extras["v15_entry_atr"] = atr_f
                            extras["v15_trail_mult"] = float(
                                getattr(settings, "atr_trailing_mult", 2.0) or 2.0
                            )
                    except (TypeError, ValueError):
                        pass
                tf = str(vd.get("v15_timeframe") or "15m")
                bars = int(getattr(settings, "min_hold_bars", 0) or 0)
                if bars > 0:
                    tf_l = tf.strip().lower()
                    bar_sec = 900
                    if tf_l.endswith("m") and tf_l[:-1].isdigit():
                        bar_sec = int(tf_l[:-1]) * 60
                    extras["v15_min_hold_until"] = datetime.now(timezone.utc) + timedelta(
                        seconds=bars * bar_sec
                    )
                if extras:
                    trade["position_extras"] = extras

            pex = dict(trade.get("position_extras") or {})
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
                    paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
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
                    paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
                )
                return

            fill_price = result.details.get("average_fill_price") or price
            # SL/TP may have been rebased to fill inside execute_trade (paper mode)
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
                if settings.paper_trading_mode:
                    cv_pf = float(
                        pos.get("contract_value_btc")
                        or getattr(settings, "contract_value_btc", 0.001)
                    )
                    taker_pf = float(getattr(settings, "taker_fee_rate", 0.0005) or 0.0005)
                    slip_pf = float(getattr(settings, "slippage_bps", 5.0) or 5.0)
                    pos["entry_fee_usd"] = entry_leg_fees_usd(
                        float(fill_price),
                        float(quantity),
                        cv_pf,
                        taker_pf,
                        slip_pf,
                    )
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
                },
            )
            await event_bus.publish(order_fill)

            if settings.paper_trading_mode:
                from agent.core.paper_trade_logger import paper_trade_logger
                from agent.core.paper_trade_entry import (
                    compute_paper_entry_ledger,
                    resolve_paper_usdinr_rate,
                )

                rate = await resolve_paper_usdinr_rate(payload.get("usd_inr_rate"))
                contract_value_btc = float(
                    (pos or {}).get("contract_value_btc")
                    or getattr(settings, "contract_value_btc", 0.001)
                )
                ef_raw = (pos or {}).get("entry_fee_usd")
                entry_fee_opt = float(ef_raw) if ef_raw is not None else None
                trade_value_inr, fees_inr_open, _ = compute_paper_entry_ledger(
                    quantity=float(quantity),
                    fill_price=float(fill_price),
                    contract_value_btc=contract_value_btc,
                    usd_inr_rate=rate,
                    entry_fee_usd=entry_fee_opt,
                )
                paper_trade_logger.log_trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side_raw,
                    quantity=quantity,
                    fill_price=fill_price,
                    order_id=order_id,
                    reasoning_chain_id=payload.get("reasoning_chain_id"),
                    usd_inr_rate=rate,
                    trade_value_inr=trade_value_inr,
                    fees_inr=fees_inr_open,
                )

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
                paper_trading_mode=bool(getattr(settings, "paper_trading_mode", False)),
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
            return ExecutionResult(False, error_message="Exchange not connected")

        try:
            symbol = trade["symbol"]
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
                # In paper mode, allow a fresh ticker for the open leg so close and open use different fill prices
                if settings.paper_trading_mode:
                    await asyncio.sleep(0.05)

            # Validate trade parameters (after potential position close)
            validation_result = await self._validate_trade(trade)
            if not validation_result["valid"]:
                return ExecutionResult(False, error_message=validation_result["error"])

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

            # If order was filled immediately, update position
            if order_result["filled_immediately"]:
                fill_price = order_result["average_fill_price"]
                pex = trade.get("position_extras") or {}
                tick_sz: Optional[float] = None
                if pex.get("tick_size") is not None:
                    try:
                        tick_sz = float(pex["tick_size"])
                    except (TypeError, ValueError):
                        tick_sz = None
                if settings.paper_trading_mode and price is not None and fill_price is not None:
                    try:
                        pe = float(price)
                        fp = float(fill_price)
                        if pe > 0:
                            stop_loss, take_profit = rebase_sl_tp_to_fill(
                                pe, fp, stop_loss, take_profit, tick_sz
                            )
                            trade["stop_loss"] = stop_loss
                            trade["take_profit"] = take_profit
                    except (TypeError, ValueError):
                        pass
                position = self.position_manager.open_position(
                    symbol=symbol,
                    side="long" if side == "buy" else "short",
                    quantity=quantity,
                    entry_price=fill_price,
                    order_id=order_id,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_extras=trade.get("position_extras"),
                )

                # Place stop loss and take profit orders if specified
                if stop_loss:
                    await self._place_stop_order(
                        symbol,
                        "sell" if side == "buy" else "buy",
                        quantity,
                        stop_loss,
                        "stop_loss",
                        tick_size=tick_sz,
                    )

                if take_profit:
                    await self._place_limit_order(
                        symbol,
                        "sell" if side == "buy" else "buy",
                        quantity,
                        take_profit,
                        "take_profit",
                        tick_size=tick_sz,
                    )

            result = ExecutionResult(True, order_id=order_id)
            result.details = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "filled_immediately": order_result["filled_immediately"],
                "average_fill_price": order_result.get("average_fill_price"),
                "position_opened": order_result["filled_immediately"]
            }

            logger.info("trade_executed",
                       symbol=symbol,
                       side=side,
                       quantity=quantity,
                       order_id=order_id,
                       filled_immediately=order_result["filled_immediately"])

            return result

        except Exception as e:
            logger.error("trade_execution_failed",
                        trade=trade,
                        error=str(e))
            return ExecutionResult(False, error_message=f"Execution failed: {str(e)}")

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

        try:
            close_side = "sell" if position["side"] == "long" else "buy"

            order_result = await self._place_order(
                symbol=symbol,
                side=close_side,
                quantity=position.get("lots", position.get("quantity", 0)),
                order_type=order_type,
                price=price
            )

            if order_result["success"] and order_result.get("filled_immediately", False):
                exit_price = float(order_result["average_fill_price"])
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
                }
                if model_predictions is not None:
                    payload_data["model_predictions"] = model_predictions
                if reasoning_chain_id is not None:
                    payload_data["reasoning_chain_id"] = reasoning_chain_id
                if predicted_signal is not None:
                    payload_data["predicted_signal"] = predicted_signal
                if entry_time is not None:
                    payload_data["entry_time"] = entry_time
                pos_closed = PositionClosedEvent(
                    source="execution_engine",
                    payload=payload_data,
                )
                await event_bus.publish(pos_closed)

                if settings.paper_trading_mode:
                    from agent.core.paper_trade_logger import paper_trade_logger
                    from decimal import Decimal, ROUND_HALF_UP

                    fees_for_close_inr = (
                        fees_exit_usd * usdinr_exit
                        if mode != "round_trip"
                        else fees_usd * usdinr_exit
                    )
                    fees_inr = Decimal(str(fees_for_close_inr)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    net_pnl_inr = Decimal(str(net_usd * usdinr_exit)).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    margin_usd = (lots * entry_px * cv) / max(
                        1, int(getattr(settings, "isolated_margin_leverage", 5) or 5)
                    )
                    pnl_pct_margin = (net_usd / margin_usd) * 100.0 if margin_usd > 0 else 0.0
                    duration_seconds = None
                    if isinstance(position.get("entry_time"), datetime):
                        duration_seconds = (
                            datetime.now(timezone.utc) - position["entry_time"]
                        ).total_seconds()
                    paper_trade_logger.log_position_close(
                        position_id=position_id,
                        symbol=symbol,
                        side=position["side"],
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        quantity=position.get("lots", position.get("quantity", 0)),
                        pnl=net_usd,
                        exit_reason=exit_reason,
                        fees_inr=float(fees_inr),
                        net_pnl_inr=float(net_pnl_inr),
                        usd_inr_rate=usdinr_exit,
                        duration_seconds=duration_seconds,
                        gross_pnl_usd=gross_usd,
                        usdinr_at_entry=usdinr_entry,
                        fx_pnl_inr=float(
                            Decimal(str(fx_pnl_inr)).quantize(
                                Decimal("0.01"), rounding=ROUND_HALF_UP
                            )
                        ),
                        pnl_pct_on_margin=pnl_pct_margin,
                        reasoning_chain_id=reasoning_chain_id,
                    )

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

        # Paper isolated margin: liquidate when equity falls below maintenance margin
        if settings.paper_trading_mode and bool(
            getattr(settings, "enable_paper_liquidation", True)
        ):
            try:
                lev_pm = max(1, int(getattr(settings, "isolated_margin_leverage", 5) or 5))
                cv_pm = float(
                    position.get("contract_value_btc")
                    or getattr(settings, "contract_value_btc", 0.001)
                )
                lots_pm = float(position.get("lots", position.get("quantity", 0)))
                ep_pm = float(entry_price)
                if (
                    lots_pm > 0
                    and ep_pm > 0
                    and cv_pm > 0
                    and math.isfinite(float(current_price))
                ):
                    notional_usd = lots_pm * ep_pm * cv_pm
                    initial_margin_usd = notional_usd / lev_pm
                    upl = float(position.get("unrealized_pnl", 0.0))
                    eq = isolated_equity_usd(initial_margin_usd, upl)
                    maint_frac = float(
                        getattr(settings, "maintenance_fraction_of_initial", 0.5) or 0.5
                    )
                    maintenance_usd = initial_margin_usd * max(0.0, min(1.0, maint_frac))
                    if eq < maintenance_usd:
                        close_result = await self.close_position(
                            position_symbol, exit_reason="liquidation"
                        )
                        if close_result.success:
                            return {
                                "symbol": position_symbol,
                                "actions_taken": [
                                    {
                                        "action": "liquidation",
                                        "symbol": position_symbol,
                                        "exit_price": current_price,
                                        "equity_usd": eq,
                                        "maintenance_usd": maintenance_usd,
                                    }
                                ],
                                "position_status": "closed",
                            }
            except Exception as e:
                logger.warning(
                    "paper_liquidation_check_failed",
                    symbol=position_symbol,
                    error=str(e),
                )
        trail_pct = getattr(settings, "trailing_stop_percentage", 0.015) or 0.015
        act_pct = float(
            getattr(settings, "trailing_stop_activation_profit_pct", 0.0) or 0.0
        )

        min_hold_until = position.get("v15_min_hold_until")
        past_min_hold = True
        if min_hold_until is not None:
            now = datetime.now(timezone.utc)
            if hasattr(min_hold_until, "tzinfo") and min_hold_until.tzinfo:
                min_hold_dt = min_hold_until
            else:
                min_hold_dt = min_hold_until.replace(tzinfo=timezone.utc)
            past_min_hold = now >= min_hold_dt
            if not past_min_hold:
                logger.debug(
                    "min_hold_soft_exits_deferred",
                    symbol=position_symbol,
                    until=min_hold_until,
                    now=now,
                )

        v15_atr = position.get("v15_entry_atr")
        v15_mult = position.get("v15_trail_mult")
        v15_trail_active = False
        if past_min_hold and v15_atr is not None and v15_mult is not None:
            try:
                atr_v = float(v15_atr)
                mult_v = float(v15_mult)
            except (TypeError, ValueError):
                atr_v = 0.0
                mult_v = 0.0
            if atr_v > 0 and mult_v > 0:
                v15_trail_active = True
                if position["side"] == "long":
                    new_sl = current_price - mult_v * atr_v
                    if position.get("stop_loss") is None or new_sl > position["stop_loss"]:
                        position["stop_loss"] = new_sl
                        logger.info(
                            "v15_atr_trailing_stop_updated",
                            symbol=position_symbol,
                            new_stop=new_sl,
                        )
                elif position["side"] == "short":
                    new_sl = current_price + mult_v * atr_v
                    cur_sl = position.get("stop_loss")
                    if cur_sl is None or new_sl < cur_sl:
                        position["stop_loss"] = new_sl
                        logger.info(
                            "v15_atr_trailing_stop_updated",
                            symbol=position_symbol,
                            new_stop=new_sl,
                        )

        if past_min_hold and not v15_trail_active and position["side"] == "long" and current_price > entry_price:
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
        elif past_min_hold and not v15_trail_active and position["side"] == "short" and current_price < entry_price:
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

        if (
            past_min_hold
            and bool(getattr(settings, "v15_signal_logic_enabled", True))
            and position.get("v15_entry_atr") is not None
        ):
            st = context_manager.get_state()
            edge = getattr(st, "v15_live_edge", None) if st else None
            if edge is not None:
                try:
                    ef = float(edge)
                    th = float(getattr(settings, "edge_decay_threshold", 0.05) or 0.05)
                    if abs(ef) < th:
                        close_result = await self.close_position(
                            position_symbol, exit_reason="edge_decay"
                        )
                        if close_result.success:
                            actions_taken.append(
                                {
                                    "action": "edge_decay_exit",
                                    "symbol": position_symbol,
                                    "exit_price": current_price,
                                    "edge": ef,
                                }
                            )
                            return {
                                "symbol": position_symbol,
                                "actions_taken": actions_taken,
                                "position_status": "closed",
                            }
                except (TypeError, ValueError):
                    pass

        if stop_loss:
            should_stop = (position["side"] == "long" and current_price <= stop_loss) or (
                position["side"] == "short" and current_price >= stop_loss
            )
            if should_stop:
                sl_reason = (
                    "atr_trail_stop"
                    if position.get("v15_entry_atr") is not None
                    else "stop_loss_hit"
                )
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

    async def _place_order(self, symbol: str, side: str, quantity: float,
                          order_type: str, price: Optional[float] = None,
                          stop_price: Optional[float] = None) -> Dict[str, Any]:
        """Place an order with the exchange.

        In paper trading mode: fetches current price from Delta ticker,
        simulates fill without calling place_order. Fails if ticker price unavailable.
        In live mode: calls delta_client.place_order().
        """
        try:
            order_id = str(uuid.uuid4())[:8]

            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price
            )

            await asyncio.sleep(0.05)

            if order_type == "market":
                # Get fill price: paper mode uses ticker; live uses real order
                if settings.paper_trading_mode:
                    base_price = await self._get_fill_price_paper(symbol, price_hint=price)
                    max_pct = self.execution_config["max_slippage_percent"] / 100.0
                    slippage_pct = random.uniform(0.1 * max_pct, max_pct)
                    half_spread = getattr(settings, "half_spread_pct", 0.0002)
                    if side == "buy":
                        fill_price = base_price * (1 + half_spread + slippage_pct)
                    else:
                        fill_price = base_price * (1 - half_spread - slippage_pct)
                    order.update_fill(quantity, fill_price)
                    return {
                        "success": True,
                        "order_id": order_id,
                        "filled_immediately": True,
                        "average_fill_price": fill_price,
                        "slippage_percent": abs(fill_price - base_price) / base_price * 100 if base_price else 0,
                    }
                else:
                    # Live trading
                    if self.delta_client:
                        result = await self.delta_client.place_order(
                            symbol=symbol,
                            side=side.upper(),
                            quantity=quantity,
                            order_type="MARKET",
                        )
                        if result.get("result") and result["result"].get("order", {}).get("average_fill_price"):
                            fill_price = float(result["result"]["order"]["average_fill_price"])
                        elif price is not None and price > 0:
                            fill_price = price
                        else:
                            order_price = result.get("result", {}).get("order", {}).get("price")
                            if order_price is not None:
                                fill_price = float(order_price)
                            else:
                                raise ValueError(
                                    "Live order returned no fill price and no price parameter provided"
                                )
                        order.update_fill(quantity, fill_price)
                        return {
                            "success": True,
                            "order_id": order_id,
                            "filled_immediately": True,
                            "average_fill_price": fill_price,
                    }
                    else:
                        return {"success": False, "error": "Delta client not configured for live trading"}

            else:
                self.order_manager.add_order(order)
                return {
                    "success": True,
                    "order_id": order_id,
                    "filled_immediately": False
                }

        except Exception as e:
            logger.error("order_placement_failed",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        error=str(e))
            return {
                "success": False,
                "error": f"Order placement failed: {str(e)}"
            }

    def _anchor_paper_reference_mid(
        self,
        symbol: str,
        ticker_mid: float,
        price_hint: Optional[float],
    ) -> float:
        """Clamp ticker mid to within max_slippage_percent of approval/reference price (when hint set)."""
        if price_hint is None:
            return ticker_mid
        try:
            hint = float(price_hint)
        except (TypeError, ValueError):
            return ticker_mid
        if hint <= 0 or not math.isfinite(hint) or not math.isfinite(ticker_mid):
            return ticker_mid
        max_frac = float(self.execution_config.get("max_slippage_percent", 0.5)) / 100.0
        lo = hint * (1.0 - max_frac)
        hi = hint * (1.0 + max_frac)
        anchored = min(hi, max(lo, ticker_mid))
        if abs(anchored - ticker_mid) > 1e-9:
            logger.debug(
                "paper_fill_reference_mid_clamped_to_hint_band",
                symbol=symbol,
                ticker_mid=ticker_mid,
                price_hint=hint,
                anchored_mid=anchored,
                max_slippage_percent=self.execution_config.get("max_slippage_percent"),
            )
        return anchored

    async def _get_fill_price_paper(
        self, symbol: str, price_hint: Optional[float] = None
    ) -> float:
        """Reference mid for paper fill: Delta ticker (freshness-checked), clamped to hint band.

        If ticker cannot be used but ``price_hint`` is a valid positive price, returns the hint
        and logs ``paper_fill_price_ticker_unavailable_using_hint`` (audit/reconciliation).
        """
        if not self.delta_client:
            if price_hint is not None:
                try:
                    h = float(price_hint)
                    if h > 0 and math.isfinite(h):
                        logger.warning(
                            "paper_fill_price_ticker_unavailable_using_hint",
                            symbol=symbol,
                            reason="no_delta_client",
                            price_hint=h,
                        )
                        return h
                except (TypeError, ValueError):
                    pass
            raise ValueError("Delta client not configured; cannot get fill price for paper trade")

        try:
            ticker = await self.delta_client.get_ticker(symbol)
            result = ticker.get("result") or ticker
            if not isinstance(result, dict):
                raise ValueError(f"Ticker returned invalid data for {symbol}")
            ticker_ts_raw = result.get("timestamp")
            if ticker_ts_raw is None:
                raise ValueError(f"Ticker for {symbol} has no timestamp; cannot validate freshness")

            ticker_ts = float(ticker_ts_raw)
            if ticker_ts > 1e10:
                ticker_ts /= 1000.0

            max_age_s = float(getattr(settings, "paper_ticker_max_age_seconds", 10.0) or 10.0)
            age_s = time.time() - ticker_ts
            if age_s > max_age_s:
                if getattr(settings, "paper_fill_price_fallback_enabled", True):
                    context_price = self._get_context_price(symbol)
                    if context_price is not None and context_price > 0:
                        logger.warning(
                            "paper_fill_price_fallback_used",
                            symbol=symbol,
                            ticker_age_s=round(age_s, 3),
                            max_age_s=max_age_s,
                            fallback_price=context_price,
                        )
                        mid = float(context_price)
                        return self._anchor_paper_reference_mid(symbol, mid, price_hint)
                raise ValueError(
                    f"Stale ticker for {symbol}, age={age_s:.1f}s (max={max_age_s:.1f}s)"
                )
            mark = result.get("mark_price")
            close = result.get("close")
            raw = float(mark) if mark is not None else (float(close) if close is not None else None)
            if raw is None:
                raise ValueError(f"Ticker has no mark_price/close for {symbol}")
            mid = self._anchor_paper_reference_mid(symbol, raw, price_hint)
            return mid
        except Exception as exc:
            if price_hint is not None:
                try:
                    h = float(price_hint)
                    if h > 0 and math.isfinite(h):
                        logger.warning(
                            "paper_fill_price_ticker_unavailable_using_hint",
                            symbol=symbol,
                            reason=str(exc),
                            price_hint=h,
                        )
                        return h
                except (TypeError, ValueError):
                    pass
            raise

    def _get_context_price(self, symbol: str) -> Optional[float]:
        """Best-effort fallback to latest in-memory market price."""
        try:
            state = context_manager.get_state()
            if state and hasattr(state, "config") and isinstance(state.config, dict):
                md = state.config.get("market_data", {})
                if isinstance(md, dict):
                    price = md.get("price")
                    if price is not None:
                        return float(price)
            if state and hasattr(state, "market_data") and isinstance(state.market_data, dict):
                price = state.market_data.get("price")
                if price is not None:
                    return float(price)
        except Exception:
            return None
        return None

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

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        return self.order_manager.cancel_order(order_id)

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