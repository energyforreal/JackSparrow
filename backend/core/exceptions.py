"""
Custom exception classes for the backend service.

Provides standardized exception types for better error handling and logging.
"""

from typing import Optional, Dict, Any


class BackendException(Exception):
    """Base exception for backend errors."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Initialize backend exception.
        
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "INTERNAL_ERROR"
        self.details = details or {}


class DatabaseError(BackendException):
    """Database operation error."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="DATABASE_ERROR", details=details)


class RedisError(BackendException):
    """Redis operation error."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="REDIS_ERROR", details=details)


class AgentServiceError(BackendException):
    """Agent service communication error."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="AGENT_SERVICE_ERROR", details=details)


class ValidationError(BackendException):
    """Input validation error."""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if field:
            details["field"] = field
        super().__init__(message, error_code="VALIDATION_ERROR", details=details)


class RateLimitError(BackendException):
    """Rate limit exceeded error."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(message, error_code="RATE_LIMIT_EXCEEDED", details=details)


class ExternalAPIError(BackendException):
    """External API call error."""
    
    def __init__(self, message: str, api_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        if details is None:
            details = {}
        if api_name:
            details["api_name"] = api_name
        super().__init__(message, error_code="EXTERNAL_API_ERROR", details=details)
