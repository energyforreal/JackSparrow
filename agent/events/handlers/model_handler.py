"""
Model event handler.

Updates agent context when model prediction completes. Decision emission is
owned exclusively by MCPOrchestrator on MODEL_PREDICTION_REQUEST.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    ModelPredictionCompleteEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class ModelEventHandler:
    """Handler for model prediction complete events (context sync only)."""
    
    def __init__(self):
        """Initialize model event handler."""
        self.context_manager = context_manager
    
    async def handle_prediction_complete(self, event: ModelPredictionCompleteEvent):
        """Sync model predictions into agent context."""
        try:
            payload = event.payload
            symbol = payload.get("symbol")

            predictions = payload.get("predictions")
            models_section = payload.get("models") or {}
            if predictions is None and isinstance(models_section, dict):
                predictions = models_section.get("predictions", [])
            if predictions is None:
                predictions = []

            if not predictions:
                logger.debug(
                    "model_prediction_complete_no_predictions",
                    symbol=symbol,
                    event_id=event.event_id,
                )
                return

            await self.context_manager.update_state(
                {
                    "model_predictions": predictions,
                    "predictions": predictions,
                }
            )

            logger.info(
                "model_prediction_complete_handled",
                symbol=symbol,
                prediction_count=len(predictions),
                event_id=event.event_id,
                source=event.source,
            )
            
        except Exception as e:
            logger.error(
                "model_prediction_complete_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.MODEL_PREDICTION_COMPLETE, self.handle_prediction_complete)
        
        logger.info("model_handlers_registered")


# Global handler instance
model_handler = ModelEventHandler()
