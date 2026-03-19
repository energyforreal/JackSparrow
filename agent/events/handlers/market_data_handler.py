"""
Market data event handler.

Handles market data events and triggers feature computation.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    MarketTickEvent,
    CandleClosedEvent,
    PriceFluctuationEvent,
    FeatureRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.data.feature_list import get_feature_list

logger = structlog.get_logger()


class MarketDataEventHandler:
    """Handler for market data events."""
    
    def __init__(self):
        """Initialize market data event handler."""
        self.context_manager = context_manager

    @staticmethod
    def _get_runtime_feature_names() -> list[str]:
        """
        Resolve feature names for real-time pipeline requests.

        Prefer model-required features from the initialized orchestrator (v4 metadata
        order). Fall back to canonical feature list only if model requirements are
        unavailable (for example, early startup before model discovery completes).
        """
        try:
            from agent.core.mcp_orchestrator import mcp_orchestrator

            if mcp_orchestrator and mcp_orchestrator.model_registry:
                required = mcp_orchestrator.model_registry.get_required_feature_names()
                if required:
                    return list(required)
        except Exception:
            # Fall through to canonical list.
            pass
        return get_feature_list()
    
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
            await self.context_manager.update_state({
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
            await self.context_manager.update_state({
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
            
            # Trigger feature computation using model-required feature names first.
            runtime_feature_names = self._get_runtime_feature_names()
            feature_request = FeatureRequestEvent(
                source="market_data_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "current_price": payload.get("close"),
                    "feature_names": runtime_feature_names,
                    "timestamp": payload.get("timestamp"),
                    "version": "latest"
                }
            )
            
            await event_bus.publish(feature_request)
            
            logger.info(
                "candle_closed_handled",
                symbol=symbol,
                interval=interval,
                feature_count=len(runtime_feature_names),
                candle_timestamp=payload.get("timestamp"),
                close_price=payload.get("close"),
                message="Candle closed - triggering decision generation pipeline (features -> models -> reasoning -> decision)",
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

    async def handle_price_fluctuation(self, event: PriceFluctuationEvent):
        """Handle price fluctuation event and trigger ML pipeline.

        This triggers the same feature computation and prediction pipeline as candle close,
        but based on major price fluctuations instead of time-based intervals.

        Args:
            event: Price fluctuation event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            change_pct = payload.get("change_pct")
            threshold_pct = payload.get("threshold_pct")

            # Update context with fluctuation data
            await self.context_manager.update_state({
                "market_data": {
                    "symbol": symbol,
                    "price": payload.get("price"),
                    "previous_price": payload.get("previous_price"),
                    "change_pct": change_pct,
                    "volume": payload.get("volume"),
                    "timestamp": payload.get("timestamp"),
                    "fluctuation_triggered": True
                }
            })

            # Trigger feature computation using model-required feature names first.
            runtime_feature_names = self._get_runtime_feature_names()
            feature_request = FeatureRequestEvent(
                source="market_data_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "current_price": payload.get("price"),
                    "feature_names": runtime_feature_names,
                    "timestamp": payload.get("timestamp"),
                    "version": "latest"
                }
            )

            await event_bus.publish(feature_request)

            logger.info(
                "price_fluctuation_handled",
                symbol=symbol,
                change_pct=f"{change_pct:.2f}%",
                threshold_pct=f"{threshold_pct:.2f}%",
                feature_count=len(runtime_feature_names),
                price=payload.get("price"),
                message="Major price fluctuation detected - triggering ML pipeline (features -> models -> reasoning -> decision)",
                event_id=event.event_id,
                feature_request_id=feature_request.event_id
            )

        except Exception as e:
            logger.error(
                "price_fluctuation_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.MARKET_TICK, self.handle_market_tick)
        event_bus.subscribe(EventType.PRICE_FLUCTUATION, self.handle_price_fluctuation)
        event_bus.subscribe(EventType.CANDLE_CLOSED, self.handle_candle_closed)

        logger.info("market_data_handlers_registered")


# Global handler instance
market_data_handler = MarketDataEventHandler()

