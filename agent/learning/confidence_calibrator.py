"""Confidence calibration based on historical performance."""

from __future__ import annotations

from agent.learning.performance_tracker import PerformanceTracker


class ConfidenceCalibrator:
    """Calibrate raw confidence using model reliability and signal strength."""

    def __init__(self, performance_tracker: PerformanceTracker) -> None:
        self.performance_tracker = performance_tracker

    def calibrate_confidence(
        self,
        raw_confidence: float,
        model_name: str,
        signal_strength: float,
    ) -> float:
        """Return calibrated confidence in [0, 1]."""
        perf = self.performance_tracker.get_model_performance(model_name)
        accuracy = float(perf.get("accuracy", 0.0) or 0.0)
        evaluated = int(perf.get("evaluated_predictions", 0) or 0)

        raw = max(0.0, min(1.0, float(raw_confidence)))

        # Keep new models near neutral scaling until enough outcomes accumulate.
        neutral_multiplier = 1.0
        reliability_multiplier = 1.0 + (accuracy - 0.5) * 0.6
        if evaluated < 20:
            blend = max(0.0, min(1.0, evaluated / 20.0))
            reliability_multiplier = (
                neutral_multiplier * (1.0 - blend) + reliability_multiplier * blend
            )

        # Mildly upweight stronger directional signals; avoid extreme boosts.
        signal_scale = max(0.0, min(1.0, abs(float(signal_strength))))
        signal_multiplier = 0.90 + 0.20 * signal_scale

        calibrated = raw * reliability_multiplier * signal_multiplier
        return max(0.0, min(1.0, calibrated))

