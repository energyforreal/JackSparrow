"""
Learning System - Adaptive learning from trading outcomes.

Tracks model performance, updates weights, and adapts strategy parameters
based on historical trading results.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import os
import structlog
import statistics
import json
from pathlib import Path

logger = structlog.get_logger()


class TradeOutcome:
    """Represents the outcome of a completed trade."""

    def __init__(self, trade_id: str, symbol: str, entry_price: float, exit_price: float,
                 entry_time: datetime, exit_time: datetime, position_size: float,
                 predicted_signal: str, actual_pnl: float, holding_period_hours: float):
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.position_size = position_size
        self.predicted_signal = predicted_signal
        self.actual_pnl = actual_pnl
        self.holding_period_hours = holding_period_hours
        self.pnl_percentage = (actual_pnl / (entry_price * position_size)) * 100

    def was_profitable(self) -> bool:
        """Return True if trade was profitable."""
        return self.actual_pnl > 0

    def get_sharpe_contribution(self) -> float:
        """Calculate contribution to Sharpe ratio."""
        # Risk-adjusted return: return / volatility (simplified)
        if self.holding_period_hours > 0:
            return self.pnl_percentage / (self.holding_period_hours ** 0.5)
        return 0.0


class ModelPerformanceTracker:
    """Tracks individual model performance metrics."""

    def __init__(self):
        self.model_stats: Dict[str, Dict[str, Any]] = {}
        self.recent_trades: List[TradeOutcome] = []
        self.max_history_days = 30

    def record_trade_outcome(self, model_name: str, outcome: TradeOutcome):
        """Record trade outcome for a specific model."""
        if model_name not in self.model_stats:
            self.model_stats[model_name] = {
                "total_trades": 0,
                "profitable_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "sharpe_ratio": 0.0,
                "recent_performance": [],
                "last_updated": datetime.utcnow()
            }

        stats = self.model_stats[model_name]
        stats["total_trades"] += 1
        stats["total_pnl"] += outcome.actual_pnl

        if outcome.was_profitable():
            stats["profitable_trades"] += 1

        # Calculate win rate
        stats["win_rate"] = stats["profitable_trades"] / stats["total_trades"]

        # Calculate average P&L
        stats["avg_pnl"] = stats["total_pnl"] / stats["total_trades"]

        # Add to recent performance (keep last 50 trades)
        stats["recent_performance"].append({
            "pnl": outcome.actual_pnl,
            "timestamp": outcome.exit_time,
            "profitable": outcome.was_profitable()
        })

        if len(stats["recent_performance"]) > 50:
            stats["recent_performance"] = stats["recent_performance"][-50:]

        # Calculate Sharpe-like ratio from recent performance
        if len(stats["recent_performance"]) >= 10:
            recent_returns = [p["pnl"] for p in stats["recent_performance"]]
            if recent_returns:
                mean_return = statistics.mean(recent_returns)
                std_return = statistics.stdev(recent_returns) if len(recent_returns) > 1 else 1.0
                stats["sharpe_ratio"] = mean_return / std_return if std_return > 0 else 0.0

        stats["last_updated"] = datetime.utcnow()

        # Keep global recent trades for cross-model analysis
        self.recent_trades.append(outcome)
        if len(self.recent_trades) > 100:
            self.recent_trades = self.recent_trades[-100:]

        # Clean old trades
        cutoff_date = datetime.utcnow() - timedelta(days=self.max_history_days)
        self.recent_trades = [t for t in self.recent_trades if t.exit_time > cutoff_date]

        logger.info("model_performance_updated",
                   model_name=model_name,
                   total_trades=stats["total_trades"],
                   win_rate=stats["win_rate"],
                   avg_pnl=stats["avg_pnl"],
                   sharpe_ratio=stats["sharpe_ratio"])

    def get_model_weight(self, model_name: str, base_weight: float = 0.5) -> float:
        """Calculate dynamic weight for a model based on performance."""
        if model_name not in self.model_stats:
            return base_weight

        stats = self.model_stats[model_name]

        # Weight calculation based on multiple factors:
        # 1. Win rate (0.4 weight)
        # 2. Sharpe ratio (0.3 weight)
        # 3. Recent performance (0.3 weight)

        win_rate_score = min(1.0, stats["win_rate"] * 2.0)  # Boost win rate influence
        sharpe_score = max(0.0, min(1.0, stats["sharpe_ratio"] * 0.5 + 0.5))  # Normalize Sharpe

        # Recent performance (last 10 trades win rate)
        recent_trades = stats["recent_performance"][-10:]
        if recent_trades:
            recent_win_rate = sum(1 for t in recent_trades if t["profitable"]) / len(recent_trades)
            recent_score = recent_win_rate
        else:
            recent_score = 0.5

        # Weighted combination
        final_weight = (win_rate_score * 0.4 + sharpe_score * 0.3 + recent_score * 0.3)

        # Ensure reasonable bounds
        final_weight = max(0.1, min(1.0, final_weight))

        logger.debug("model_weight_calculated",
                    model_name=model_name,
                    win_rate_score=win_rate_score,
                    sharpe_score=sharpe_score,
                    recent_score=recent_score,
                    final_weight=final_weight)

        return final_weight

    def get_performance_summary(self, model_name: str) -> Dict[str, Any]:
        """Get performance summary for a model."""
        if model_name not in self.model_stats:
            return {"error": "Model not found"}

        return self.model_stats[model_name].copy()

    def get_all_model_weights(self, base_weights: Dict[str, float]) -> Dict[str, float]:
        """Calculate weights for all models."""
        weights = {}
        total_weight = 0.0

        for model_name, base_weight in base_weights.items():
            dynamic_weight = self.get_model_weight(model_name, base_weight)
            weights[model_name] = dynamic_weight
            total_weight += dynamic_weight

        # Normalize to sum to 1.0
        if total_weight > 0:
            weights = {name: weight / total_weight for name, weight in weights.items()}

        return weights


class LearningSystem:
    """Adaptive learning system for the trading agent."""

    def __init__(self):
        self.performance_tracker = ModelPerformanceTracker()
        self.confidence_calibration = ConfidenceCalibrator()
        self.strategy_adapter = StrategyAdapter()
        self._initialized = False
        self._state_loaded = False

    def _state_path(self) -> Path:
        from agent.core.config import settings

        p = str(getattr(settings, "learning_state_path", "learning_state.json") or "learning_state.json")
        path = Path(p)
        if path.is_absolute():
            return path
        # If LOGS_ROOT is set (Docker compose), persist alongside structured logs.
        logs_root = os.environ.get("LOGS_ROOT")
        if logs_root:
            return Path(logs_root) / path
        return path

    def _persistence_enabled(self) -> bool:
        from agent.core.config import settings

        return bool(getattr(settings, "learning_state_persistence_enabled", True))

    def _serialize_state(self) -> Dict[str, Any]:
        stats = self.performance_tracker.model_stats or {}
        # Normalize datetimes so JSON is stable.
        out_stats: Dict[str, Any] = {}
        for model_name, s in stats.items():
            if not isinstance(s, dict):
                continue
            ss = dict(s)
            lu = ss.get("last_updated")
            if isinstance(lu, datetime):
                ss["last_updated"] = lu.isoformat()
            rp = ss.get("recent_performance")
            if isinstance(rp, list):
                norm_rp = []
                for r in rp:
                    if not isinstance(r, dict):
                        continue
                    rr = dict(r)
                    ts = rr.get("timestamp")
                    if isinstance(ts, datetime):
                        rr["timestamp"] = ts.isoformat()
                    norm_rp.append(rr)
                ss["recent_performance"] = norm_rp
            out_stats[model_name] = ss

        return {
            "saved_at": datetime.utcnow().isoformat(),
            "model_stats": out_stats,
            "calibration_factors": dict(self.confidence_calibration.calibration_factors),
            "strategy_params": dict(self.strategy_adapter.strategy_params),
        }

    def _load_state(self) -> None:
        if self._state_loaded:
            return
        self._state_loaded = True
        if not self._persistence_enabled():
            return
        path = self._state_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("learning_state_load_failed", path=str(path), error=str(e))
            return

        stats = data.get("model_stats")
        if not isinstance(stats, dict):
            return
        # Best-effort parse back into the in-memory structure expected by tracker.
        parsed: Dict[str, Dict[str, Any]] = {}
        for model_name, s in stats.items():
            if not isinstance(model_name, str) or not isinstance(s, dict):
                continue
            ss = dict(s)
            lu = ss.get("last_updated")
            if isinstance(lu, str):
                try:
                    ss["last_updated"] = datetime.fromisoformat(lu)
                except Exception:
                    pass
            rp = ss.get("recent_performance")
            if isinstance(rp, list):
                norm_rp = []
                for r in rp:
                    if not isinstance(r, dict):
                        continue
                    rr = dict(r)
                    ts = rr.get("timestamp")
                    if isinstance(ts, str):
                        try:
                            rr["timestamp"] = datetime.fromisoformat(ts)
                        except Exception:
                            pass
                    norm_rp.append(rr)
                ss["recent_performance"] = norm_rp
            parsed[model_name] = ss

        self.performance_tracker.model_stats = parsed
        factors = data.get("calibration_factors")
        if isinstance(factors, dict):
            norm_factors: Dict[str, float] = {}
            for name, value in factors.items():
                try:
                    norm_factors[str(name)] = float(value)
                except (TypeError, ValueError):
                    continue
            self.confidence_calibration.calibration_factors = norm_factors
        strategy_params = data.get("strategy_params")
        if isinstance(strategy_params, dict):
            self.strategy_adapter.strategy_params.update(strategy_params)
        logger.info("learning_state_loaded", path=str(path), models=len(parsed))

    def _persist_state(self) -> None:
        if not self._persistence_enabled():
            return
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._serialize_state()
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as e:
            logger.warning("learning_state_persist_failed", path=str(path), error=str(e))

    async def initialize(self):
        """Initialize learning system."""
        self._load_state()
        self._initialized = True
        logger.info("learning_system_initialized")

    async def shutdown(self):
        """Shutdown learning system."""
        self._persist_state()
        logger.info("learning_system_shutdown")

    async def record_trade_outcome(self, trade_outcome: TradeOutcome,
                                  model_predictions: List[Dict[str, Any]]) -> None:
        """
        Record trade outcome and update learning models.

        Args:
            trade_outcome: The completed trade outcome
            model_predictions: List of model predictions that led to the trade
        """
        if not self._initialized:
            await self.initialize()

        # Record outcome for each model that participated
        participating_models = set()
        for prediction in model_predictions:
            model_name = prediction.get("model_name")
            if model_name:
                participating_models.add(model_name)
                self.performance_tracker.record_trade_outcome(model_name, trade_outcome)

        # Update confidence calibration
        await self.confidence_calibration.update_calibration(trade_outcome, model_predictions)

        # Adapt strategy parameters
        await self.strategy_adapter.adapt_strategy(trade_outcome, participating_models)

        logger.info("trade_outcome_recorded",
                   trade_id=trade_outcome.trade_id,
                   pnl=trade_outcome.actual_pnl,
                   models_used=len(participating_models),
                   was_profitable=trade_outcome.was_profitable())

        # Persist after updating rolling stats so adaptive weights survive restarts.
        self._persist_state()

    async def get_updated_model_weights(self, current_weights: Dict[str, float]) -> Dict[str, float]:
        """Get updated model weights based on learning."""
        return self.performance_tracker.get_all_model_weights(current_weights)

    async def calibrate_runtime_confidence(
        self, raw_confidence: float, model_predictions: List[Dict[str, Any]]
    ) -> float:
        """Calibrate runtime confidence using learned per-model calibration factors."""
        if not self._initialized:
            await self.initialize()
        try:
            base = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            return 0.0
        if not isinstance(model_predictions, list) or not model_predictions:
            return base

        total_weight = 0.0
        weighted_factor = 0.0
        for pred in model_predictions:
            if not isinstance(pred, dict):
                continue
            model_name = pred.get("model_name")
            if not model_name:
                continue
            try:
                pred_weight = float(pred.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                pred_weight = 0.0
            pred_weight = max(0.0, min(1.0, pred_weight))
            if pred_weight <= 0:
                continue
            factor = float(
                self.confidence_calibration.calibration_factors.get(str(model_name), 1.0)
            )
            weighted_factor += factor * pred_weight
            total_weight += pred_weight

        if total_weight <= 0:
            return base
        avg_factor = weighted_factor / total_weight
        calibrated = base * avg_factor
        return max(0.0, min(1.0, calibrated))

    async def get_learning_insights(self) -> Dict[str, Any]:
        """Get current learning insights and recommendations."""
        insights = {
            "performance_summary": {},
            "confidence_calibration": await self.confidence_calibration.get_calibration_status(),
            "strategy_adaptations": await self.strategy_adapter.get_adaptation_status(),
            "recommendations": []
        }

        # Add performance insights for each model
        for model_name in self.performance_tracker.model_stats.keys():
            insights["performance_summary"][model_name] = \
                self.performance_tracker.get_performance_summary(model_name)

        # Generate recommendations
        recommendations = []

        # Check for underperforming models
        for model_name, stats in self.performance_tracker.model_stats.items():
            if stats["total_trades"] > 10 and stats["win_rate"] < 0.4:
                recommendations.append({
                    "type": "model_performance",
                    "severity": "high",
                    "message": f"Model {model_name} has low win rate ({stats['win_rate']:.2f}). Consider retraining.",
                    "model": model_name,
                    "win_rate": stats["win_rate"]
                })

        # Check for overfitting signals
        for model_name, stats in self.performance_tracker.model_stats.items():
            if stats["total_trades"] > 20:
                recent_trades = stats["recent_performance"][-10:]
                if recent_trades:
                    recent_win_rate = sum(1 for t in recent_trades if t["profitable"]) / len(recent_trades)
                    overall_win_rate = stats["win_rate"]

                    if recent_win_rate < overall_win_rate * 0.7:
                        recommendations.append({
                            "type": "overfitting_warning",
                            "severity": "medium",
                            "message": f"Model {model_name} recent performance ({recent_win_rate:.2f}) significantly worse than overall ({overall_win_rate:.2f}).",
                            "model": model_name,
                            "recent_win_rate": recent_win_rate,
                            "overall_win_rate": overall_win_rate
                        })

        insights["recommendations"] = recommendations

        return insights

    async def get_health_status(self) -> Dict[str, Any]:
        """Get learning system health status."""
        return {
            "status": "healthy" if self._initialized else "unhealthy",
            "initialized": self._initialized,
            "models_tracked": len(self.performance_tracker.model_stats),
            "recent_trades": len(self.performance_tracker.recent_trades),
            "total_trades_learned": sum(stats["total_trades"]
                                      for stats in self.performance_tracker.model_stats.values())
        }


class ConfidenceCalibrator:
    """Calibrates prediction confidence based on historical accuracy."""

    def __init__(self):
        self.confidence_history: Dict[str, List[Dict[str, Any]]] = {}
        self.calibration_factors: Dict[str, float] = {}

    async def update_calibration(self, trade_outcome: TradeOutcome,
                               model_predictions: List[Dict[str, Any]]) -> None:
        """Update confidence calibration based on trade outcome."""
        for prediction in model_predictions:
            model_name = prediction.get("model_name")
            confidence = prediction.get("confidence", 0.5)
            predicted_correctly = self._did_model_predict_correctly(prediction, trade_outcome)

            if model_name not in self.confidence_history:
                self.confidence_history[model_name] = []

            self.confidence_history[model_name].append({
                "confidence": confidence,
                "correct": predicted_correctly,
                "timestamp": datetime.utcnow()
            })

            # Keep only recent history
            if len(self.confidence_history[model_name]) > 100:
                self.confidence_history[model_name] = self.confidence_history[model_name][-100:]

            # Update calibration factor
            await self._update_calibration_factor(model_name)

    def _did_model_predict_correctly(self, prediction: Dict[str, Any],
                                   trade_outcome: TradeOutcome) -> bool:
        """Determine if model's prediction was directionally correct."""
        predicted_signal = prediction.get("prediction", 0.0)
        actual_pnl = trade_outcome.actual_pnl

        # Simple directional accuracy: positive prediction should lead to positive P&L
        predicted_positive = predicted_signal > 0.1  # Strong bullish
        predicted_negative = predicted_signal < -0.1  # Strong bearish

        actual_positive = actual_pnl > 0
        actual_negative = actual_pnl < 0

        if predicted_positive and actual_positive:
            return True
        elif predicted_negative and actual_negative:
            return True
        elif abs(predicted_signal) < 0.1 and abs(actual_pnl) < 100:  # HOLD signal, small P&L
            return True

        return False

    async def _update_calibration_factor(self, model_name: str) -> None:
        """Update confidence calibration factor for a model."""
        history = self.confidence_history.get(model_name, [])
        if len(history) < 10:
            return

        # Calculate calibration: average confidence when correct vs when wrong
        correct_predictions = [h for h in history if h["correct"]]
        wrong_predictions = [h for h in history if not h["correct"]]

        if correct_predictions and wrong_predictions:
            avg_conf_correct = statistics.mean(h["confidence"] for h in correct_predictions)
            avg_conf_wrong = statistics.mean(h["confidence"] for h in wrong_predictions)

            # Calibration factor: how much to adjust confidence
            # If model is overconfident when wrong, reduce confidence
            calibration_factor = avg_conf_correct / max(avg_conf_wrong, 0.1)
            calibration_factor = max(0.5, min(2.0, calibration_factor))  # Reasonable bounds

            self.calibration_factors[model_name] = calibration_factor

    def calibrate_confidence(self, model_name: str, raw_confidence: float) -> float:
        """Apply confidence calibration to raw confidence score."""
        calibration_factor = self.calibration_factors.get(model_name, 1.0)
        calibrated = raw_confidence * calibration_factor
        return max(0.0, min(1.0, calibrated))

    async def get_calibration_status(self) -> Dict[str, Any]:
        """Get confidence calibration status."""
        return {
            "calibration_factors": self.calibration_factors.copy(),
            "models_calibrated": len(self.calibration_factors),
            "calibration_history_size": sum(len(history)
                                          for history in self.confidence_history.values())
        }


