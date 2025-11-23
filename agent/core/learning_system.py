"""Learning system for agent adaptation."""

from typing import Dict, Any, List
from datetime import datetime
import structlog

from agent.learning.performance_tracker import PerformanceTracker
from agent.learning.model_weight_adjuster import ModelWeightAdjuster
from agent.learning.confidence_calibrator import ConfidenceCalibrator
from agent.learning.strategy_adapter import StrategyAdapter
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    OrderFillEvent,
    PositionClosedEvent,
    ModelWeightUpdateEvent,
    StrategyAdaptationEvent,
    LearningCompleteEvent,
    EventType
)
from agent.models.mcp_model_registry import MCPModelRegistry

logger = structlog.get_logger()


class LearningSystem:
    """Learning system for agent adaptation."""
    
    def __init__(self, model_registry: MCPModelRegistry = None):
        """Initialize learning system."""
        self.performance_tracker = PerformanceTracker()
        self.weight_adjuster = ModelWeightAdjuster(self.performance_tracker)
        self.confidence_calibrator = ConfidenceCalibrator(self.performance_tracker)
        self.strategy_adapter = StrategyAdapter(self.performance_tracker)
        self.model_registry = model_registry
    
    async def initialize(self):
        """Initialize learning system and register event handlers."""
        event_bus.subscribe(EventType.ORDER_FILL, self._handle_order_fill)
        event_bus.subscribe(EventType.POSITION_CLOSED, self._handle_position_closed)
    
    async def shutdown(self):
        """Shutdown learning system."""
        pass
    
    async def _handle_order_fill(self, event: OrderFillEvent):
        """Handle order fill event for learning.
        
        Args:
            event: Order fill event
        """
        # Learning happens when position closes, not on fill
        pass
    
    async def _handle_position_closed(self, event: PositionClosedEvent):
        """Handle position closed event and trigger learning.
        
        Args:
            event: Position closed event
        """
        try:
            payload = event.payload
            position_id = payload.get("position_id")
            symbol = payload.get("symbol")
            entry_price = payload.get("entry_price")
            exit_price = payload.get("exit_price")
            pnl = payload.get("pnl")
            
            # Record trade outcome (simplified - would need to track which models contributed)
            # For now, record for all models
            if self.model_registry:
                model_names = list(self.model_registry.models.keys())
                for model_name in model_names:
                    # Calculate actual outcome direction
                    actual_outcome = 1.0 if pnl > 0 else -1.0
                    self.record_trade_outcome(
                        model_name=model_name,
                        prediction=0.0,  # Would need to track original prediction
                        actual_outcome=actual_outcome,
                        profit=pnl
                    )
            
            # Update model weights
            if self.model_registry:
                model_names = list(self.model_registry.models.keys())
                updated_weights = self.get_updated_weights(model_names)
                
                for model_name, new_weight in updated_weights.items():
                    old_weight = self.model_registry.model_weights.get(model_name, 1.0)
                    if abs(new_weight - old_weight) > 0.01:  # Significant change
                        self.model_registry.update_model_weight(model_name, new_weight)
                        
                        # Emit weight update event
                        weight_event = ModelWeightUpdateEvent(
                            source="learning_system",
                            payload={
                                "model_name": model_name,
                                "old_weight": old_weight,
                                "new_weight": new_weight,
                                "reason": f"Performance-based adjustment after trade {position_id}",
                                "timestamp": datetime.utcnow()
                            }
                        )
                        await event_bus.publish(weight_event)
            
            # Adapt strategy parameters
            adapted_params = self.get_adapted_strategy_params()
            if adapted_params:
                for param_name, new_value in adapted_params.items():
                    # Emit strategy adaptation event
                    adaptation_event = StrategyAdaptationEvent(
                        source="learning_system",
                        payload={
                            "parameter_name": param_name,
                            "old_value": None,  # Would track old value
                            "new_value": new_value,
                            "reason": f"Strategy adaptation after trade {position_id}",
                            "timestamp": datetime.utcnow()
                        }
                    )
                    await event_bus.publish(adaptation_event)
            
            # Emit learning complete event
            learning_event = LearningCompleteEvent(
                source="learning_system",
                correlation_id=event.event_id,
                payload={
                    "trade_id": position_id,
                    "performance_metrics": {
                        "pnl": pnl,
                        "return_pct": (pnl / entry_price) * 100 if entry_price > 0 else 0.0
                    },
                    "model_updates": [
                        {
                            "model_name": name,
                            "new_weight": weight
                        }
                        for name, weight in updated_weights.items()
                    ] if self.model_registry else [],
                    "timestamp": datetime.utcnow()
                }
            )
            await event_bus.publish(learning_event)
            
            logger.info(
                "learning_complete",
                position_id=position_id,
                pnl=pnl,
                event_id=learning_event.event_id
            )
            
        except Exception as e:
            logger.error(
                "learning_system_position_closed_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    def record_trade_outcome(
        self,
        model_name: str,
        prediction: float,
        actual_outcome: float,
        profit: float
    ):
        """Record trade outcome for learning."""
        self.performance_tracker.record_prediction(
            model_name=model_name,
            prediction=prediction,
            actual_outcome=actual_outcome,
            profit=profit
        )
    
    def get_updated_weights(self, model_names: List[str]) -> Dict[str, float]:
        """Get updated model weights based on performance."""
        return self.weight_adjuster.calculate_weights(model_names)
    
    def calibrate_confidence(
        self,
        raw_confidence: float,
        model_name: str,
        signal_strength: float
    ) -> float:
        """Calibrate confidence based on historical performance."""
        return self.confidence_calibrator.calibrate_confidence(
            raw_confidence=raw_confidence,
            model_name=model_name,
            signal_strength=signal_strength
        )
    
    def get_adapted_strategy_params(self) -> Dict[str, Any]:
        """Get adapted strategy parameters."""
        return self.strategy_adapter.adapt_parameters()

