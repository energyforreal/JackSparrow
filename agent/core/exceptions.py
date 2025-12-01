"""
Custom exception classes for the agent service.

Provides standardized exception types for better error handling and logging.
"""

from typing import Optional, Dict, Any


class AgentException(Exception):
    """Base exception for agent errors."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Initialize agent exception.
        
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "INTERNAL_ERROR"
        self.details = details or {}


class ModelError(AgentException):
    """Model prediction or loading error."""
    
    def __init__(self, message: str, model_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if model_name:
            details["model_name"] = model_name
        super().__init__(message, error_code="MODEL_ERROR", details=details)


class FeatureComputationError(AgentException):
    """Feature computation error."""
    
    def __init__(self, message: str, feature_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if feature_name:
            details["feature_name"] = feature_name
        super().__init__(message, error_code="FEATURE_COMPUTATION_ERROR", details=details)


class MarketDataError(AgentException):
    """Market data retrieval error."""
    
    def __init__(self, message: str, symbol: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if symbol:
            details["symbol"] = symbol
        super().__init__(message, error_code="MARKET_DATA_ERROR", details=details)


class ReasoningError(AgentException):
    """Reasoning engine error."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="REASONING_ERROR", details=details)


class RiskViolationError(AgentException):
    """Risk management violation error."""
    
    def __init__(self, message: str, violation_type: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if violation_type:
            details["violation_type"] = violation_type
        super().__init__(message, error_code="RISK_VIOLATION", details=details)