class StrategyAdapter:
    """Adapts trading strategy parameters based on performance."""

    def __init__(self):
        self.strategy_params = {
            "max_position_size": 0.1,  # 10% of portfolio
            "min_confidence_threshold": 0.6,
            "volatility_multiplier": 1.0,
            "holding_period_limit": 24  # hours
        }
        self.performance_history: List[Dict[str, Any]] = []

    async def adapt_strategy(self, trade_outcome: TradeOutcome,
                           participating_models: set) -> None:
        """Adapt strategy parameters based on trade outcome."""
        self.performance_history.append({
            "outcome": trade_outcome,
            "models": list(participating_models),
            "timestamp": datetime.utcnow()
        })

        # Keep recent history
        if len(self.performance_history) > 50:
            self.performance_history = self.performance_history[-50:]

        # Analyze recent performance and adapt parameters
        recent_trades = self.performance_history[-10:]
        if len(recent_trades) >= 5:
            win_rate = sum(1 for t in recent_trades if t["outcome"].was_profitable()) / len(recent_trades)

            # Adapt based on win rate
            if win_rate > 0.7:
                # Good performance - can be more aggressive
                self.strategy_params["max_position_size"] = min(0.15, self.strategy_params["max_position_size"] * 1.1)
                self.strategy_params["min_confidence_threshold"] = max(0.5, self.strategy_params["min_confidence_threshold"] * 0.95)
            elif win_rate < 0.4:
                # Poor performance - be more conservative
                self.strategy_params["max_position_size"] = max(0.05, self.strategy_params["max_position_size"] * 0.9)
                self.strategy_params["min_confidence_threshold"] = min(0.8, self.strategy_params["min_confidence_threshold"] * 1.05)

            logger.info("strategy_parameters_adapted",
                       win_rate=win_rate,
                       max_position_size=self.strategy_params["max_position_size"],
                       min_confidence_threshold=self.strategy_params["min_confidence_threshold"])

    async def get_adaptation_status(self) -> Dict[str, Any]:
        """Get strategy adaptation status."""
        return {
            "current_parameters": self.strategy_params.copy(),
            "performance_history_size": len(self.performance_history),
            "recent_win_rate": self._calculate_recent_win_rate()
        }

    def _calculate_recent_win_rate(self) -> float:
        """Calculate win rate from recent trades."""
        recent_trades = self.performance_history[-10:]
        if not recent_trades:
            return 0.0

        profitable_trades = sum(1 for t in recent_trades if t["outcome"].was_profitable())
        return profitable_trades / len(recent_trades)

    def get_strategy_parameters(self) -> Dict[str, Any]:
        """Get current strategy parameters."""
        return self.strategy_params.copy()