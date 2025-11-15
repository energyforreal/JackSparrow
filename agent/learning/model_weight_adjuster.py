"""Model weight adjustment based on performance."""

from typing import Dict, Any, List
from agent.learning.performance_tracker import PerformanceTracker


class ModelWeightAdjuster:
    """Model weight adjustment service."""
    
    def __init__(self, performance_tracker: PerformanceTracker):
        """Initialize weight adjuster."""
        self.performance_tracker = performance_tracker
    
    def calculate_weights(self, model_names: List[str]) -> Dict[str, float]:
        """Calculate model weights based on performance."""
        
        if not model_names:
            return {}
        
        # Get performance for each model
        performances = {}
        for model_name in model_names:
            perf = self.performance_tracker.get_model_performance(model_name)
            # Weight based on accuracy and profit
            score = perf["accuracy"] * 0.5 + (max(0, perf["total_profit"]) / 1000.0) * 0.5
            performances[model_name] = max(0.1, score)  # Minimum weight of 0.1
        
        # Normalize weights
        total_score = sum(performances.values())
        if total_score > 0:
            weights = {
                name: score / total_score
                for name, score in performances.items()
            }
        else:
            # Equal weights if no performance data
            equal_weight = 1.0 / len(model_names)
            weights = {name: equal_weight for name in model_names}
        
        return weights

