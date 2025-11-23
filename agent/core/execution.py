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
                logger.warning(
                    "paper_trading_mode_disabled",
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
                    message="Executing trade in paper trading mode"
                )
            
            try:
                # Place order via Delta Exchange
                # In paper trading mode, use testnet/sandbox API if available
                # For now, the delta_client should handle this based on base_url
                if settings.paper_trading_mode:
                    logger.debug(
                        "executing_paper_trade",
                        symbol=symbol,
                        side=side,
                        quantity=quantity
                    )
                
                result = await self.delta_client.place_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    order_type="MARKET",
                    price=None
                )
                
                # Simulate order fill (in real implementation, wait for exchange confirmation)
                trade_id = result.get("id", str(uuid.uuid4()))
                fill_price = price  # Use requested price or market price
                
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
                
                logger.error(
                    "trade_execution_failed",
                    order_id=order_id,
                    symbol=symbol,
                    error=str(e),
                    exc_info=True
                )
                
        except Exception as e:
            logger.error(
                "execution_module_risk_approved_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )


# Global execution module instance
execution_module = ExecutionModule()

