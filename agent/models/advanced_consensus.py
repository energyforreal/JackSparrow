"""
Advanced Consensus Algorithms - Enhanced model ensemble decision making.

Implements sophisticated consensus algorithms including correlation-based weighting,
time-decayed performance, market regime adaptation, and confidence scoring.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import statistics
import numpy as np
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ConsensusConfig:
    """Configuration for consensus algorithms."""
    correlation_threshold: float = 0.7  # Models with correlation above this are penalized
    time_decay_factor: float = 0.9  # How much to weight recent vs old performance
    regime_adaptation_strength: float = 0.3  # How strongly to adapt to market regimes
    confidence_weight_power: float = 2.0  # How much to emphasize high confidence
    min_weight: float = 0.05  # Minimum weight any model can have
    max_weight: float = 0.4  # Maximum weight any model can have


@dataclass
class ModelPrediction:
    """Enhanced model prediction with metadata."""
    model_name: str
    prediction: float  # -1 to 1 scale
    confidence: float  # 0 to 1 scale
    timestamp: datetime
    model_type: str
    feature_importance: Optional[Dict[str, float]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ConsensusResult:
    """Result of consensus calculation."""
    final_prediction: float
    confidence: float
    model_weights: Dict[str, float]
    consensus_method: str
    reasoning: str
    risk_assessment: Dict[str, Any]


class CorrelationAnalyzer:
    """Analyzes correlations between model predictions."""

    def __init__(self, history_window: int = 100):
        self.prediction_history: List[Dict[str, Any]] = []
        self.history_window = history_window
        self.correlation_cache: Dict[str, float] = {}
        self.cache_timestamp: Optional[datetime] = None

    def add_prediction_set(self, predictions: List[ModelPrediction], actual_outcome: Optional[float] = None):
        """Add a set of predictions to history."""
        prediction_data = {
            "timestamp": datetime.utcnow(),
            "predictions": {p.model_name: p.prediction for p in predictions},
            "actual_outcome": actual_outcome,
            "model_names": [p.model_name for p in predictions]
        }

        self.prediction_history.append(prediction_data)

        # Maintain history window
        if len(self.prediction_history) > self.history_window:
            self.prediction_history = self.prediction_history[-self.history_window:]

        # Invalidate correlation cache
        self.correlation_cache = {}
        self.cache_timestamp = None

    def get_correlation_matrix(self, model_names: List[str]) -> np.ndarray:
        """Calculate correlation matrix for given models."""
        if not self.prediction_history:
            return np.eye(len(model_names))

        # Extract prediction series
        prediction_series = {}
        for model_name in model_names:
            series = []
            for entry in self.prediction_history:
                if model_name in entry["predictions"]:
                    series.append(entry["predictions"][model_name])
            prediction_series[model_name] = series

        # Ensure all series have same length (use most recent)
        min_length = min(len(series) for series in prediction_series.values())
        for model_name in prediction_series:
            prediction_series[model_name] = prediction_series[model_name][-min_length:]

        # Calculate correlation matrix
        n_models = len(model_names)
        correlation_matrix = np.eye(n_models)

        for i in range(n_models):
            for j in range(i + 1, n_models):
                model_i = model_names[i]
                model_j = model_names[j]

                if len(prediction_series[model_i]) > 1 and len(prediction_series[model_j]) > 1:
                    try:
                        corr = np.corrcoef(prediction_series[model_i], prediction_series[model_j])[0, 1]
                        if not np.isnan(corr):
                            correlation_matrix[i, j] = corr
                            correlation_matrix[j, i] = corr
                    except:
                        pass  # Keep as 1.0 (perfect correlation) on error

        return correlation_matrix

    def calculate_correlation_penalty(self, model_name: str, all_models: List[str],
                                    correlation_matrix: np.ndarray) -> float:
        """Calculate penalty for highly correlated models."""
        if model_name not in all_models:
            return 1.0

        model_idx = all_models.index(model_name)
        correlations = correlation_matrix[model_idx, :]

        # Average correlation with other models (excluding self)
        other_correlations = np.delete(correlations, model_idx)
        avg_correlation = np.mean(np.abs(other_correlations))

        # Apply penalty for high correlation
        if avg_correlation > 0.8:
            penalty = 0.5  # Strong penalty for very high correlation
        elif avg_correlation > 0.6:
            penalty = 0.7  # Moderate penalty
        elif avg_correlation > 0.4:
            penalty = 0.9  # Light penalty
        else:
            penalty = 1.0  # No penalty

        return penalty


class TimeWeightedPerformance:
    """Tracks and calculates time-weighted model performance."""

    def __init__(self, decay_factor: float = 0.95):
        self.decay_factor = decay_factor
        self.performance_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self.accuracy_history: Dict[str, List[Tuple[datetime, bool]]] = {}

    def record_prediction(self, model_name: str, prediction: float,
                         actual_outcome: Optional[float] = None):
        """Record a model prediction."""
        timestamp = datetime.utcnow()

        if model_name not in self.performance_history:
            self.performance_history[model_name] = []
            self.accuracy_history[model_name] = []

        # Store prediction magnitude (absolute value represents confidence in direction)
        self.performance_history[model_name].append((timestamp, abs(prediction)))

        # If we have actual outcome, record accuracy
        if actual_outcome is not None:
            # Simple accuracy: correct direction
            predicted_direction = 1 if prediction > 0.1 else -1 if prediction < -0.1 else 0
            actual_direction = 1 if actual_outcome > 0.1 else -1 if actual_outcome < -0.1 else 0

            is_accurate = predicted_direction == actual_direction
            self.accuracy_history[model_name].append((timestamp, is_accurate))

    def get_time_weighted_accuracy(self, model_name: str, days_back: int = 30) -> float:
        """Calculate time-weighted accuracy for a model."""
        if model_name not in self.accuracy_history:
            return 0.5  # Neutral accuracy

        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        accuracies = [(ts, acc) for ts, acc in self.accuracy_history[model_name]
                     if ts >= cutoff_date]

        if not accuracies:
            return 0.5

        # Apply time decay
        now = datetime.utcnow()
        weighted_accuracies = []

        for timestamp, accuracy in accuracies:
            days_old = (now - timestamp).days
            weight = self.decay_factor ** days_old
            weighted_accuracies.append(accuracy * weight)

        if not weighted_accuracies:
            return 0.5

        return sum(weighted_accuracies) / sum(self.decay_factor ** (now - ts).days
                                             for ts, _ in accuracies)

    def get_recent_performance_score(self, model_name: str, days_back: int = 7) -> float:
        """Get recent performance score (0-1 scale)."""
        accuracy = self.get_time_weighted_accuracy(model_name, days_back)

        # Convert to performance score (higher accuracy = higher score)
        return accuracy


class MarketRegimeAdapter:
    """Adapts consensus weights based on market regime."""

    def __init__(self):
        self.regime_history: List[Tuple[datetime, str]] = []
        self.model_regime_performance: Dict[str, Dict[str, List[float]]] = {}

    def detect_market_regime(self, volatility: float, trend_strength: float,
                           volume_ratio: float) -> str:
        """
        Detect current market regime based on market indicators.

        Regimes:
        - bull_trending: Strong uptrend, low volatility
        - bear_trending: Strong downtrend, low volatility
        - high_volatility: High volatility regardless of trend
        - ranging: Low volatility, weak trend
        """
        if volatility > 0.03:  # High volatility threshold
            return "high_volatility"
        elif trend_strength > 0.7:  # Strong trend
            return "trending"
        else:
            return "ranging"

    def record_regime_performance(self, regime: str, model_name: str, accuracy: float):
        """Record how well a model performs in a given regime."""
        if model_name not in self.model_regime_performance:
            self.model_regime_performance[model_name] = {}

        if regime not in self.model_regime_performance[model_name]:
            self.model_regime_performance[model_name][regime] = []

        self.model_regime_performance[model_name][regime].append(accuracy)

        # Keep only recent performance (last 20 entries per regime)
        if len(self.model_regime_performance[model_name][regime]) > 20:
            self.model_regime_performance[model_name][regime] = \
                self.model_regime_performance[model_name][regime][-20:]

    def get_regime_performance_score(self, model_name: str, current_regime: str) -> float:
        """Get model's performance score in current regime."""
        if model_name not in self.model_regime_performance:
            return 0.5

        if current_regime not in self.model_regime_performance[model_name]:
            return 0.5

        performances = self.model_regime_performance[model_name][current_regime]
        if not performances:
            return 0.5

        return statistics.mean(performances)

    def calculate_regime_weight_multiplier(self, model_name: str, current_regime: str) -> float:
        """Calculate weight multiplier based on regime performance."""
        regime_score = self.get_regime_performance_score(model_name, current_regime)

        # Boost models that perform well in current regime
        if regime_score > 0.6:
            return 1.2  # 20% boost
        elif regime_score < 0.4:
            return 0.8  # 20% penalty
        else:
            return 1.0  # No adjustment


