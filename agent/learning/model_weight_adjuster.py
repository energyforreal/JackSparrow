"""Model weight adjustment based on performance."""

from __future__ import annotations

import math
from typing import Dict, List

from agent.learning.performance_tracker import PerformanceTracker


class ModelWeightAdjuster:
    """Calculate adaptive model ensemble weights."""

    def __init__(self, performance_tracker: PerformanceTracker) -> None:
        self.performance_tracker = performance_tracker

    def calculate_weights(self, model_names: List[str]) -> Dict[str, float]:
        """Calculate normalized model weights from reliability and profitability."""
        if not model_names:
            return {}

        scores: Dict[str, float] = {}
        for model_name in model_names:
            perf = self.performance_tracker.get_model_performance(model_name)
            accuracy = float(perf.get("accuracy", 0.0) or 0.0)
            total_profit = float(perf.get("total_profit", 0.0) or 0.0)
            evaluated = int(perf.get("evaluated_predictions", 0) or 0)

            # Blend toward neutral reliability for small samples.
            reliability = max(0.0, min(1.0, accuracy))
            sample_factor = max(0.0, min(1.0, evaluated / 50.0))
            reliability = 0.5 * (1.0 - sample_factor) + reliability * sample_factor

            # Profit signal saturates via tanh to avoid outsized single-model domination.
            profit_component = 0.5 + 0.5 * math.tanh(total_profit / 1000.0)

            score = 0.7 * reliability + 0.3 * profit_component
            scores[model_name] = max(0.05, score)

        total_score = sum(scores.values())
        if total_score <= 0:
            equal_weight = 1.0 / len(model_names)
            return {name: equal_weight for name in model_names}
        return {name: score / total_score for name, score in scores.items()}

