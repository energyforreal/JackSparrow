"""Strategy parameter adaptation."""

from typing import Dict, Any
from agent.learning.performance_tracker import PerformanceTracker


class StrategyAdapter:
    """Strategy adaptation service."""
    
    def __init__(self, performance_tracker: PerformanceTracker):
        """Initialize strategy adapter."""
        self.performance_tracker = performance_tracker
        self.base_params = {
            "position_size_multiplier": 1.0,
            "confidence_threshold": 0.6,
            "stop_loss_multiplier": 1.0
        }
    
    def adapt_parameters(self) -> Dict[str, Any]:
        """Adapt strategy parameters based on performance."""
        
        # Get overall performance
        overall_accuracy = self._calculate_overall_accuracy()
        overall_profit = self._calculate_overall_profit()
        
        # Adjust parameters based on performance
        params = self.base_params.copy()
        
        # If performing well, increase position size
        if overall_accuracy > 0.6 and overall_profit > 0:
            params["position_size_multiplier"] = min(1.2, 1.0 + (overall_accuracy - 0.6))
        
        # If performing poorly, decrease position size
        elif overall_accuracy < 0.4 or overall_profit < 0:
            params["position_size_multiplier"] = max(0.8, 1.0 - (0.6 - overall_accuracy))
        
        # Adjust confidence threshold
        if overall_accuracy > 0.6:
            params["confidence_threshold"] = max(0.5, self.base_params["confidence_threshold"] - 0.1)
        elif overall_accuracy < 0.4:
            params["confidence_threshold"] = min(0.8, self.base_params["confidence_threshold"] + 0.1)
        
        return params
    
    def _calculate_overall_accuracy(self) -> float:
        """Calculate overall accuracy across all models."""
        # Simplified - would aggregate from performance tracker
        return 0.55  # Placeholder
    
    def _calculate_overall_profit(self) -> float:
        """Calculate overall profit across all models."""
        # Simplified - would aggregate from performance tracker
        return 0.0  # Placeholder

