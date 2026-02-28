"""
Execution Engine - Trade execution with order management.

Handles trade execution, order management, slippage control,
and integration with trading venues.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio
import uuid
import structlog

from agent.events.event_bus import event_bus
from agent.events.schemas import RiskApprovedEvent, OrderFillEvent, PositionClosedEvent, EventType
from agent.core.config import settings

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
        self.created_time = datetime.utcnow()
        self.updated_time = datetime.utcnow()
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
            timestamp = datetime.utcnow()

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
            self.updated_time = datetime.utcnow()

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
                     entry_price: float, order_id: str) -> Dict[str, Any]:
        """Open a new position."""
        position = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "entry_time": datetime.utcnow(),
            "current_price": entry_price,
            "unrealized_pnl": 0.0,
            "entry_order_id": order_id,
            "exit_order_id": None,
            "status": "open"
        }

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

            # Calculate unrealized P&L
            entry_value = position["entry_price"] * position["quantity"]
            current_value = current_price * position["quantity"]

            if position["side"] == "long":
                position["unrealized_pnl"] = current_value - entry_value
            else:  # short
                position["unrealized_pnl"] = entry_value - current_value

            position["updated_time"] = datetime.utcnow()

    def close_position(self, symbol: str, exit_price: float,
                      exit_order_id: str) -> Optional[Dict[str, Any]]:
        """Close an existing position."""
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # Calculate realized P&L
        entry_value = position["entry_price"] * position["quantity"]
        exit_value = exit_price * position["quantity"]

        if position["side"] == "long":
            realized_pnl = exit_value - entry_value
        else:  # short
            realized_pnl = entry_value - exit_value

        # Update position
        position.update({
            "exit_price": exit_price,
            "exit_time": datetime.utcnow(),
            "realized_pnl": realized_pnl,
            "exit_order_id": exit_order_id,
            "status": "closed"
        })

        logger.info("position_closed",
                   symbol=symbol,
                   realized_pnl=realized_pnl,
                   exit_price=exit_price)

        return position.copy()

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

        total_exposure = sum(pos["entry_price"] * pos["quantity"] for pos in open_positions.values())
        total_unrealized_pnl = sum(pos["unrealized_pnl"] for pos in open_positions.values())

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

        # Mock exchange integration (would be replaced with real exchange API)
        self.exchange_connected = False

    async def initialize(self, delta_client=None):
        """Initialize execution engine.

        Args:
            delta_client: Optional DeltaExchangeClient for paper/live trading
        """
        self.delta_client = delta_client
        # Initialize mock exchange connection
        await self._connect_exchange()
        self._initialized = True

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
            side_raw = payload.get("side", "BUY").upper()
            quantity = payload.get("quantity", 0)
            price = payload.get("price", 0)

            if not symbol or quantity <= 0:
                logger.warning(
                    "execution_risk_approved_invalid_payload",
                    symbol=symbol,
                    quantity=quantity,
                    event_id=event.event_id,
                )
                return

            # Normalize side to lowercase for execute_trade
            side = "buy" if side_raw == "BUY" else "sell"

            # Compute stop loss and take profit from config
            stop_loss = None
            take_profit = None
            if settings.stop_loss_percentage:
                if side == "buy":
                    stop_loss = price * (1 - settings.stop_loss_percentage)
                else:
                    stop_loss = price * (1 + settings.stop_loss_percentage)
            if settings.take_profit_percentage:
                if side == "buy":
                    take_profit = price * (1 + settings.take_profit_percentage)
                else:
                    take_profit = price * (1 - settings.take_profit_percentage)

            trade = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": "market",
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

            result = await self.execute_trade(trade)

            if not result.success:
                logger.warning(
                    "execution_risk_approved_trade_failed",
                    symbol=symbol,
                    side=side,
                    error=result.error_message,
                    event_id=event.event_id,
                )
                return

            # Publish OrderFillEvent for backend persistence and WebSocket broadcast
            fill_price = result.details.get("average_fill_price") or price
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
                    "timestamp": datetime.now(timezone.utc),
                },
            )
            await event_bus.publish(order_fill)

            if settings.paper_trading_mode:
                from agent.core.paper_trade_logger import paper_trade_logger
                paper_trade_logger.log_trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side_raw,
                    quantity=quantity,
                    fill_price=fill_price,
                    order_id=order_id,
                    reasoning_chain_id=payload.get("reasoning_chain_id"),
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

            # Validate trade parameters
            validation_result = await self._validate_trade(trade)
            if not validation_result["valid"]:
                return ExecutionResult(False, error_message=validation_result["error"])

            # Check if we need to close existing position first
            existing_position = self.position_manager.get_position(symbol)
            if existing_position and existing_position["side"] != ("long" if side == "buy" else "short"):
                # Close opposite position first
                await self.close_position(symbol, order_type="market")

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
                position = self.position_manager.open_position(
                    symbol=symbol,
                    side="long" if side == "buy" else "short",
                    quantity=quantity,
                    entry_price=fill_price,
                    order_id=order_id
                )

                # Place stop loss and take profit orders if specified
                if stop_loss:
                    await self._place_stop_order(symbol, "sell" if side == "buy" else "buy",
                                               quantity, stop_loss, "stop_loss")

                if take_profit:
                    await self._place_limit_order(symbol, "sell" if side == "buy" else "buy",
                                                quantity, take_profit, "take_profit")

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

    async def close_position(self, symbol: str, order_type: str = "market",
                           price: Optional[float] = None) -> ExecutionResult:
        """Close an existing position."""
        position = self.position_manager.get_position(symbol)
        if not position:
            return ExecutionResult(False, error_message=f"No open position for {symbol}")

        try:
            # Determine close side (opposite of position side)
            close_side = "sell" if position["side"] == "long" else "buy"

            # Execute close order
            order_result = await self._place_order(
                symbol=symbol,
                side=close_side,
                quantity=position["quantity"],
                order_type=order_type,
                price=price
            )

            if order_result["success"] and order_result["filled_immediately"]:
                exit_price = order_result["average_fill_price"]
                closed_position = self.position_manager.close_position(
                    symbol=symbol,
                    exit_price=exit_price,
                    exit_order_id=order_result["order_id"]
                )

                logger.info("position_closed_successfully",
                           symbol=symbol,
                           exit_price=exit_price,
                           realized_pnl=closed_position["realized_pnl"])

                # Publish PositionClosedEvent for backend persistence and paper trade log
                position_id = f"pos_{closed_position.get('entry_order_id', order_result.get('order_id', ''))}"
                pos_closed = PositionClosedEvent(
                    source="execution_engine",
                    payload={
                        "position_id": position_id,
                        "symbol": symbol,
                        "side": position["side"],
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "quantity": position["quantity"],
                        "pnl": closed_position["realized_pnl"],
                        "exit_reason": "market_close",
                        "timestamp": datetime.now(timezone.utc),
                    },
                )
                await event_bus.publish(pos_closed)

                if settings.paper_trading_mode:
                    from agent.core.paper_trade_logger import paper_trade_logger
                    paper_trade_logger.log_position_close(
                        position_id=position_id,
                        symbol=symbol,
                        side=position["side"],
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        quantity=position["quantity"],
                        pnl=closed_position["realized_pnl"],
                        exit_reason="market_close",
                    )

            return ExecutionResult(True, order_id=order_result.get("order_id"))

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
        if not position:
            return {"action": "none", "reason": "No position found"}

        actions_taken = []

        # Check stop loss and take profit levels
        # This would integrate with real-time price feeds
        # For now, return status
        current_price = position.get("current_price", position["entry_price"])

        # Simulate stop loss check (would use real price feed)
        stop_loss = position.get("stop_loss")
        take_profit = position.get("take_profit")

        if stop_loss:
            should_stop = (position["side"] == "long" and current_price <= stop_loss) or \
                         (position["side"] == "short" and current_price >= stop_loss)
            if should_stop:
                close_result = await self.close_position(position_symbol)
                if close_result.success:
                    actions_taken.append({
                        "action": "stop_loss_triggered",
                        "symbol": position_symbol,
                        "exit_price": current_price
                    })

        if take_profit:
            should_tp = (position["side"] == "long" and current_price >= take_profit) or \
                       (position["side"] == "short" and current_price <= take_profit)
            if should_tp:
                close_result = await self.close_position(position_symbol)
                if close_result.success:
                    actions_taken.append({
                        "action": "take_profit_triggered",
                        "symbol": position_symbol,
                        "exit_price": current_price
                    })

        return {
            "symbol": position_symbol,
            "actions_taken": actions_taken,
            "position_status": position["status"]
        }

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
                    base_price = await self._get_fill_price_paper(symbol, price)
                    # Simulate slippage
                    slippage = base_price * (self.execution_config["max_slippage_percent"] / 100.0) * (0.5 if side == "buy" else -0.5)
                    fill_price = base_price + slippage
                    order.update_fill(quantity, fill_price)
                    return {
                        "success": True,
                        "order_id": order_id,
                        "filled_immediately": True,
                        "average_fill_price": fill_price,
                        "slippage_percent": abs(slippage / base_price) * 100 if base_price else 0,
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

    async def _get_fill_price_paper(self, symbol: str, _price_hint: Optional[float] = None) -> float:
        """Get current market price for paper trading from Delta ticker. Raises if unavailable."""
        if not self.delta_client:
            raise ValueError("Delta client not configured; cannot get fill price for paper trade")
        ticker = await self.delta_client.get_ticker(symbol)
        result = ticker.get("result") or ticker
        if not isinstance(result, dict):
            raise ValueError(f"Ticker returned invalid data for {symbol}")
        close = result.get("close") or result.get("mark_price")
        if close is None:
            raise ValueError(f"Ticker has no close/mark_price for {symbol}")
        return float(close)

    async def _place_stop_order(self, symbol: str, side: str, quantity: float,
                               stop_price: float, label: str) -> Optional[str]:
        """Place a stop order."""
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

    async def _place_limit_order(self, symbol: str, side: str, quantity: float,
                                limit_price: float, label: str) -> Optional[str]:
        """Place a limit order."""
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