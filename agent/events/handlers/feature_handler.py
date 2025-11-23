"""
Feature event handler.

Handles feature events and triggers model predictions.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    FeatureRequestEvent,
    FeatureComputedEvent,
    ModelPredictionRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class FeatureEventHandler:
    """Handler for feature events."""
    
    def __init__(self):
        """Initialize feature event handler."""
        self.context_manager = context_manager
    
    async def handle_feature_computed(self, event: FeatureComputedEvent):
        """Handle feature computed event.
        
        Args:
            event: Feature computed event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            features = payload.get("features", {})
            quality_score = payload.get("quality_score", 0.0)
            
            # Update context with features
            self.context_manager.update_context({
                "features": features
            })
            
            # Trigger model prediction request
            model_request = ModelPredictionRequestEvent(
                source="feature_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "features": features,
                    "context": {
                        "feature_quality_score": quality_score,
                        "symbol": symbol
                    },
                    "require_explanation": True
                }
            )
            
            await event_bus.publish(model_request)
            
            logger.info(
                "feature_computed_handled",
                symbol=symbol,
                feature_count=len(features),
                quality_score=quality_score,
                event_id=event.event_id,
                model_request_id=model_request.event_id
            )
            
        except Exception as e:
            logger.error(
                "feature_computed_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.FEATURE_COMPUTED, self.handle_feature_computed)
        
        logger.info("feature_handlers_registered")


# Global handler instance
feature_handler = FeatureEventHandler()

