"""
Model event handler.

Handles model prediction events and triggers reasoning.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    ModelPredictionCompleteEvent,
    ReasoningRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class ModelEventHandler:
    """Handler for model events."""
    
    def __init__(self):
        """Initialize model event handler."""
        self.context_manager = context_manager
    
    async def handle_prediction_complete(self, event: ModelPredictionCompleteEvent):
        """Handle model prediction complete event.
        
        Args:
            event: Model prediction complete event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            predictions = payload.get("predictions", [])
            consensus_signal = payload.get("consensus_signal", 0.0)
            consensus_confidence = payload.get("consensus_confidence", 0.0)
            
            # Update context with predictions
            self.context_manager.update_context({
                "predictions": predictions
            })
            
            # Trigger reasoning request
            reasoning_request = ReasoningRequestEvent(
                source="model_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "market_context": {
                        "predictions": predictions,
                        "consensus_signal": consensus_signal,
                        "consensus_confidence": consensus_confidence,
                        "symbol": symbol
                    },
                    "use_memory": True
                }
            )
            
            await event_bus.publish(reasoning_request)
            
            logger.info(
                "model_prediction_complete_handled",
                symbol=symbol,
                prediction_count=len(predictions),
                consensus_signal=consensus_signal,
                event_id=event.event_id,
                reasoning_request_id=reasoning_request.event_id
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

