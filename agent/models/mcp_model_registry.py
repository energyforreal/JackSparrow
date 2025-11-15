"""
MCP Model Registry.

Manages all ML model nodes and implements MCP Model Protocol.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import time
import asyncio

from agent.models.mcp_model_node import MCPModelNode, MCPModelRequest, MCPModelPrediction, MCPModelResponse


class MCPModelResponse(BaseModel):
    """MCP Model Protocol response."""
    request_id: str
    predictions: List[MCPModelPrediction]
    consensus_prediction: float  # Weighted average
    consensus_confidence: float
    healthy_models: int
    total_models: int
    timestamp: datetime


class MCPModelRegistry:
    """MCP Model Registry managing all model nodes."""
    
    def __init__(self):
        """Initialize model registry."""
        self.models: Dict[str, MCPModelNode] = {}
        self.model_weights: Dict[str, float] = {}
    
    async def initialize(self):
        """Initialize model registry."""
        # Models will be registered via model discovery
        pass
    
    async def shutdown(self):
        """Shutdown all models."""
        for model in self.models.values():
            try:
                # Models may have cleanup methods
                pass
            except Exception as e:
                print(f"Error shutting down model {model.model_name}: {e}")
    
    def register_model(self, model: MCPModelNode, weight: float = 1.0):
        """Register model node."""
        self.models[model.model_name] = model
        self.model_weights[model.model_name] = weight
        
        # Normalize weights
        self._normalize_weights()
    
    def unregister_model(self, model_name: str):
        """Unregister model node."""
        if model_name in self.models:
            del self.models[model_name]
        if model_name in self.model_weights:
            del self.model_weights[model_name]
        self._normalize_weights()
    
    def _normalize_weights(self):
        """Normalize model weights to sum to 1.0."""
        if not self.model_weights:
            return
        
        total_weight = sum(self.model_weights.values())
        if total_weight > 0:
            self.model_weights = {
                name: weight / total_weight
                for name, weight in self.model_weights.items()
            }
    
    async def get_predictions(self, request: MCPModelRequest) -> MCPModelResponse:
        """Get predictions from all healthy models."""
        
        if not self.models:
            return MCPModelResponse(
                request_id=request.request_id,
                predictions=[],
                consensus_prediction=0.0,
                consensus_confidence=0.0,
                healthy_models=0,
                total_models=0,
                timestamp=datetime.utcnow()
            )
        
        # Get predictions from all models in parallel
        predictions: List[MCPModelPrediction] = []
        
        tasks = []
        for model in self.models.values():
            tasks.append(self._get_prediction_safe(model, request))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, MCPModelPrediction):
                predictions.append(result)
            elif isinstance(result, Exception):
                print(f"Error getting prediction: {result}")
        
        # Filter healthy models
        healthy_predictions = [
            pred for pred in predictions
            if pred.health_status == "healthy"
        ]
        
        # Calculate consensus
        if healthy_predictions:
            # Weighted average based on confidence and model weight
            total_weight = 0.0
            weighted_sum = 0.0
            confidence_sum = 0.0
            
            for pred in healthy_predictions:
                model_weight = self.model_weights.get(pred.model_name, 1.0 / len(healthy_predictions))
                combined_weight = model_weight * pred.confidence
                
                weighted_sum += pred.prediction * combined_weight
                total_weight += combined_weight
                confidence_sum += pred.confidence
            
            if total_weight > 0:
                consensus_prediction = weighted_sum / total_weight
                consensus_confidence = confidence_sum / len(healthy_predictions)
            else:
                consensus_prediction = 0.0
                consensus_confidence = 0.0
        else:
            consensus_prediction = 0.0
            consensus_confidence = 0.0
        
        return MCPModelResponse(
            request_id=request.request_id,
            predictions=predictions,
            consensus_prediction=consensus_prediction,
            consensus_confidence=consensus_confidence,
            healthy_models=len(healthy_predictions),
            total_models=len(self.models),
            timestamp=datetime.utcnow()
        )
    
    async def _get_prediction_safe(
        self,
        model: MCPModelNode,
        request: MCPModelRequest
    ) -> Optional[MCPModelPrediction]:
        """Safely get prediction from model."""
        try:
            return await model.predict(request)
        except Exception as e:
            print(f"Error getting prediction from {model.model_name}: {e}")
            # Return degraded prediction
            return MCPModelPrediction(
                model_name=model.model_name,
                model_version=model.model_version,
                prediction=0.0,
                confidence=0.0,
                reasoning=f"Model error: {str(e)}",
                features_used=[],
                feature_importance={},
                computation_time_ms=0.0,
                health_status="degraded"
            )
    
    def update_model_weight(self, model_name: str, weight: float):
        """Update model weight."""
        if model_name in self.models:
            self.model_weights[model_name] = weight
            self._normalize_weights()
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all models."""
        
        health_statuses = {}
        healthy_count = 0
        
        for model_name, model in self.models.items():
            try:
                status = await model.get_health_status()
                health_statuses[model_name] = status
                if status.get("status") == "healthy":
                    healthy_count += 1
            except Exception as e:
                health_statuses[model_name] = {
                    "status": "unknown",
                    "error": str(e)
                }
        
        return {
            "total_models": len(self.models),
            "healthy_models": healthy_count,
            "model_statuses": health_statuses
        }

