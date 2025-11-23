"""
MCP Model Node interface.

Base interface for all ML model nodes implementing MCP Model Protocol.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MCPModelRequest(BaseModel):
    """MCP Model Protocol request."""
    model_config = ConfigDict(protected_namespaces=())
    request_id: str
    features: List[float]
    context: Dict[str, Any]
    require_explanation: bool = True


class MCPModelPrediction(BaseModel):
    """MCP Model Protocol prediction structure."""
    model_config = ConfigDict(protected_namespaces=())
    model_name: str
    model_version: str
    prediction: float  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Human-readable explanation
    features_used: List[str]
    feature_importance: Dict[str, float]
    computation_time_ms: float
    health_status: str


class MCPModelNode(ABC):
    """Base interface for MCP Model Nodes."""
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return model identifier."""
        pass
    
    @property
    @abstractmethod
    def model_version(self) -> str:
        """Return model version."""
        pass
    
    @property
    @abstractmethod
    def model_type(self) -> str:
        """Return model type (xgboost, lstm, etc.)."""
        pass
    
    @abstractmethod
    async def initialize(self):
        """Initialize model node."""
        pass
    
    @abstractmethod
    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        """Generate prediction following MCP Model Protocol."""
        pass
    
    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Return model capabilities and requirements."""
        pass
    
    @abstractmethod
    async def get_health_status(self) -> Dict[str, Any]:
        """Get model health status."""
        pass

