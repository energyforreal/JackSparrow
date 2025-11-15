"""Confidence calibration based on historical performance."""

from typing import Dict, Any
from agent.learning.performance_tracker import PerformanceTracker


class ConfidenceCalibrator:
    """Confidence calibration service."""
    
    def __init__(self, performance_tracker: PerformanceTracker):
        """Initialize confidence calibrator."""
        self.performance_tracker = performance_tracker
    
    def calibrate_confidence(
        self,
        raw_confidence: float,
        model_name: str,
        signal_strength: float
    ) -> float:
        """Calibrate confidence based on historical performance."""
        
        # Get model accuracy
        accuracy = self.performance_tracker.get_model_accuracy(model_name)
        
        # Adjust confidence based on accuracy
        # If model has been accurate, increase confidence
        # If model has been inaccurate, decrease confidence
        calibrated = raw_confidence * accuracy
        
        # Adjust based on signal strength
        # Stronger signals get higher confidence
        signal_multiplier = min(1.0, abs(signal_strength) + 0.5)
        calibrated = calibrated * signal_multiplier
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, calibrated))

