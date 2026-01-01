"""
Execution module for trade execution.

Handles trade execution via Delta Exchange API.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import structlog

from agent.data.delta_client import DeltaExchangeClient
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    RiskApprovedEvent,
    OrderSubmittedEvent,
    OrderFillEvent,
    ExecutionFailedEvent,
    PositionClosedEvent,
    EventType
)
from agent.core.context_manager import context_manager
from agent.core.config import settings
from agent.core.logging_utils import log_error_with_context, log_warning_with_context, log_exception

logger = structlog.get_logger()


class ExecutionModule:
    """Execution module for trade execution."""
    
    def __init__(self):
        """Initialize execution module."""
        self.delta_client = DeltaExchangeClient()
        self.context_manager = context_manager
    
    async def initialize(self):
        """Initialize execution module and register event handlers."""
        event_bus.subscribe(EventType.RISK_APPROVED, self._handle_risk_approved)
        event_bus.subscribe(EventType.DECISION_READY, self._handle_exit_decision)
    
    async def shutdown(self):
        """Shutdown execution module."""
        pass
    
    async def _handle_risk_approved(self, event: RiskApprovedEvent):
        """Handle risk approved event and execute trade.
        
        Args:
            event: Risk approved event
        """
        # EXECUTION: Entry logging with decision context
        logger.info("EXECUTION: Entered execute_trade with decision=%s", event)
        
        # EXECUTION: Validate event is not None
        if event is None:
            logger.warning("EXECUTION: Skipping trade — decision is None")
            return
        
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            side = payload.get("side")
            quantity = payload.get("quantity")
            price = payload.get("price")
            
            logger.info(
                "execution_risk_approved_received",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                paper_trading_mode=settings.paper_trading_mode,
                event_id=event.event_id,
                message="ExecutionModule received RiskApprovedEvent - starting trade execution"
            )
            
            # Validate inputs
            if not symbol:
                logger.error(
                    "execution_invalid_symbol",
                    event_id=event.event_id,
                    symbol=symbol,
                    message="Symbol is missing or empty - cannot execute trade"
                )
                return
            
            if not side or side.upper() not in ["BUY", "SELL"]:
                logger.error(
                    "execution_invalid_side",
                    event_id=event.event_id,
                    side=side,
                    message="Side is missing or invalid - cannot execute trade"
                )
                return
            
            if quantity is None or quantity <= 0:
                logger.error(
                    "execution_invalid_quantity",
                    event_id=event.event_id,
                    symbol=symbol,
                    quantity=quantity,
                    message="Quantity is missing, zero, or negative - cannot execute trade"
                )
                return
            
            if price is None or price <= 0:
                logger.warning(
                    "execution_invalid_price",
                    event_id=event.event_id,
                    symbol=symbol,
                    price=price,
                    message="Price is missing or invalid - will attempt to fetch from market"
                )
                # Will try to fetch price from ticker below
            
            # EXECUTION: Check features are available before trade execution
            context = self.context_manager.get_current_context()
            if context.features is None or len(context.features) == 0:
                logger.warning("EXECUTION: Features missing — aborting trade")
                return
            
            # Execute trade
            order_id = str(uuid.uuid4())
            
            # Emit order submitted event
            submitted_event = OrderSubmittedEvent(
                source="execution_module",
                correlation_id=event.event_id,
                payload={
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "timestamp": datetime.utcnow()
                }
            )
            await event_bus.publish(submitted_event)
            
            # Verify paper trading mode before executing trades
            if not settings.paper_trading_mode:
                log_warning_with_context(
                    "paper_trading_mode_disabled",
                    component="execution_module",
                    correlation_id=event.event_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    message="PAPER_TRADING_MODE is False - real trades will be executed!"
                )
                # In production, you might want to add additional confirmation here
            else:
                logger.info(
                    "paper_trading_mode_enabled",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    message="Executing trade in paper trading mode - no real exchange API calls will be made"
                )
            
            try:
                # In paper trading mode, simulate trade execution without calling exchange API
                if settings.paper_trading_mode:
                    logger.debug(
                        "executing_paper_trade",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        message="Simulating trade execution (paper trading mode)"
                    )
                    
                    # Simulate order placement - get current market price for realistic simulation
                    try:
                        ticker = await self.delta_client.get_ticker(symbol)
                        simulated_price = ticker.get("close") if ticker else price
                    except Exception:
                        # If ticker fetch fails, use provided price or a default
                        simulated_price = price if price else 50000.0  # Fallback price
                        log_warning_with_context(
                            "paper_trade_ticker_fetch_failed",
                            component="execution_module",
                            correlation_id=event.event_id,
                            symbol=symbol,
                            order_id=order_id,
                            message="Using fallback price for paper trade simulation"
                        )
                    
                    # Simulate order result
                    result = {
                        "id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "price": simulated_price,
                        "status": "filled",
                        "paper_trading": True
                    }
                else:
                    # Real trading mode - place actual order via Delta Exchange
                    logger.info(
                        "executing_real_trade",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        message="Placing real order on exchange (PAPER_TRADING_MODE=False)"
                    )
                    
                    result = await self.delta_client.place_order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        order_type="MARKET",
                        price=None
                    )
                
                # Extract trade details from result
                trade_id = result.get("id", str(uuid.uuid4()))
                fill_price = result.get("price", price)  # Use price from result or requested price
                
                logger.info(
                    "execution_trade_result",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    requested_price=price,
                    fill_price=fill_price,
                    paper_trading_mode=settings.paper_trading_mode,
                    trade_id=trade_id,
                    order_id=order_id,
                )
                
                # Validate fill_price before emitting event
                if fill_price <= 0:
                    logger.error(
                        "execution_invalid_fill_price",
                        order_id=order_id,
                        trade_id=trade_id,
                        symbol=symbol,
                        fill_price=fill_price,
                        requested_price=price,
                        message="Fill price is invalid - cannot emit OrderFillEvent"
                    )
                    raise ValueError(f"Invalid fill price: {fill_price}")
                
                logger.info(
                    "execution_emitting_order_fill",
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price,
                    message="Emitting OrderFillEvent - trade execution successful"
                )
                
                # Emit order fill event
                fill_event = OrderFillEvent(
                    source="execution_module",
                    correlation_id=event.event_id,
                    payload={
                        "order_id": order_id,
                        "trade_id": trade_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "fill_price": fill_price,
                        "timestamp": datetime.utcnow()
                    }
                )
                await event_bus.publish(fill_event)
                
                # EXECUTION: Order filled confirmation logging
                logger.info(
                    "EXECUTION: Order filled — id=%s qty=%s price=%s side=%s",
                    order_id, quantity, fill_price, side
                )
                
                logger.info(
                    "execution_order_fill_event_published",
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    fill_event_id=fill_event.event_id,
                    message="OrderFillEvent published successfully"
                )
                
                # Calculate stop loss and take profit levels
                from agent.risk.risk_manager import RiskManager
                risk_manager = RiskManager()
                stop_loss_price = risk_manager.calculate_stop_loss(fill_price, side)
                take_profit_price = risk_manager.calculate_take_profit(fill_price, side)
                
                # Generate position_id for tracking
                position_id = str(uuid.uuid4())
                
                # Update context
                self.context_manager.update_context({
                    "trade": {
                        "order_id": order_id,
                        "trade_id": trade_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "price": fill_price
                    },
                    "position": {
                        "position_id": position_id,
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry_price": fill_price,
                        "stop_loss": stop_loss_price,
                        "take_profit": take_profit_price,
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    "position_opened": True
                })
                
                logger.info(
                    "trade_executed",
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price
                )
                
            except Exception as e:
                # Emit execution failed event
                failed_event = ExecutionFailedEvent(
                    source="execution_module",
                    correlation_id=event.event_id,
                    payload={
                        "order_id": order_id,
                        "symbol": symbol,
                        "reason": "Order execution failed",
                        "error": str(e),
                        "timestamp": datetime.utcnow()
                    }
                )
                await event_bus.publish(failed_event)
                
                log_error_with_context(
                    "trade_execution_failed",
                    error=e,
                    component="execution_module",
                    correlation_id=event.event_id,
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price
                )
                
        except Exception as e:
            log_error_with_context(
                "execution_module_risk_approved_error",
                error=e,
                component="execution_module",
                correlation_id=event.event_id if hasattr(event, "event_id") else None,
                event_type=event.event_type.value if hasattr(event, "event_type") else None
            )
    
    async def _handle_exit_decision(self, event):
        """Handle exit decision event to close position.
        
        Only processes exit decisions that originate from the risk manager
        with an explicit exit_reason field. This prevents incorrectly closing
        positions when the reasoning engine generates legitimate opposite signals.
        
        Args:
            event: DecisionReadyEvent with exit_reason field indicating exit
        """
        from agent.events.schemas import DecisionReadyEvent
        
        # Only handle DecisionReadyEvent instances
        if not isinstance(event, DecisionReadyEvent):
            return
        
        payload = event.payload
        
        # Only process exit decisions that have an explicit exit_reason field
        # This ensures we only process exits from the risk manager, not new
        # trading signals from the reasoning engine.
        # 
        # The reasoning engine emits DECISION_READY events without exit_reason
        # (these are new trading signals, not exits). The risk manager emits
        # DECISION_READY events with exit_reason when stop loss/take profit
        # conditions are met.
        exit_reason = payload.get("exit_reason")
        if not exit_reason:
            # This is not an exit decision (no exit_reason field), ignore it
            # This prevents incorrectly closing positions when the reasoning
            # engine generates legitimate opposite signals (e.g., SELL when
            # holding BUY position as a new trading signal, not an exit)
            return
        
        # Verify source is risk_manager for additional safety
        # Only the risk manager should emit exit decisions with exit_reason
        if event.source != "risk_manager":
            logger.warning(
                "exit_decision_rejected_unexpected_source",
                event_id=event.event_id,
                source=event.source,
                exit_reason=exit_reason,
                message="Exit decision rejected: unexpected source (expected risk_manager)"
            )
            return
        
        # Verify we have a position to close
        context = self.context_manager.get_current_context()
        if not context.position:
            logger.debug(
                "exit_decision_ignored_no_position",
                event_id=event.event_id,
                exit_reason=exit_reason,
                source=event.source,
                message="Exit decision received but no active position to close"
            )
            return
        
        try:
            symbol = payload.get("symbol") or context.position.get("symbol")
            position_quantity = context.position.get("quantity", 0.0)
            entry_price = context.position.get("entry_price", 0.0)
            entry_timestamp_str = context.position.get("timestamp")
            position_side = context.position.get("side")
            
            # Calculate exit side (opposite of entry)
            exit_side = "SELL" if position_side == "BUY" else "BUY"
            
            # Get current price for exit
            try:
                ticker = await self.delta_client.get_ticker(symbol)
                exit_price = ticker.get("close") if ticker else entry_price
            except Exception:
                exit_price = entry_price
            
            order_id = str(uuid.uuid4())
            
            # Execute exit trade
            if settings.paper_trading_mode:
                # Simulate exit trade
                result = {
                    "id": str(uuid.uuid4()),
                    "symbol": symbol,
                    "side": exit_side,
                    "quantity": position_quantity,
                    "price": exit_price,
                    "status": "filled",
                    "paper_trading": True
                }
            else:
                # Real exit trade
                result = await self.delta_client.place_order(
                    symbol=symbol,
                    side=exit_side,
                    quantity=position_quantity,
                    order_type="MARKET",
                    price=None
                )
            
            trade_id = result.get("id", str(uuid.uuid4()))
            fill_price = result.get("price", exit_price)
            
            # Calculate PnL
            # position_quantity is in dollars (USD value), need to convert to asset quantity
            # Asset quantity = dollar quantity / entry_price
            if entry_price > 0:
                asset_quantity = position_quantity / entry_price
            else:
                asset_quantity = 0.0
                logger.warning(
                    "pnl_calculation_invalid_entry_price",
                    symbol=symbol,
                    entry_price=entry_price,
                    message="Entry price is zero or invalid, PnL calculation may be incorrect"
                )
            
            # Calculate PnL using asset quantity
            if position_side == "BUY":
                # Long position: profit when exit_price > entry_price
                pnl = (fill_price - entry_price) * asset_quantity
            else:
                # Short position: profit when exit_price < entry_price
                pnl = (entry_price - fill_price) * asset_quantity
            
            # Calculate duration
            duration_seconds = 0.0
            if entry_timestamp_str:
                try:
                    entry_timestamp = datetime.fromisoformat(entry_timestamp_str.replace('Z', '+00:00'))
                    duration_seconds = (datetime.utcnow() - entry_timestamp.replace(tzinfo=None)).total_seconds()
                except Exception:
                    pass
            
            # Exit reason is already present in payload (from risk manager)
            # This is guaranteed by the check at the start of the function
            # Use the exit_reason from payload, which was already extracted above
            
            # Get position_id from context or generate one
            position_id = context.position.get("position_id") if context.position else None
            if not position_id:
                # Try to find position_id from database using symbol and entry_price
                # For now, generate a new one if not found
                position_id = str(uuid.uuid4())
                logger.warning(
                    "position_id_not_found_in_context",
                    symbol=symbol,
                    entry_price=entry_price,
                    message="Position ID not found in context, using generated ID"
                )
            
            # Emit PositionClosedEvent
            position_closed_event = PositionClosedEvent(
                source="execution_module",
                correlation_id=event.event_id,
                payload={
                    "position_id": position_id,
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "exit_price": fill_price,
                    "pnl": pnl,
                    "duration_seconds": duration_seconds,
                    "exit_reason": exit_reason,
                    "timestamp": datetime.utcnow()
                }
            )
            await event_bus.publish(position_closed_event)
            
            # Clear position from context and set position_closed flag
            self.context_manager.update_context({
                "position": None,
                "position_opened": False,
                "position_closed": True
            })
            
            logger.info(
                "position_closed",
                position_id=position_closed_event.payload["position_id"],
                symbol=symbol,
                entry_price=entry_price,
                exit_price=fill_price,
                pnl=pnl,
                exit_reason=exit_reason,
                event_id=position_closed_event.event_id
            )
            
        except Exception as e:
            log_error_with_context(
                "exit_trade_execution_failed",
                error=e,
                component="execution_module",
                correlation_id=event.event_id if hasattr(event, "event_id") else None,
                symbol=context.position.get("symbol") if context.position else None
            )


# Global execution module instance
execution_module = ExecutionModule()

