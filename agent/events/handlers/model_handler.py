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

            # Support both legacy flat payloads and the richer MCP orchestrator result
            predictions = payload.get("predictions")
            consensus_signal = payload.get("consensus_signal")
            consensus_confidence = payload.get("consensus_confidence")

            models_section = payload.get("models") or {}
            if predictions is None and isinstance(models_section, dict):
                predictions = models_section.get("predictions", [])
                # Use consensus values from models block when available
                if consensus_signal is None:
                    consensus_signal = models_section.get("consensus_prediction", 0.0)
                if consensus_confidence is None:
                    consensus_confidence = models_section.get("consensus_confidence", 0.0)

            if predictions is None:
                predictions = []

            # If the MCP orchestrator already produced a full decision for this event,
            # we skip triggering a second reasoning pass to avoid duplicate decisions.
            if event.source == "mcp_orchestrator" and isinstance(payload.get("decision"), dict):
                logger.info(
                    "model_prediction_complete_decision_already_emitted",
                    symbol=symbol,
                    prediction_count=len(predictions),
                    event_id=event.event_id,
                    message="Skipping reasoning because MCP orchestrator already emitted DecisionReadyEvent.",
                )
                return

            prediction_count = len(predictions)

            if prediction_count == 0:
                # Hard-stop: do not trigger reasoning when no model predictions
                logger.error(
                    "model_prediction_complete_no_predictions",
                    symbol=symbol,
                    prediction_count=prediction_count,
                    consensus_signal=consensus_signal or 0.0,
                    consensus_confidence=consensus_confidence or 0.0,
                    event_id=event.event_id,
                    message="ModelPredictionCompleteEvent received with zero predictions. Skipping reasoning.",
                )
                return

            # Update context with predictions
            await self.context_manager.update_state(
                {
                    "predictions": predictions
                }
            )

            # Trigger reasoning request only when predictions are available
            reasoning_request = ReasoningRequestEvent(
                source="model_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "market_context": {
                        "predictions": predictions,
                        "consensus_signal": consensus_signal or 0.0,
                        "consensus_confidence": consensus_confidence or 0.0,
                        "symbol": symbol,
                    },
                    "use_memory": True,
                },
            )

            await event_bus.publish(reasoning_request)

            logger.info(
                "model_prediction_complete_handled",
                symbol=symbol,
                prediction_count=prediction_count,
                consensus_signal=consensus_signal,
                event_id=event.event_id,
                reasoning_request_id=reasoning_request.event_id,
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

