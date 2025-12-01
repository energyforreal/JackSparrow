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
    """Register compatibility shims for legacy-pickled XGBoost models.
    
    This function registers multiple shim modules to handle legacy pickle files
    that were saved with different import paths. It must be called before
    any pickle.load() operations on XGBoost models.
    """
    # Shim 1: Top-level "XGBClassifier" module (for models pickled with old import style)
    module_name = "XGBClassifier"
    if module_name not in sys.modules:
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
        logger.debug("pickle_compatibility_shim_registered", module=module_name)
    
    # Shim 2: Ensure xgb module exists (some models may reference xgb.XGBClassifier)
    if "xgb" not in sys.modules:
        import xgboost as xgb
        sys.modules["xgb"] = xgb
        logger.debug("pickle_compatibility_shim_registered", module="xgb")
    
    # Shim 3: Ensure xgboost module has XGBClassifier attribute
    if "xgboost" in sys.modules:
        import xgboost
        if not hasattr(xgboost, 'XGBClassifier'):
            xgboost.XGBClassifier = XGBClassifier
            logger.debug("pickle_compatibility_xgboost_module_updated")


# Register compatibility shims immediately at module load time
# This ensures they're available before any model loading attempts
_ensure_pickle_compatibility()


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
                        raise ValueError(
                            f"File does not appear to be a valid pickle file. "
                            f"Expected magic bytes starting with \\x80, got: {magic_bytes.hex()}"
                        )
                    
                    # Try a quick validation by attempting to peek at pickle stream
                    # This helps catch corruption early before full load attempt
                    f.seek(0)
                    try:
                        # Use pickletools to validate structure (if available)
                        import pickletools
                        # Just check if we can read the first few opcodes
                        # This is a lightweight check that doesn't fully unpickle
                        pickle_data = f.read(min(1024, file_size))
                        pickletools.dis(pickle_data, out=None)
                    except ImportError:
                        # pickletools not available, skip this check
                        pass
                    except Exception as peek_error:
                        # If peek fails, it might be corrupted
                        # But we'll still try full load as it might be a false positive
                        logger.warning(
                            "xgboost_model_format_peek_warning",
                            model_path=str(self.model_path),
                            error=str(peek_error),
                            message="Quick format validation failed, but will attempt full load"
                        )
            except ValueError as e:
                # Invalid format detected - fail fast
                logger.error(
                    "xgboost_model_invalid_format",
                    model_path=str(self.model_path),
                    magic_bytes=magic_bytes.hex() if 'magic_bytes' in locals() else "unknown",
                    error=str(e),
                    message="File format validation failed before loading attempt"
                )
                raise ValueError(
                    f"Model file format validation failed: {e}. "
                    f"File may be corrupted or not a valid pickle file."
                ) from e
            except Exception as e:
                logger.warning(
                    "xgboost_model_format_check_failed",
                    model_path=str(self.model_path),
                    error=str(e),
                    message="Could not validate file format before loading, proceeding with load attempt"
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
            
            # Validate that loaded object is actually an XGBoost model, not a numpy array or other type
            model_type = type(self.model).__name__
            # Accept both XGBClassifier (has predict_proba) and XGBRegressor (has predict)
            # Both are valid XGBoost models for trading predictions
            is_xgboost_model = (
                hasattr(self.model, 'predict') and 
                not isinstance(self.model, np.ndarray) and
                ('XGB' in model_type or 'Booster' in model_type)
            )
            
            if isinstance(self.model, np.ndarray):
                # Check if it's feature names (common mistake)
                if self.model.dtype == object and len(self.model) > 0:
                    sample_values = str(self.model.flat[:5]) if self.model.size > 0 else ""
                    if any(keyword in sample_values.lower() for keyword in ['sma', 'rsi', 'macd', 'feature']):
                        raise ValueError(
                            f"Model file contains feature names (numpy array) instead of an XGBoost model. "
                            f"Array shape: {self.model.shape}, dtype: {self.model.dtype}. "
                            f"Sample values: {self.model.flat[:5] if self.model.size > 0 else 'empty'}. "
                            f"This indicates the model file was saved incorrectly - it contains feature names "
                            f"instead of the trained model. Please regenerate the model file with the actual "
                            f"XGBoost model object. "
                            f"To fix: Re-train and save the model using 'pickle.dump(model, file)' where 'model' "
                            f"is an XGBClassifier instance, not feature names."
                        )
                else:
                    raise ValueError(
                        f"Model file contains a numpy array instead of an XGBoost model. "
                        f"Array shape: {self.model.shape}, dtype: {self.model.dtype}. "
                        f"The pickle file may contain model predictions or other data instead of the model itself. "
                        f"Please check the model file format and regenerate if necessary."
                    )
            
            if not is_xgboost_model:
                # Check if it's a dictionary containing the model
                if isinstance(self.model, dict):
                    # Try to find the model in the dictionary
                    possible_keys = ['model', 'classifier', 'xgb_model', 'xgboost_model', 'estimator']
                    for key in possible_keys:
                        if key in self.model and hasattr(self.model[key], 'predict'):
                            logger.info(
                                "xgboost_model_extracted_from_dict",
                                model_path=str(self.model_path),
                                dict_key=key,
                                message="Model was stored in a dictionary, extracted successfully"
                            )
                            self.model = self.model[key]
                            is_xgboost_model = True
                            break
                    
                    if not is_xgboost_model:
                        raise ValueError(
                            f"Model file contains a dictionary but no XGBoost model found. "
                            f"Dictionary keys: {list(self.model.keys())}. "
                            f"Expected keys: {possible_keys}"
                        )
                else:
                    # Check if it's an XGBRegressor (valid model, just doesn't have predict_proba)
                    if 'XGBRegressor' in model_type or 'Regressor' in model_type:
                        # XGBRegressor is valid - it has predict() but not predict_proba()
                        # The prediction code already handles this by using predict() as fallback
                        is_xgboost_model = True
                        logger.info(
                            "xgboost_regressor_detected",
                            model_path=str(self.model_path),
                            model_type=model_type,
                            message="XGBRegressor detected (valid model, will use predict() method)"
                        )
                    else:
                        raise ValueError(
                            f"Model file does not contain a valid XGBoost model. "
                            f"Loaded type: {model_type}. "
                            f"Expected XGBClassifier or XGBRegressor (or XGBoost Booster object) with 'predict' method."
                        )
            
            # Final validation: ensure model has required methods
            if not hasattr(self.model, 'predict'):
                raise ValueError(f"Loaded model object (type: {model_type}) does not have 'predict' method")
            
            self.health_status = "healthy"
            logger.info(
                "xgboost_model_loaded",
                model_path=str(self.model_path),
                model_name=self._model_name,
                model_type=model_type,
                health_status=self.health_status,
                file_size_bytes=file_size,
                has_predict=hasattr(self.model, 'predict'),
                has_predict_proba=hasattr(self.model, 'predict_proba')
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
        
        # Validate model is loaded
        # Use 'is None' check instead of 'not self.model' to avoid numpy array ambiguity
        if self.model is None:
            logger.warning(
                "xgboost_model_not_loaded",
                model_name=self.model_name,
                health_status=self.health_status,
                message="Model not loaded, cannot make prediction"
            )
            raise ValueError("Model not loaded")
        
        # If health_status is not healthy, log it but still attempt prediction
        # (model might be functional even if status is unknown)
        if self.health_status != "healthy":
            logger.warning(
                "xgboost_model_unhealthy_status",
                model_name=self.model_name,
                health_status=self.health_status,
                message=f"Model health_status is '{self.health_status}', attempting prediction anyway"
            )
        
        try:
            
            # Convert features to numpy array
            features_array = np.array([request.features]).reshape(1, -1)
            feature_count = len(request.features)
            
            # Validate feature count matches model expectations
            # XGBoost models trained with FEATURE_LIST expect 50 features
            expected_feature_count = 50
            if feature_count != expected_feature_count:
                # Log missing features for debugging
                expected_features = [
                    'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
                    'ema_12', 'ema_26', 'ema_50',
                    'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
                    'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
                    'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
                    'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
                    'momentum_10', 'momentum_20',
                    'macd', 'macd_signal', 'macd_histogram',
                    'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
                    'trend_strength',
                    'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
                    'atr_14', 'atr_20',
                    'volatility_10', 'volatility_20',
                    'volume_sma_20', 'volume_ratio', 'obv',
                    'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
                    'returns_1h', 'returns_24h'
                ]
                received_features = list(request.features.keys())
                missing_features = [f for f in expected_features if f not in received_features]
                
                error_msg = (
                    f"Feature count mismatch: received {feature_count} features, "
                    f"but model expects {expected_feature_count} features. "
                    f"Model: {self.model_name}. "
                    f"This indicates a mismatch between feature computation and model training. "
                    f"Please ensure all {expected_feature_count} features are computed and passed to the model. "
                    f"Missing features: {missing_features[:10]}{'...' if len(missing_features) > 10 else ''}"
                )
                logger.error(
                    "xgboost_feature_count_mismatch",
                    model_name=self.model_name,
                    received_count=feature_count,
                    expected_count=expected_feature_count,
                    missing_features=missing_features,
                    received_features=received_features[:10],  # Log first 10 for debugging
                    message=error_msg
                )
                raise ValueError(error_msg)
            
            # Detect model output type and get prediction
            # Try to use predict_proba() first (for probability outputs)
            prediction_raw = None
            is_probability = False
            
            # Validate model type before prediction
            if isinstance(self.model, np.ndarray):
                raise ValueError(
                    f"Model is a numpy array, not an XGBoost model. "
                    f"This indicates the model file was saved incorrectly. "
                    f"Model type: {type(self.model).__name__}, shape: {self.model.shape if hasattr(self.model, 'shape') else 'N/A'}"
                )
            
            if not hasattr(self.model, 'predict'):
                raise ValueError(
                    f"Model object does not have 'predict' method. "
                    f"Model type: {type(self.model).__name__}, "
                    f"Available methods: {[m for m in dir(self.model) if not m.startswith('_')][:10]}"
                )
            
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
                except Exception as e:
                    # Fallback to predict() if predict_proba fails
                    logger.warning(
                        "xgboost_predict_proba_failed",
                        model_name=self.model_name,
                        error=str(e),
                        message="predict_proba failed, falling back to predict()"
                    )
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
            
            # If prediction succeeded, ensure health_status is "healthy"
            # This handles cases where status might have been "unknown" or incorrectly set
            # A successful prediction with valid values indicates the model is functioning correctly
            if self.health_status != "healthy":
                old_status = self.health_status
                self.health_status = "healthy"
                logger.info(
                    "xgboost_model_health_status_updated",
                    model_name=self.model_name,
                    old_status=old_status,
                    new_status="healthy",
                    prediction=prediction_normalized,
                    confidence=confidence,
                    message="Updating health_status to 'healthy' after successful prediction with valid output"
                )
            
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=float(prediction_normalized),
                confidence=float(confidence),
                reasoning=f"XGBoost model prediction: {prediction_raw:.4f}",
                features_used=[f"feature_{i}" for i in range(len(request.features))],
                feature_importance=feature_importance,
                computation_time_ms=computation_time_ms,
                health_status=self.health_status  # Now guaranteed to be "healthy" if prediction succeeded
            )
        except Exception as e:
            # If prediction fails, mark as degraded
            logger.error(
                "xgboost_model_prediction_failed",
                model_name=self.model_name,
                error=str(e),
                health_status=self.health_status,
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

