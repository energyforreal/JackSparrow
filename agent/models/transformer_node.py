"""
Transformer model node implementation.

Implements MCP Model Node interface for Transformer models (ONNX or PyTorch).
"""

from typing import Dict, Any, List
from pathlib import Path
import time
import numpy as np
import structlog
from datetime import datetime

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction

logger = structlog.get_logger()


class TransformerNode(MCPModelNode):
    """Transformer model node for ONNX or PyTorch models."""

    def __init__(self, model_path: Path):
        """Initialize Transformer node."""
        self.model_path = model_path
        self.model = None
        self._model_name = model_path.stem
        self._model_version = "1.0.0"
        self._model_type = "transformer"
        self._is_regressor = None  # Will be set during initialization
        self._runtime = None  # ONNX or PyTorch
        self.health_status = "unknown"

    @classmethod
    async def load_from_file(cls, model_path: Path) -> "TransformerNode":
        """Load Transformer model from file."""
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
            if file_size < 1000:  # Transformer models are typically large
                logger.warning(
                    "transformer_model_suspicious_size",
                    model_path=str(self.model_path),
                    file_size=file_size,
                    message="Model file is unusually small for a Transformer model - may be corrupted"
                )

            # Determine model format and load accordingly
            file_extension = self.model_path.suffix.lower()

            if file_extension == '.onnx':
                # Load ONNX model
                try:
                    import onnxruntime as ort
                    self._runtime = "onnx"
                    self.model = ort.InferenceSession(str(self.model_path))
                    logger.info(
                        "transformer_onnx_model_loaded",
                        model_path=str(self.model_path),
                        inputs=len(self.model.get_inputs()),
                        outputs=len(self.model.get_outputs())
                    )
                except ImportError as e:
                    raise ImportError(
                        f"ONNX Runtime not installed. Install with: pip install onnxruntime. Error: {e}"
                    )

            elif file_extension in ['.pt', '.pth']:
                # Load PyTorch model
                try:
                    import torch
                    self._runtime = "pytorch"
                    self.model = torch.load(self.model_path, map_location='cpu')
                    self.model.eval()  # Set to evaluation mode
                    logger.info(
                        "transformer_pytorch_model_loaded",
                        model_path=str(self.model_path),
                        model_type=type(self.model).__name__
                    )
                except ImportError as e:
                    raise ImportError(
                        f"PyTorch not installed. Install with: pip install torch. Error: {e}"
                    )
            else:
                raise ValueError(
                    f"Unsupported file format: {file_extension}. "
                    f"Expected .onnx for ONNX models or .pt/.pth for PyTorch models."
                )

            # Validate loaded model
            if self.model is None:
                raise ValueError("Model loaded but is None")

            # Determine if regressor or classifier based on output structure
            if self._runtime == "onnx":
                output_names = [output.name for output in self.model.get_outputs()]
                output_dims = [output.shape for output in self.model.get_outputs()]
                # Assume first output determines type
                if output_dims and len(output_dims[0]) > 0:
                    output_dim = output_dims[0][-1]
                    self._is_regressor = output_dim > 2
            elif self._runtime == "pytorch":
                # Try to infer from model structure
                try:
                    # Check if model has a classification head
                    self._is_regressor = not hasattr(self.model, 'num_classes') or self.model.num_classes <= 2
                except:
                    # Fallback: assume regression if uncertain
                    self._is_regressor = True

            self.health_status = "healthy"
            logger.info(
                "transformer_model_loaded",
                model_path=str(self.model_path),
                model_name=self._model_name,
                runtime=self._runtime,
                is_regressor=self._is_regressor,
                health_status=self.health_status,
                file_size_bytes=file_size
            )

        except Exception as e:
            logger.error(
                "transformer_model_load_failed",
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
                "transformer_model_not_loaded",
                model_name=self.model_name,
                health_status=self.health_status,
                message="Model not loaded, cannot make prediction"
            )
            raise ValueError("Model not loaded")

        if self.health_status != "healthy":
            logger.warning(
                "transformer_model_unhealthy_status",
                model_name=self.model_name,
                health_status=self.health_status,
                message=f"Model health_status is '{self.health_status}', attempting prediction anyway"
            )

        try:
            # Convert features to numpy array
            features_array = np.array([request.features], dtype=np.float32)
            feature_count = len(request.features)

            # Validate feature count matches model expectations
            expected_feature_count = 50  # Same as other models
            if feature_count != expected_feature_count:
                error_msg = (
                    f"Feature count mismatch: received {feature_count} features, "
                    f"but model expects {expected_feature_count} features. "
                    f"Model: {self.model_name}."
                )
                logger.error(
                    "transformer_feature_count_mismatch",
                    model_name=self.model_name,
                    received_count=feature_count,
                    expected_count=expected_feature_count
                )
                raise ValueError(error_msg)

            # Run inference based on runtime
            if self._runtime == "onnx":
                # ONNX inference
                input_name = self.model.get_inputs()[0].name
                prediction_raw = self.model.run(None, {input_name: features_array})[0]

                if isinstance(prediction_raw, np.ndarray):
                    prediction_raw = prediction_raw.flatten()

            elif self._runtime == "pytorch":
                # PyTorch inference
                import torch
                with torch.no_grad():
                    input_tensor = torch.from_numpy(features_array)
                    output_tensor = self.model(input_tensor)
                    prediction_raw = output_tensor.numpy().flatten()

            # Process prediction output
            if self._is_regressor:
                # Regression: extract scalar prediction
                prediction_raw = float(prediction_raw[0]) if isinstance(prediction_raw, (list, np.ndarray)) else float(prediction_raw)

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
                if isinstance(prediction_raw, (list, np.ndarray)) and len(prediction_raw) > 1:
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
                else:
                    # Single output, assume classification probability
                    prediction_normalized = (float(prediction_raw) - 0.5) * 2.0

            # Clamp to [-1, 1] range
            prediction_normalized = max(-1.0, min(1.0, float(prediction_normalized)))

            # Calculate confidence
            if self._is_regressor:
                confidence = min(1.0, abs(prediction_normalized))
            else:
                confidence = abs(prediction_normalized)

            computation_time_ms = (time.time() - start_time) * 1000

            # Transformer models don't typically provide feature importance
            feature_importance = {}

            # If prediction succeeded, ensure health_status is "healthy"
            if self.health_status != "healthy":
                old_status = self.health_status
                self.health_status = "healthy"
                logger.info(
                    "transformer_model_health_status_updated",
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
                reasoning=f"Transformer model prediction: {prediction_raw}",
                features_used=[f"feature_{i}" for i in range(len(request.features))],
                feature_importance=feature_importance,
                computation_time_ms=computation_time_ms,
                health_status=self.health_status
            )

        except Exception as e:
            logger.error(
                "transformer_model_prediction_failed",
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
            "is_regressor": self._is_regressor,
            "runtime": self._runtime
        }

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": self.health_status,
            "model_loaded": self.model is not None,
            "model_type": "regressor" if self._is_regressor else "classifier",
            "runtime": self._runtime
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
