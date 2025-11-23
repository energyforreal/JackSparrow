"""
Time service for system time synchronization.

Provides centralized time management using UTC/system time.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any
import structlog

logger = structlog.get_logger()


class TimeService:
    """Service for managing system time synchronization."""
    
    @staticmethod
    def get_server_time() -> datetime:
        """Get current server time in UTC.
        
        Returns:
            Current UTC datetime
        """
        return datetime.now(timezone.utc)
    
    @staticmethod
    def get_timestamp_ms() -> int:
        """Get current timestamp in milliseconds.
        
        Returns:
            Unix timestamp in milliseconds
        """
        return int(time.time() * 1000)
    
    @staticmethod
    def get_time_info() -> Dict[str, Any]:
        """Get comprehensive time information.
        
        Returns:
            Dictionary containing server time, timestamp, and timezone info
        """
        server_time = TimeService.get_server_time()
        timestamp_ms = TimeService.get_timestamp_ms()
        
        return {
            "server_time": server_time.isoformat(),
            "timestamp_ms": timestamp_ms,
            "timezone": "UTC"
        }
    
    @staticmethod
    def validate_timestamp(timestamp_ms: int, max_drift_ms: int = 5000) -> bool:
        """Validate timestamp is within acceptable drift.
        
        Args:
            timestamp_ms: Timestamp to validate (milliseconds)
            max_drift_ms: Maximum allowed drift in milliseconds (default 5 seconds)
            
        Returns:
            True if timestamp is within acceptable range
        """
        current_ms = TimeService.get_timestamp_ms()
        drift = abs(timestamp_ms - current_ms)
        
        if drift > max_drift_ms:
            logger.warning(
                "timestamp_drift_detected",
                timestamp_ms=timestamp_ms,
                current_ms=current_ms,
                drift_ms=drift,
                max_drift_ms=max_drift_ms
            )
            return False
        
        return True


# Global time service instance
time_service = TimeService()

