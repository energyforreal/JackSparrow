"""
XGBoost model node implementation.

Implements MCP Model Node interface for XGBoost models.
"""

from typing import Dict, Any
from pathlib import Path
import pickle
import sys
import types
import time
import warnings
import numpy as np
import structlog
from xgboost import XGBClassifier

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction
from agent.core.config import settings

logger = structlog.get_logger()


def _ensure_pickle_compatibility() -> None:
    """Register compatibility shims for legacy-pickled XGBoost models."""
    module_name = "XGBClassifier"
    if module_name in sys.modules:
        return

    shim = types.ModuleType(module_name)

    def _module_getattr(name: str):
        if name == "XGBClassifier":
            return XGBClassifier
        if hasattr(np, name):
            return getattr(np, name)
        raise AttributeError(f"module '{module_name}' has no attribute '{name}'")

    shim.__getattr__ = _module_getattr  # type: ignore[attr-defined]
    shim.XGBClassifier = XGBClassifier
    shim.dtype = np.dtype
    shim.ndarray = np.ndarray
    sys.modules[module_name] = shim


class XGBoostNode(MCPModelNode):
    """XGBoost model node."""
    
    def __init__(self, model_path: Path):
        """Initialize XGBoost node."""
        self.model_path = model_path
        self.model = None
        self._model_name = model_path.stem
        self._model_version = "1.0.0"
        self._model_type = "xgboost"
        self.health_status = "unknown"
    
    @classmethod
    async def load_from_file(cls, model_path: Path) -> "XGBoostNode":
        """Load XGBoost model from file."""
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
            if file_size < 100:  # XGBoost models are typically at least a few KB
                logger.warning(
                    "xgboost_model_suspicious_size",
                    model_path=str(self.model_path),
                    file_size=file_size,
                    message="Model file is unusually small - may be corrupted"
                )
            
            # Try to validate pickle file format before loading
            try:
                with open(self.model_path, "rb") as f:
                    # Read first few bytes to check pickle magic bytes
                    magic_bytes = f.read(4)
                    # Pickle files typically start with specific byte sequences
                    # Python 3 pickle: b'\x80\x03' or b'\x80\x04' or b'\x80\x05'
                    if not magic_bytes.startswith(b'\x80'):
                        logger.warning(
                            "xgboost_model_invalid_format",
                            model_path=str(self.model_path),
                            magic_bytes=magic_bytes.hex(),
                            message="File does not appear to be a valid pickle file"
                        )
            except Exception as e:
                logger.warning(
                    "xgboost_model_format_check_failed",
                    model_path=str(self.model_path),
                    error=str(e),
                    message="Could not validate file format before loading"
                )
            
            _ensure_pickle_compatibility()
            
            # Catch XGBoost compatibility warnings and log them informatively
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                
                try:
                    with open(self.model_path, "rb") as f:
                        self.model = pickle.load(f)
                except (pickle.UnpicklingError, EOFError, ValueError) as e:
                    # These errors typically indicate corrupted pickle files
                    error_msg = str(e)
                    if "invalid load key" in error_msg.lower() or "unpickling" in error_msg.lower():
                        raise ValueError(
                            f"Model file appears to be corrupted or in an incompatible format: {error_msg}. "
                            f"Please regenerate the model file or remove it from the model storage directory."
                        ) from e
                    raise
                
                # Check for XGBoost compatibility warnings
                xgboost_warnings = [
                    warning for warning in w 
                    if "xgboost" in str(warning.message).lower() or 
                       "serialized model" in str(warning.message).lower() or
                       "older version" in str(warning.message).lower()
                ]
                
                if xgboost_warnings:
                    logger.info(
                        "xgboost_model_compatibility_warning",
                        model_path=str(self.model_path),
                        model_name=self._model_name,
                        warning_message=str(xgboost_warnings[0].message),
                        message="Model loaded successfully but was serialized with an older XGBoost version. "
                               "For best compatibility, re-export the model using Booster.save_model() from the original version, "
                               "then load it in the current version. See: https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html"
                    )
            
            # Validate loaded model
            if self.model is None:
                raise ValueError("Model loaded but is None")
            
            self.health_status = "healthy"
            logger.info(
                "xgboost_model_loaded",
                model_path=str(self.model_path),
                model_name=self._model_name,
                health_status=self.health_status,
                file_size_bytes=file_size
            )
        except (pickle.UnpicklingError, EOFError, ValueError) as e:
            # Corrupted file errors
            error_msg = str(e)
            is_corrupted = (
                "invalid load key" in error_msg.lower() or
                "unpickling" in error_msg.lower() or
                "corrupted" in error_msg.lower() or
                "eof" in error_msg.lower()
            )
            
            logger.error(
                "xgboost_model_load_failed",
                model_path=str(self.model_path),
                model_name=self._model_name,
                error=error_msg,
                error_type=type(e).__name__,
                is_corrupted=is_corrupted,
                message="Model file failed to load. If the file is corrupted, remove it from the model storage directory "
                       "or regenerate it. The agent will continue without this model." if is_corrupted else None,
                exc_info=True
            )
            self.health_status = "unhealthy"
        except Exception as e:
            # Other errors
            logger.error(
                "xgboost_model_load_failed",
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
        
        try:
            if not self.model or self.health_status != "healthy":
                raise ValueError("Model not loaded or unhealthy")
            
            # Convert features to numpy array
            features_array = np.array([request.features]).reshape(1, -1)
            
            # Detect model output type and get prediction
            # Try to use predict_proba() first (for probability outputs)
            prediction_raw = None
            is_probability = False
            
            if hasattr(self.model, 'predict_proba'):
                try:
                    proba = self.model.predict_proba(features_array)[0]
                    # For binary classification, use probability of positive class
                    if len(proba) == 2:
                        prediction_raw = proba[1]  # Probability of class 1
                        is_probability = True
                    else:
                        # Multi-class: use max probability
                        prediction_raw = np.max(proba)
                        is_probability = True
                except Exception:
                    # Fallback to predict() if predict_proba fails
                    prediction_raw = self.model.predict(features_array)[0]
            else:
                # No predict_proba, use predict()
                prediction_raw = self.model.predict(features_array)[0]
            
            # Normalize to -1.0 to +1.0 range
            if is_probability:
                # Probability output [0, 1] -> [-1, 1]
                # Map: 0.0 -> -1.0, 0.5 -> 0.0, 1.0 -> +1.0
                prediction_normalized = (prediction_raw - 0.5) * 2.0
            else:
                # Class label output (0 or 1) or other numeric output
                # If it's a binary class (0 or 1), map: 0 -> -1, 1 -> +1
                if prediction_raw in [0, 1] or (isinstance(prediction_raw, (int, np.integer)) and prediction_raw in [0, 1]):
                    prediction_normalized = (prediction_raw * 2.0) - 1.0  # 0 -> -1, 1 -> +1
                else:
                    # Assume it's already in a reasonable range, normalize to [-1, 1]
                    # This handles regression outputs or other numeric outputs
                    if prediction_raw > 1.0 or prediction_raw < 0.0:
                        # If outside [0, 1], assume it needs normalization
                        # Use sigmoid-like normalization: map to [-1, 1]
                        prediction_normalized = np.tanh(prediction_raw)
                    else:
                        # Already in [0, 1], normalize to [-1, 1]
                        prediction_normalized = (prediction_raw - 0.5) * 2.0
            
            # Clamp to [-1, 1] to ensure valid range
            prediction_normalized = max(-1.0, min(1.0, float(prediction_normalized)))
            
            # Calculate confidence based on distance from neutral (0.0)
            # For probabilities: confidence is how far from 0.5
            # For normalized: confidence is absolute value
            if is_probability:
                # Confidence is how certain the model is (distance from 0.5)
                confidence = abs(prediction_raw - 0.5) * 2.0  # [0, 1] range
            else:
                # Confidence is absolute value of normalized prediction
                confidence = abs(prediction_normalized)
            
            computation_time_ms = (time.time() - start_time) * 1000
            
            # Calculate feature importance using model.feature_importances_
            feature_importance = {}
            if hasattr(self.model, 'feature_importances_'):
                importances = self.model.feature_importances_
                # Get feature names from context if available, otherwise use indices
                feature_names = request.context.get('feature_names', None)
                if feature_names and len(feature_names) == len(importances):
                    # Use provided feature names
                    feature_importance = {
                        name: float(importance)
                        for name, importance in zip(feature_names, importances)
                    }
                else:
                    # Use feature indices
                    feature_importance = {
                        f"feature_{i}": float(importance)
                        for i, importance in enumerate(importances)
                    }
            
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=float(prediction_normalized),
                confidence=float(confidence),
                reasoning=f"XGBoost model prediction: {prediction_raw:.4f}",
                features_used=[f"feature_{i}" for i in range(len(request.features))],
                feature_importance=feature_importance,
                computation_time_ms=computation_time_ms,
                health_status=self.health_status
            )
        except Exception as e:
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"Prediction failed: {str(e)}",
                features_used=[],
                feature_importance={},  # Empty on error
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
            "health_status": self.health_status
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": self.health_status,
            "model_loaded": self.model is not None
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

