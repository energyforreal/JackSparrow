"""Strategy parameter adaptation."""

from __future__ import annotations

from typing import Any, Dict

from agent.learning.performance_tracker import PerformanceTracker


class StrategyAdapter:
    """Adapt high-level strategy guardrails from live performance."""

    def __init__(self, performance_tracker: PerformanceTracker) -> None:
        self.performance_tracker = performance_tracker
        self.base_params = {
            "position_size_multiplier": 1.0,
            "confidence_threshold": 0.50,
            "stop_loss_multiplier": 1.0,
        }

    def adapt_parameters(self) -> Dict[str, Any]:
        """Derive bounded strategy parameters from aggregate model performance."""
        perf = self.performance_tracker.get_overall_performance()
        evaluated = int(perf.get("evaluated_predictions", 0) or 0)
        accuracy = float(perf.get("accuracy", 0.0) or 0.0)
        total_profit = float(perf.get("total_profit", 0.0) or 0.0)

        params = self.base_params.copy()
        if evaluated < 10:
            # Avoid overreacting before enough labeled outcomes exist.
            return params

        # Accuracy-centered aggressiveness score in [-1, +1].
        quality_score = max(-1.0, min(1.0, (accuracy - 0.50) / 0.25))

        # Position sizing: scale risk up/down with observed quality.
        params["position_size_multiplier"] = max(0.75, min(1.25, 1.0 + 0.15 * quality_score))

        # Confidence threshold: increase selectivity on poor quality, relax on strong performance.
        if quality_score < 0:
            # Poor quality → tighter filter
            params["confidence_threshold"] = min(
                0.95,
                max(0.45, self.base_params["confidence_threshold"] + 0.10 * abs(quality_score))
            )
        else:
            # Good quality → looser filter to capture more opportunities
            params["confidence_threshold"] = max(
                0.20,
                min(0.75, self.base_params["confidence_threshold"] - 0.10 * quality_score)
            )

        # Stop-loss multiplier: tighten slightly during drawdowns.
        if total_profit < 0:
            params["stop_loss_multiplier"] = 0.95
        elif total_profit > 0 and quality_score > 0.3:
            params["stop_loss_multiplier"] = 1.05

        return params