class AdvancedConsensusEngine:
    """
    Advanced consensus engine with multiple sophisticated algorithms.
    """

    def __init__(self, config: Optional[ConsensusConfig] = None):
        self.config = config or ConsensusConfig()
        self.correlation_analyzer = CorrelationAnalyzer()
        self.time_weighted_perf = TimeWeightedPerformance(self.config.time_decay_factor)
        self.regime_adapter = MarketRegimeAdapter()
        self.consensus_history: List[ConsensusResult] = []

    async def calculate_consensus(self, predictions: List[ModelPrediction],
                                market_context: Optional[Dict[str, Any]] = None,
                                consensus_method: str = "adaptive") -> ConsensusResult:
        """
        Calculate advanced consensus from model predictions.

        Args:
            predictions: List of model predictions
            market_context: Current market conditions
            consensus_method: Type of consensus algorithm to use

        Returns:
            ConsensusResult with final prediction and metadata
        """
        if not predictions:
            return ConsensusResult(
                final_prediction=0.0,
                confidence=0.0,
                model_weights={},
                consensus_method="none",
                reasoning="No predictions available",
                risk_assessment={"error": "No predictions"}
            )

        market_context = market_context or {}

        # Detect current market regime
        current_regime = self._detect_current_regime(market_context)

        # Calculate different types of weights
        base_weights = self._calculate_base_weights(predictions)
        correlation_weights = self._apply_correlation_weighting(predictions, base_weights)
        time_weights = self._apply_time_weighting(predictions, correlation_weights)
        regime_weights = self._apply_regime_adaptation(predictions, time_weights, current_regime)
        final_weights = self._apply_confidence_weighting(predictions, regime_weights)

        # Normalize weights
        final_weights = self._normalize_weights(final_weights)

        # Calculate weighted consensus
        weighted_sum = 0.0
        confidence_sum = 0.0
        total_weight = 0.0

        for prediction in predictions:
            weight = final_weights.get(prediction.model_name, 0.0)
            weighted_sum += prediction.prediction * weight
            confidence_sum += prediction.confidence * weight
            total_weight += weight

        if total_weight > 0:
            final_prediction = weighted_sum / total_weight
            final_confidence = confidence_sum / total_weight
        else:
            final_prediction = statistics.mean([p.prediction for p in predictions])
            final_confidence = statistics.mean([p.confidence for p in predictions])

        # Ensure bounds
        final_prediction = max(-1.0, min(1.0, final_prediction))
        final_confidence = max(0.0, min(1.0, final_confidence))

        # Generate reasoning
        reasoning = self._generate_consensus_reasoning(
            predictions, final_weights, current_regime, consensus_method
        )

        # Risk assessment
        risk_assessment = self._assess_consensus_risk(predictions, final_weights, market_context)

        result = ConsensusResult(
            final_prediction=final_prediction,
            confidence=final_confidence,
            model_weights=final_weights,
            consensus_method=consensus_method,
            reasoning=reasoning,
            risk_assessment=risk_assessment
        )

        # Store result for future learning
        self.consensus_history.append(result)

        logger.info("advanced_consensus_calculated",
                   method=consensus_method,
                   models=len(predictions),
                   final_prediction=round(final_prediction, 3),
                   confidence=round(final_confidence, 3),
                   regime=current_regime)

        return result

    def _calculate_base_weights(self, predictions: List[ModelPrediction]) -> Dict[str, float]:
        """Calculate base weights (equal weighting)."""
        n_models = len(predictions)
        if n_models == 0:
            return {}

        base_weight = 1.0 / n_models
        return {p.model_name: base_weight for p in predictions}

    def _apply_correlation_weighting(self, predictions: List[ModelPrediction],
                                   base_weights: Dict[str, float]) -> Dict[str, float]:
        """Apply correlation-based weighting to reduce redundant models."""
        if len(predictions) < 3:
            return base_weights.copy()

        model_names = [p.model_name for p in predictions]
        correlation_matrix = self.correlation_analyzer.get_correlation_matrix(model_names)

        adjusted_weights = {}
        for prediction in predictions:
            penalty = self.correlation_analyzer.calculate_correlation_penalty(
                prediction.model_name, model_names, correlation_matrix
            )
            adjusted_weights[prediction.model_name] = base_weights[prediction.model_name] * penalty

        return adjusted_weights

    def _apply_time_weighting(self, predictions: List[ModelPrediction],
                            base_weights: Dict[str, float]) -> Dict[str, float]:
        """Apply time-weighted performance adjustments."""
        adjusted_weights = {}

        for prediction in predictions:
            # Get recent performance score
            perf_score = self.time_weighted_perf.get_recent_performance_score(
                prediction.model_name, days_back=7
            )

            # Adjust weight based on performance (better performers get higher weights)
            perf_multiplier = 0.5 + perf_score  # 0.5 to 1.5 range
            adjusted_weights[prediction.model_name] = base_weights[prediction.model_name] * perf_multiplier

        return adjusted_weights

    def _apply_regime_adaptation(self, predictions: List[ModelPrediction],
                               base_weights: Dict[str, float], current_regime: str) -> Dict[str, float]:
        """Apply market regime-based weight adjustments."""
        adjusted_weights = {}

        for prediction in predictions:
            regime_multiplier = self.regime_adapter.calculate_regime_weight_multiplier(
                prediction.model_name, current_regime
            )
            adjusted_weights[prediction.model_name] = base_weights[prediction.model_name] * regime_multiplier

        return adjusted_weights

    def _apply_confidence_weighting(self, predictions: List[ModelPrediction],
                                  base_weights: Dict[str, float]) -> Dict[str, float]:
        """Apply confidence-based weighting."""
        adjusted_weights = {}

        for prediction in predictions:
            # Apply confidence weighting (higher confidence = higher weight)
            confidence_multiplier = prediction.confidence ** self.config.confidence_weight_power
            adjusted_weights[prediction.model_name] = base_weights[prediction.model_name] * confidence_multiplier

        return adjusted_weights

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize weights to ensure they sum to 1.0 and respect bounds."""
        total_weight = sum(weights.values())

        if total_weight == 0:
            # Fallback to equal weighting
            n_models = len(weights)
            return {name: 1.0 / n_models for name in weights.keys()}

        # Normalize to sum to 1.0
        normalized = {name: weight / total_weight for name, weight in weights.items()}

        # Apply min/max bounds
        adjusted = {}
        for name, weight in normalized.items():
            adjusted[name] = max(self.config.min_weight, min(self.config.max_weight, weight))

        # Re-normalize after bounds application
        total_adjusted = sum(adjusted.values())
        if total_adjusted > 0:
            final_weights = {name: weight / total_adjusted for name, weight in adjusted.items()}
        else:
            # Fallback if all weights are zero
            n_models = len(adjusted)
            final_weights = {name: 1.0 / n_models for name in adjusted.keys()}

        return final_weights

    def _detect_current_regime(self, market_context: Dict[str, Any]) -> str:
        """Detect current market regime from context."""
        volatility = market_context.get("volatility", 0.02)
        trend_strength = market_context.get("trend_strength", 0.5)
        volume_ratio = market_context.get("volume_ratio", 1.0)

        return self.regime_adapter.detect_market_regime(volatility, trend_strength, volume_ratio)

    def _generate_consensus_reasoning(self, predictions: List[ModelPrediction],
                                    weights: Dict[str, float], regime: str,
                                    method: str) -> str:
        """Generate human-readable reasoning for consensus."""
        # Sort models by weight
        sorted_models = sorted(weights.items(), key=lambda x: x[1], reverse=True)

        # Get top contributing models
        top_models = sorted_models[:3]
        top_model_names = [name for name, _ in top_models]

        # Calculate prediction distribution
        bullish = sum(1 for p in predictions if p.prediction > 0.2)
        bearish = sum(1 for p in predictions if p.prediction < -0.2)
        neutral = len(predictions) - bullish - bearish

        # Generate reasoning
        reasoning_parts = [
            f"Advanced {method} consensus from {len(predictions)} models in {regime} market regime.",
            f"Top contributing models: {', '.join(top_model_names)}.",
            f"Prediction distribution: {bullish} bullish, {bearish} bearish, {neutral} neutral."
        ]

        # Add weight analysis
        weight_range = max(weights.values()) - min(weights.values())
        if weight_range > 0.1:
            reasoning_parts.append("Significant weight differentiation applied.")
        else:
            reasoning_parts.append("Relatively equal model weighting.")

        return " ".join(reasoning_parts)

    def _assess_consensus_risk(self, predictions: List[ModelPrediction],
                             weights: Dict[str, float],
                             market_context: Dict[str, Any]) -> Dict[str, Any]:
        """Assess risk factors in the consensus."""
        # Calculate prediction dispersion
        pred_values = [p.prediction for p in predictions]
        if len(pred_values) > 1:
            dispersion = statistics.stdev(pred_values)
        else:
            dispersion = 0.0

        # Calculate confidence range
        confidence_values = [p.confidence for p in predictions]
        confidence_range = max(confidence_values) - min(confidence_values) if confidence_values else 0.0

        # Weight concentration
        max_weight = max(weights.values()) if weights else 0.0
        weight_concentration = max_weight

        risk_factors = {
            "prediction_dispersion": dispersion,
            "confidence_range": confidence_range,
            "weight_concentration": weight_concentration,
            "model_count": len(predictions)
        }

        # Risk assessment
        risk_level = "low"
        risk_reasons = []

        if dispersion > 0.5:
            risk_level = "high"
            risk_reasons.append("High model disagreement")

        if confidence_range > 0.5:
            risk_level = "medium" if risk_level == "low" else "high"
            risk_reasons.append("Wide confidence range")

        if weight_concentration > 0.6:
            risk_level = "medium" if risk_level == "low" else "high"
            risk_reasons.append("Heavy reliance on single model")

        if len(predictions) < 3:
            risk_level = "high"
            risk_reasons.append("Insufficient model diversity")

        return {
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "risk_factors": risk_factors,
            "recommendations": self._generate_risk_recommendations(risk_level, risk_factors)
        }

    def _generate_risk_recommendations(self, risk_level: str,
                                     risk_factors: Dict[str, Any]) -> List[str]:
        """Generate risk management recommendations."""
        recommendations = []

        if risk_level == "high":
            recommendations.append("Consider reducing position size due to high consensus risk")
            recommendations.append("Monitor this trade closely for early exit signals")

        if risk_factors["prediction_dispersion"] > 0.5:
            recommendations.append("High model disagreement suggests uncertain market conditions")

        if risk_factors["weight_concentration"] > 0.6:
            recommendations.append("Heavy reliance on single model increases specific risk")

        if risk_factors["model_count"] < 3:
            recommendations.append("Limited model diversity - consider adding more models")

        if not recommendations:
            recommendations.append("Consensus risk assessment: acceptable")

        return recommendations

    async def record_outcome(self, predictions: List[ModelPrediction],
                           actual_outcome: float, market_context: Dict[str, Any]):
        """Record actual outcome for learning."""
        # Add to correlation analyzer
        self.correlation_analyzer.add_prediction_set(predictions, actual_outcome)

        # Record individual model performance
        current_regime = self._detect_current_regime(market_context)

        for prediction in predictions:
            # Record prediction for time-weighted performance
            self.time_weighted_perf.record_prediction(
                prediction.model_name, prediction.prediction, actual_outcome
            )

            # Record regime performance
            predicted_direction = 1 if prediction.prediction > 0.1 else -1 if prediction.prediction < -0.1 else 0
            actual_direction = 1 if actual_outcome > 0.1 else -1 if actual_outcome < -0.1 else 0
            accuracy = 1.0 if predicted_direction == actual_direction else 0.0

            self.regime_adapter.record_regime_performance(
                current_regime, prediction.model_name, accuracy
            )

    def get_consensus_stats(self) -> Dict[str, Any]:
        """Get consensus engine statistics."""
        if not self.consensus_history:
            return {"total_consensus_calculations": 0}

        predictions = [result.final_prediction for result in self.consensus_history]
        confidences = [result.confidence for result in self.consensus_history]

        return {
            "total_consensus_calculations": len(self.consensus_history),
            "avg_prediction": statistics.mean(predictions) if predictions else 0.0,
            "avg_confidence": statistics.mean(confidences) if confidences else 0.0,
            "prediction_std": statistics.stdev(predictions) if len(predictions) > 1 else 0.0,
            "confidence_std": statistics.stdev(confidences) if len(confidences) > 1 else 0.0,
            "methods_used": list(set(result.consensus_method for result in self.consensus_history))
        }
