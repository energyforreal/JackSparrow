"""
Market data event handler.

Handles market data events and triggers feature computation.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import structlog

from agent.events.schemas import (
    MarketTickEvent,
    CandleClosedEvent,
    PriceFluctuationEvent,
    FeatureRequestEvent,
    ModelPredictionRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.core.config import settings
from feature_store.feature_registry import get_feature_list

logger = structlog.get_logger()


class MarketDataEventHandler:
    """Handler for market data events."""
    
    def __init__(self):
        """Initialize market data event handler."""
        self.context_manager = context_manager

    @staticmethod
    def _get_model_registry():
        try:
            from agent.core.mcp_orchestrator import mcp_orchestrator

            if mcp_orchestrator and mcp_orchestrator.model_registry:
                return mcp_orchestrator.model_registry
        except Exception:
            pass
        return None

    @staticmethod
    def _get_runtime_feature_names() -> list[str]:
        """
        Resolve feature names for MCP feature-server pipeline requests.

        Transformer models compute features internally at inference time; when
        the registry is transformer-only this returns [] and callers should route
        directly to model prediction instead.
        """
        registry = MarketDataEventHandler._get_model_registry()
        if registry:
            servable = registry.get_mcp_servable_feature_names()
            if servable:
                return list(servable)
            if registry.uses_transformer_internal_features():
                return []
        return get_feature_list()

    @staticmethod
    async def emit_decision_pipeline_trigger(
        *,
        symbol: str,
        current_price: Any,
        trigger: str,
        correlation_id: Optional[str] = None,
        source: str = "market_data_handler",
        timestamp: Optional[datetime] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Emit the correct event to start the decision pipeline for the active registry.

        Transformer-only registries skip MCP feature server and publish
        ModelPredictionRequestEvent directly. Other registries use FeatureRequestEvent.
        """
        registry = MarketDataEventHandler._get_model_registry()
        ts = timestamp or datetime.now(timezone.utc)
        ctx: Dict[str, Any] = {"trigger": trigger, "symbol": symbol}
        if extra_context:
            ctx.update(extra_context)

        if registry and registry.uses_transformer_internal_features():
            model_request = ModelPredictionRequestEvent(
                source=source,
                correlation_id=correlation_id,
                payload={
                    "symbol": symbol,
                    "features": {},
                    "context": {
                        **ctx,
                        "current_price": current_price,
                    },
                    "require_explanation": True,
                },
            )
            await event_bus.publish(model_request)
            logger.debug(
                "decision_pipeline_transformer_direct",
                symbol=symbol,
                trigger=trigger,
                model_request_id=model_request.event_id,
            )
            return model_request.event_id

        runtime_feature_names = MarketDataEventHandler._get_runtime_feature_names()
        feature_request = FeatureRequestEvent(
            source=source,
            correlation_id=correlation_id,
            payload={
                "symbol": symbol,
                "current_price": current_price,
                "feature_names": runtime_feature_names,
                "timestamp": ts,
                "version": "latest",
                "context": ctx,
            },
        )
        await event_bus.publish(feature_request)
        logger.debug(
            "decision_pipeline_feature_request",
            symbol=symbol,
            trigger=trigger,
            feature_count=len(runtime_feature_names),
            feature_request_id=feature_request.event_id,
        )
        return feature_request.event_id
    
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
            if not bool(getattr(settings, "candle_close_trigger_enabled", True)):
                logger.debug(
                    "candle_close_trigger_disabled",
                    event_id=event.event_id,
                )
                return
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
            
            pipeline_id = await self.emit_decision_pipeline_trigger(
                symbol=symbol,
                current_price=payload.get("close"),
                trigger="candle_closed",
                correlation_id=event.event_id,
                timestamp=payload.get("timestamp"),
                extra_context={
                    "interval": interval,
                    "active_timeframes": settings.resolved_agent_timeframes(),
                },
            )

            logger.info(
                "candle_closed_handled",
                symbol=symbol,
                interval=interval,
                candle_timestamp=payload.get("timestamp"),
                close_price=payload.get("close"),
                message="Candle closed - triggering decision generation pipeline",
                event_id=event.event_id,
                pipeline_event_id=pipeline_id,
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
            if not bool(getattr(settings, "price_fluctuation_trigger_enabled", True)):
                logger.debug(
                    "price_fluctuation_trigger_disabled",
                    event_id=event.event_id,
                )
                return
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

            pipeline_id = await self.emit_decision_pipeline_trigger(
                symbol=symbol,
                current_price=payload.get("price"),
                trigger="price_fluctuation",
                correlation_id=event.event_id,
                timestamp=payload.get("timestamp"),
                extra_context={
                    "active_timeframes": settings.resolved_agent_timeframes(),
                },
            )

            logger.info(
                "price_fluctuation_handled",
                symbol=symbol,
                change_pct=f"{change_pct:.2f}%",
                threshold_pct=f"{threshold_pct:.2f}%",
                price=payload.get("price"),
                message="Major price fluctuation detected - triggering ML pipeline",
                event_id=event.event_id,
                pipeline_event_id=pipeline_id,
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
