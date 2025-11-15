"""Performance tracking per model."""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict


class PerformanceTracker:
    """Performance tracking service."""
    
    def __init__(self):
        """Initialize performance tracker."""
        self.model_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total_predictions": 0,
            "correct_predictions": 0,
            "total_profit": 0.0,
            "predictions": []
        })
    
    def record_prediction(
        self,
        model_name: str,
        prediction: float,
        actual_outcome: Optional[float] = None,
        profit: Optional[float] = None
    ):
        """Record model prediction and outcome."""
        stats = self.model_stats[model_name]
        stats["total_predictions"] += 1
        
        if actual_outcome is not None:
            # Check if prediction was correct
            predicted_direction = 1 if prediction > 0 else -1
            actual_direction = 1 if actual_outcome > 0 else -1
            
            if predicted_direction == actual_direction:
                stats["correct_predictions"] += 1
        
        if profit is not None:
            stats["total_profit"] += profit
        
        stats["predictions"].append({
            "prediction": prediction,
            "actual_outcome": actual_outcome,
            "profit": profit,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def get_model_accuracy(self, model_name: str) -> float:
        """Get model prediction accuracy."""
        stats = self.model_stats.get(model_name, {})
        total = stats.get("total_predictions", 0)
        correct = stats.get("correct_predictions", 0)
        
        if total == 0:
            return 0.0
        
        return correct / total
    
    def get_model_performance(self, model_name: str) -> Dict[str, Any]:
        """Get model performance metrics."""
        stats = self.model_stats.get(model_name, {})
        
        return {
            "model_name": model_name,
            "total_predictions": stats.get("total_predictions", 0),
            "correct_predictions": stats.get("correct_predictions", 0),
            "accuracy": self.get_model_accuracy(model_name),
            "total_profit": stats.get("total_profit", 0.0)
        }

