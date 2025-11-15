"""
XGBoost model node implementation.

Implements MCP Model Node interface for XGBoost models.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
import pickle
import time
import numpy as np

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction
from agent.core.config import settings


class XGBoostNode(MCPModelNode):
    """XGBoost model node."""
    
    def __init__(self, model_path: Path):
        """Initialize XGBoost node."""
        self.model_path = model_path
        self.model = None
        self.model_name = model_path.stem
        self.model_version = "1.0.0"
        self.model_type = "xgboost"
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
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
            self.health_status = "healthy"
        except Exception as e:
            print(f"Error loading XGBoost model: {e}")
            self.health_status = "unhealthy"
    
    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        """Generate prediction."""
        start_time = time.time()
        
        try:
            if not self.model or self.health_status != "healthy":
                raise ValueError("Model not loaded or unhealthy")
            
            # Convert features to numpy array
            features_array = np.array([request.features]).reshape(1, -1)
            
            # Get prediction
            prediction_raw = self.model.predict(features_array)[0]
            
            # Normalize to -1.0 to +1.0 range
            # Assuming model outputs probability or class prediction
            # This is a simplification - actual normalization depends on model output
            if prediction_raw > 0.5:
                prediction_normalized = (prediction_raw - 0.5) * 2.0  # Scale to [0, 1] then [0, 2] then shift
            else:
                prediction_normalized = (prediction_raw - 0.5) * 2.0  # Scale to [-1, 0]
            
            # Clamp to [-1, 1]
            prediction_normalized = max(-1.0, min(1.0, prediction_normalized))
            
            # Calculate confidence (simplified)
            confidence = abs(prediction_normalized)
            
            computation_time_ms = (time.time() - start_time) * 1000
            
            return MCPModelPrediction(
                model_name=self.model_name,
                model_version=self.model_version,
                prediction=float(prediction_normalized),
                confidence=float(confidence),
                reasoning=f"XGBoost model prediction: {prediction_raw:.4f}",
                features_used=[f"feature_{i}" for i in range(len(request.features))],
                feature_importance={},  # Would need SHAP or feature_importances_
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
            "health_status": self.health_status
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": self.health_status,
            "model_loaded": self.model is not None
        }

