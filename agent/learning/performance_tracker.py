"""Performance tracking per model."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class PerformanceTracker:
    """Track per-model prediction quality and realized PnL."""

    MAX_HISTORY_PER_MODEL = 500
    _DIRECTION_EPSILON = 1e-12

    def __init__(self) -> None:
        self.model_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "total_predictions": 0,
                "evaluated_predictions": 0,
                "correct_predictions": 0,
                "total_profit": 0.0,
                "predictions": [],
            }
        )

    @classmethod
    def _direction(cls, value: float) -> int:
        """Map value to -1/0/+1 with a tiny neutral band."""
        if value > cls._DIRECTION_EPSILON:
            return 1
        if value < -cls._DIRECTION_EPSILON:
            return -1
        return 0

    def record_prediction(
        self,
        model_name: str,
        prediction: float,
        actual_outcome: Optional[float] = None,
        profit: Optional[float] = None,
    ) -> None:
        """Record a model prediction and optional evaluated outcome."""
        stats = self.model_stats[model_name]
        stats["total_predictions"] += 1

        if actual_outcome is not None:
            stats["evaluated_predictions"] += 1
            if self._direction(float(prediction)) == self._direction(float(actual_outcome)):
                stats["correct_predictions"] += 1

        if profit is not None:
            stats["total_profit"] += float(profit)

        predictions = stats["predictions"]
        predictions.append(
            {
                "prediction": float(prediction),
                "actual_outcome": float(actual_outcome) if actual_outcome is not None else None,
                "profit": float(profit) if profit is not None else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(predictions) > self.MAX_HISTORY_PER_MODEL:
            del predictions[: len(predictions) - self.MAX_HISTORY_PER_MODEL]

    def get_model_accuracy(self, model_name: str) -> float:
        """Return directional accuracy over evaluated predictions only."""
        stats = self.model_stats.get(model_name, {})
        evaluated = int(stats.get("evaluated_predictions", 0) or 0)
        correct = int(stats.get("correct_predictions", 0) or 0)
        if evaluated <= 0:
            return 0.0
        return correct / evaluated

    def get_model_performance(self, model_name: str) -> Dict[str, Any]:
        """Return aggregate performance for one model."""
        stats = self.model_stats.get(model_name, {})
        return {
            "model_name": model_name,
            "total_predictions": int(stats.get("total_predictions", 0) or 0),
            "evaluated_predictions": int(stats.get("evaluated_predictions", 0) or 0),
            "correct_predictions": int(stats.get("correct_predictions", 0) or 0),
            "accuracy": self.get_model_accuracy(model_name),
            "total_profit": float(stats.get("total_profit", 0.0) or 0.0),
        }

    def get_all_model_performance(self) -> Dict[str, Dict[str, Any]]:
        """Return aggregate performance keyed by model name."""
        return {name: self.get_model_performance(name) for name in self.model_stats.keys()}

    def get_overall_performance(self) -> Dict[str, Any]:
        """Return pooled metrics across all tracked models."""
        per_model = self.get_all_model_performance()
        total_predictions = sum(p["total_predictions"] for p in per_model.values())
        evaluated_predictions = sum(p["evaluated_predictions"] for p in per_model.values())
        correct_predictions = sum(p["correct_predictions"] for p in per_model.values())
        total_profit = sum(p["total_profit"] for p in per_model.values())
        accuracy = (
            correct_predictions / evaluated_predictions if evaluated_predictions > 0 else 0.0
        )
        return {
            "models_tracked": len(per_model),
            "total_predictions": total_predictions,
            "evaluated_predictions": evaluated_predictions,
            "correct_predictions": correct_predictions,
            "accuracy": accuracy,
            "total_profit": total_profit,
        }

