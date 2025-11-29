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
    
    async def shutdown(self):
        """Shutdown execution module."""
        pass
    
    async def _handle_risk_approved(self, event: RiskApprovedEvent):
        """Handle risk approved event and execute trade.
        
        Args:
            event: Risk approved event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            side = payload.get("side")
            quantity = payload.get("quantity")
            price = payload.get("price")
            
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
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry_price": fill_price,
                        "timestamp": datetime.utcnow().isoformat()
                    }
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


# Global execution module instance
execution_module = ExecutionModule()

