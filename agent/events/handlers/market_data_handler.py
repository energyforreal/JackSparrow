"""
Market data event handler.

Handles market data events and triggers feature computation.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    MarketTickEvent,
    CandleClosedEvent,
    FeatureRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class MarketDataEventHandler:
    """Handler for market data events."""
    
    def __init__(self):
        """Initialize market data event handler."""
        self.context_manager = context_manager
    
    async def handle_market_tick(self, event: MarketTickEvent):
        """Handle market tick event.
        
        Args:
            event: Market tick event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            price = payload.get("price")
            volume = payload.get("volume")
            
            # Update context with latest price
            self.context_manager.update_context({
                "market_data": {
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "timestamp": payload.get("timestamp")
                }
            })
            
            logger.debug(
                "market_tick_handled",
                symbol=symbol,
                price=price,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "market_tick_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def handle_candle_closed(self, event: CandleClosedEvent):
        """Handle candle closed event.
        
        Args:
            event: Candle closed event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            interval = payload.get("interval")
            
            # Update context with candle data
            self.context_manager.update_context({
                "market_data": {
                    "symbol": symbol,
                    "interval": interval,
                    "open": payload.get("open"),
                    "high": payload.get("high"),
                    "low": payload.get("low"),
                    "close": payload.get("close"),
                    "volume": payload.get("volume"),
                    "timestamp": payload.get("timestamp")
                }
            })
            
            # Trigger feature computation
            feature_request = FeatureRequestEvent(
                source="market_data_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "feature_names": [
                        "rsi_14", "macd_signal", "bb_upper", "bb_lower",
                        "volume_sma", "price_sma", "volatility"
                    ],
                    "timestamp": payload.get("timestamp"),
                    "version": "latest"
                }
            )
            
            await event_bus.publish(feature_request)
            
            logger.info(
                "candle_closed_handled",
                symbol=symbol,
                interval=interval,
                close=payload.get("close"),
                event_id=event.event_id,
                feature_request_id=feature_request.event_id
            )
            
        except Exception as e:
            logger.error(
                "candle_closed_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.MARKET_TICK, self.handle_market_tick)
        event_bus.subscribe(EventType.CANDLE_CLOSED, self.handle_candle_closed)
        
        logger.info("market_data_handlers_registered")


# Global handler instance
market_data_handler = MarketDataEventHandler()

