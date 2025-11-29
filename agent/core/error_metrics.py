"""Error metrics tracking for monitoring error rates and patterns.

Provides error counting, rate tracking, and summary statistics for operational monitoring.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field

from agent.core.logging_utils import get_session_id


@dataclass
class ErrorMetric:
    """Single error metric entry."""
    timestamp: float
    error_type: str
    component: Optional[str] = None
    message: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class ErrorSummary:
    """Error summary statistics."""
    session_id: str
    total_errors: int
    total_warnings: int
    errors_by_type: Dict[str, int]
    errors_by_component: Dict[str, int]
    warnings_by_key: Dict[str, int]
    recent_errors: List[Dict[str, Any]]
    error_rate_per_minute: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ErrorMetrics:
    """Track error metrics for monitoring and alerting."""
    
    def __init__(self, window_size: int = 1000, time_window_seconds: int = 300):
        """Initialize error metrics tracker.
        
        Args:
            window_size: Maximum number of recent errors to keep in memory
            time_window_seconds: Time window for error rate calculation (default: 5 minutes)
        """
        self.session_id = get_session_id() or "unknown"
        self.window_size = window_size
        self.time_window_seconds = time_window_seconds
        
        # Error tracking
        self.error_counts_by_type: Dict[str, int] = {}
        self.error_counts_by_component: Dict[str, int] = {}
        self.recent_errors: deque = deque(maxlen=window_size)
        
        # Warning tracking
        self.warning_counts: Dict[str, int] = {}
        
        # Rate tracking (for error rate calculation)
        self.error_timestamps: deque = deque(maxlen=window_size)
        
        self._start_time = time.time()
    
    def record_error(
        self,
        error_type: str,
        component: Optional[str] = None,
        message: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> None:
        """Record an error metric.
        
        Args:
            error_type: Type of error (exception class name)
            component: Component where error occurred
            message: Error message
            correlation_id: Correlation ID for request tracking
        """
        timestamp = time.time()
        
        # Update counts
        self.error_counts_by_type[error_type] = self.error_counts_by_type.get(error_type, 0) + 1
        if component:
            self.error_counts_by_component[component] = self.error_counts_by_component.get(component, 0) + 1
        
        # Track timestamp for rate calculation
        self.error_timestamps.append(timestamp)
        
        # Store recent error details
        error_metric = ErrorMetric(
            timestamp=timestamp,
            error_type=error_type,
            component=component,
            message=message,
            correlation_id=correlation_id
        )
        self.recent_errors.append({
            "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
            "error_type": error_type,
            "component": component,
            "message": message,
            "correlation_id": correlation_id,
        })
    
    def record_warning(
        self,
        warning_key: str,
        component: Optional[str] = None,
        message: Optional[str] = None
    ) -> None:
        """Record a warning metric.
        
        Args:
            warning_key: Key identifying the warning type
            component: Component where warning occurred
            message: Warning message
        """
        # Use component:key format for unique identification
        key = f"{component}:{warning_key}" if component else warning_key
        self.warning_counts[key] = self.warning_counts.get(key, 0) + 1
    
    def get_error_rate(self) -> float:
        """Calculate error rate per minute over the time window.
        
        Returns:
            Error rate (errors per minute)
        """
        if not self.error_timestamps:
            return 0.0
        
        current_time = time.time()
        window_start = current_time - self.time_window_seconds
        
        # Count errors in the time window
        errors_in_window = sum(
            1 for ts in self.error_timestamps
            if ts >= window_start
        )
        
        # Calculate rate per minute
        window_minutes = self.time_window_seconds / 60.0
        if window_minutes > 0:
            return errors_in_window / window_minutes
        
        return 0.0
    
    def get_summary(self, include_recent: int = 10) -> ErrorSummary:
        """Get error summary statistics.
        
        Args:
            include_recent: Number of recent errors to include in summary
            
        Returns:
            ErrorSummary object with statistics
        """
        recent_errors_list = list(self.recent_errors)[-include_recent:] if include_recent > 0 else []
        
        return ErrorSummary(
            session_id=self.session_id,
            total_errors=sum(self.error_counts_by_type.values()),
            total_warnings=sum(self.warning_counts.values()),
            errors_by_type=self.error_counts_by_type.copy(),
            errors_by_component=self.error_counts_by_component.copy(),
            warnings_by_key=self.warning_counts.copy(),
            recent_errors=recent_errors_list,
            error_rate_per_minute=self.get_error_rate(),
        )
    
    def reset(self) -> None:
        """Reset all metrics (for testing or session reset)."""
        self.error_counts_by_type.clear()
        self.error_counts_by_component.clear()
        self.warning_counts.clear()
        self.recent_errors.clear()
        self.error_timestamps.clear()
        self._start_time = time.time()
        self.session_id = get_session_id() or "unknown"


# Global error metrics instance
_error_metrics_instance: Optional[ErrorMetrics] = None


def get_error_metrics() -> ErrorMetrics:
    """Get global error metrics instance.
    
    Returns:
        Global ErrorMetrics instance
    """
    global _error_metrics_instance
    if _error_metrics_instance is None:
        _error_metrics_instance = ErrorMetrics()
    return _error_metrics_instance


def record_error(
    error_type: str,
    component: Optional[str] = None,
    message: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> None:
    """Record an error in the global metrics tracker.
    
    Args:
        error_type: Type of error
        component: Component where error occurred
        message: Error message
        correlation_id: Correlation ID
    """
    get_error_metrics().record_error(error_type, component, message, correlation_id)


def record_warning(
    warning_key: str,
    component: Optional[str] = None,
    message: Optional[str] = None
) -> None:
    """Record a warning in the global metrics tracker.
    
    Args:
        warning_key: Warning key
        component: Component where warning occurred
        message: Warning message
    """
    get_error_metrics().record_warning(warning_key, component, message)


def get_error_summary(include_recent: int = 10) -> ErrorSummary:
    """Get error summary from global metrics tracker.
    
    Args:
        include_recent: Number of recent errors to include
        
    Returns:
        ErrorSummary object
    """
    return get_error_metrics().get_summary(include_recent=include_recent)

