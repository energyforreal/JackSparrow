"""Learning system for agent adaptation."""

from typing import Dict, Any, List
from agent.learning.performance_tracker import PerformanceTracker
from agent.learning.model_weight_adjuster import ModelWeightAdjuster
from agent.learning.confidence_calibrator import ConfidenceCalibrator
from agent.learning.strategy_adapter import StrategyAdapter


class LearningSystem:
    """Learning system for agent adaptation."""
    
    def __init__(self):
        """Initialize learning system."""
        self.performance_tracker = PerformanceTracker()
        self.weight_adjuster = ModelWeightAdjuster(self.performance_tracker)
        self.confidence_calibrator = ConfidenceCalibrator(self.performance_tracker)
        self.strategy_adapter = StrategyAdapter(self.performance_tracker)
    
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

