"""
LSTM model node implementation.

Implements MCP Model Node interface for TensorFlow/Keras LSTM models.
"""

from typing import Dict, Any, List
from pathlib import Path
import time
import numpy as np
import structlog
from datetime import datetime

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction

logger = structlog.get_logger()


class LSTMNode(MCPModelNode):
    """LSTM model node for TensorFlow/Keras models."""

    def __init__(self, model_path: Path):
        """Initialize LSTM node."""
        self.model_path = model_path
        self.model = None
        self._model_name = model_path.stem
        self._model_version = "1.0.0"
        self._model_type = "lstm"
        self._is_regressor = None  # Will be set during initialization
        self.health_status = "unknown"

    @classmethod
    async def load_from_file(cls, model_path: Path) -> "LSTMNode":
        """Load LSTM model from file."""
        node = cls(model_path)
        await node.initialize()
        return node

    async def initialize(self):
        """Initialize model."""
        try:
            # Validate file exists and is readable
            if not self.model_path.exists():
                raise FileNotFoundError(f"Model file not found: {self.model_path}")

            if not self.model_path.is_file():
                raise ValueError(f"Model path is not a file: {self.model_path}")

            # Check file size (corrupted files are often very small or empty)
            file_size = self.model_path.stat().st_size
            if file_size == 0:
                raise ValueError(f"Model file is empty: {self.model_path}")
            if file_size < 1000:  # LSTM models are typically much larger
                logger.warning(
                    "lstm_model_suspicious_size",
                    model_path=str(self.model_path),
                    file_size=file_size,
                    message="Model file is unusually small for an LSTM model - may be corrupted"
                )

            # Try to load TensorFlow/Keras model
            try:
                from tensorflow import keras
            except ImportError as e:
                raise ImportError(
                    f"TensorFlow not installed. Install with: pip install tensorflow. Error: {e}"
                )

            self.model = keras.models.load_model(self.model_path)

            # Validate loaded model
            if self.model is None:
                raise ValueError("Model loaded but is None")

            # Check if it's a Keras model
            if not hasattr(self.model, 'predict'):
                raise ValueError(
                    f"Model file does not contain a valid Keras model. "
                    f"Expected keras.Model, got {type(self.model).__name__}"
                )

            # Determine if regressor or classifier based on output shape
            output_shape = self.model.output_shape
            if isinstance(output_shape, list) and len(output_shape) > 1:
                # Multiple outputs
                output_dim = output_shape[-1]
            else:
                # Single output
                output_dim = output_shape[-1] if hasattr(output_shape, '__getitem__') else output_shape

            # For LSTM: if output dimension > 2, likely regression (price prediction)
            # If output dimension <= 2, likely classification (probabilities)
            self._is_regressor = output_dim > 2

            self.health_status = "healthy"
            logger.info(
                "lstm_model_loaded",
                model_path=str(self.model_path),
                model_name=self._model_name,
                output_shape=str(output_shape),
                is_regressor=self._is_regressor,
                health_status=self.health_status,
                file_size_bytes=file_size
            )

        except Exception as e:
            logger.error(
                "lstm_model_load_failed",
                model_path=str(self.model_path),
                model_name=self._model_name,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            self.health_status = "unhealthy"

    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        """Generate prediction."""
        start_time = time.time()

        # Validate model is loaded
        if self.model is None:
            logger.warning(
                "lstm_model_not_loaded",
                model_name=self.model_name,
                health_status=self.health_status,
                message="Model not loaded, cannot make prediction"
            )
            raise ValueError("Model not loaded")

        if self.health_status != "healthy":
            logger.warning(
                "lstm_model_unhealthy_status",
                model_name=self.model_name,
                health_status=self.health_status,
                message=f"Model health_status is '{self.health_status}', attempting prediction anyway"
            )

        try:
            # LSTM models expect sequence input (typically 60 timesteps × 49 features)
            # For now, we'll reshape single feature vector to (1, 1, feature_count)
            # TODO: Implement proper sequence handling when historical data is available
            features_array = np.array([request.features]).reshape(1, 1, -1)
            feature_count = len(request.features)

            # Validate feature count matches model expectations
            expected_feature_count = 49  # LSTM typically expects sequence data
            if feature_count != expected_feature_count:
                logger.warning(
                    "lstm_feature_count_mismatch",
                    model_name=self.model_name,
                    received_count=feature_count,
                    expected_count=expected_feature_count,
                    message="LSTM models typically expect sequence data, using single timestep"
                )

            # Get prediction from LSTM model
            prediction_raw = self.model.predict(features_array, verbose=0)

            if self._is_regressor:
                # Regression: extract scalar prediction
                if isinstance(prediction_raw, np.ndarray):
                    prediction_raw = float(prediction_raw.flatten()[0])

                # Normalize regressor output to [-1, 1] range
                current_price = request.context.get('current_price')
                if current_price is not None and current_price > 0:
                    return_pct = (prediction_raw - current_price) / current_price
                    max_return_range = 0.10  # 10% return maps to ±1.0
                    prediction_normalized = max(-1.0, min(1.0, return_pct / max_return_range))
                else:
                    # Fallback normalization
                    prediction_normalized = np.tanh((prediction_raw - 50000) / 10000)
            else:
                # Classification: extract probabilities
                if isinstance(prediction_raw, np.ndarray):
                    pred_proba = prediction_raw.flatten()
                else:
                    pred_proba = np.array(prediction_raw)

                if len(pred_proba) == 3:  # Assume SELL, HOLD, BUY
                    buy_prob = pred_proba[2] if len(pred_proba) > 2 else 0
                    sell_prob = pred_proba[0]
                    total_directional_prob = buy_prob + sell_prob
                    if total_directional_prob > 0:
                        prediction_normalized = (buy_prob - sell_prob) / total_directional_prob
                    else:
                        prediction_normalized = 0.0
                else:
                    # Binary: probability of positive class
                    prediction_normalized = (pred_proba[1] - 0.5) * 2.0 if len(pred_proba) > 1 else (pred_proba[0] - 0.5) * 2.0

            # Clamp to [-1, 1] range
            prediction_normalized = max(-1.0, min(1.0, float(prediction_normalized)))

            # Calculate confidence
            if self._is_regressor:
                confidence = min(1.0, abs(prediction_normalized))
            else:
                confidence = abs(prediction_normalized)

            computation_time_ms = (time.time() - start_time) * 1000

            # LSTM models don't typically provide feature importance
            feature_importance = {}

            # If prediction succeeded, ensure health_status is "healthy"
            if self.health_status != "healthy":
                old_status = self.health_status
                self.health_status = "healthy"
                logger.info(
                    "lstm_model_health_status_updated",
                    model_name=self.model_name,
                    old_status=old_status,
                    new_status="healthy",
                    prediction=prediction_normalized,
                    confidence=confidence,
                    message="Updating health_status to 'healthy' after successful prediction"
                )

            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=float(prediction_normalized),
                confidence=float(confidence),
                reasoning=f"LSTM model prediction: {prediction_raw:.4f}",
                features_used=[f"feature_{i}" for i in range(len(request.features))],
                feature_importance=feature_importance,
                computation_time_ms=computation_time_ms,
                health_status=self.health_status
            )

        except Exception as e:
            logger.error(
                "lstm_model_prediction_failed",
                model_name=self.model_name,
                error=str(e),
                exc_info=True
            )
            # Update health_status to degraded if it was healthy
            if self.health_status == "healthy":
                self.health_status = "degraded"

            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"Prediction failed: {str(e)}",
                features_used=[],
                feature_importance={},
                computation_time_ms=(time.time() - start_time) * 1000,
                health_status="degraded"
            )

    def get_model_info(self) -> Dict[str, Any]:
        """Return model information."""
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_type": self.model_type,
            "model_path": str(self.model_path),
            "health_status": self.health_status,
            "is_regressor": self._is_regressor
        }

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": self.health_status,
            "model_loaded": self.model is not None,
            "model_type": "regressor" if self._is_regressor else "classifier"
        }

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_type(self) -> str:
        return self._model_type
