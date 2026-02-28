"""
Shared enumeration definitions for backend-frontend synchronization.

These enums ensure consistent values across the entire system and serve as
a single source of truth for signal types, statuses, and states.
"""

from enum import Enum
from typing import List


class SignalType(str, Enum):
    """Trading signal type enumeration.
    
    Must match frontend SignalType in frontend/types/enums.ts
    """
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    
    @classmethod
    def get_valid_values(cls) -> List[str]:
        """Get list of valid signal values."""
        return [member.value for member in cls]
    
    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check if value is a valid signal."""
        return value in cls.get_valid_values()
    
    @classmethod
    def normalize(cls, value: str, default: str = "HOLD") -> str:
        """Normalize and validate a signal value.
        
        Args:
            value: Signal value to normalize
            default: Default value if invalid
            
        Returns:
            Valid signal value
        """
        if cls.is_valid(value):
            return value
        return default


class PositionStatus(str, Enum):
    """Position status enumeration.
    
    Must match backend PositionStatus in backend/core/database.py
    """
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


class TradeStatus(str, Enum):
    """Trade status enumeration.
    
    Must match backend TradeStatus in backend/core/database.py
    """
    EXECUTED = "EXECUTED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class TradeSide(str, Enum):
    """Trade side enumeration (BUY or SELL).
    
    Must match backend TradeSide in backend/core/database.py
    """
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    """Position side enumeration (LONG or SHORT)."""
    LONG = "LONG"
    SHORT = "SHORT"


class AgentState(str, Enum):
    """Agent state enumeration."""
    UNKNOWN = "UNKNOWN"
    INITIALIZING = "INITIALIZING"
    MONITORING = "MONITORING"
    OBSERVING = "OBSERVING"
    DECISION_MAKING = "DECISION_MAKING"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class HealthStatus(str, Enum):
    """System health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceStatus(str, Enum):
    """Individual service status."""
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


# Simplified WebSocket message types
class WebSocketMessageType(str, Enum):
    """Consolidated WebSocket message types."""
    DATA_UPDATE = "data_update"  # Replaces signal_update, portfolio_update, trade_executed, etc.
    AGENT_UPDATE = "agent_update"  # Replaces agent_state
    SYSTEM_UPDATE = "system_update"  # Replaces health_update, time_sync
    RESPONSE = "response"  # For request-response pattern
    ERROR = "error"  # Error messages


class WebSocketResource(str, Enum):
    """WebSocket resource types for data_update messages."""
    SIGNAL = "signal"  # Trading signals and reasoning
    PORTFOLIO = "portfolio"  # Portfolio and positions
    TRADE = "trade"  # Trade executions
    MARKET = "market"  # Market data and ticks
    PERFORMANCE = "performance"  # Performance metrics
    HEALTH = "health"  # System health
    TIME = "time"  # Time synchronization
    AGENT = "agent"  # Agent state
    MODEL = "model"  # Model predictions


# Confidence thresholds for signal mapping
SIGNAL_CONFIDENCE_THRESHOLDS = {
    "STRONG_BUY_MIN": 0.8,
    "BUY_MIN": 0.65,
    "SELL_MAX": 0.35,
    "STRONG_SELL_MAX": 0.2,
}


def get_signal_from_confidence(confidence: float) -> str:
    """Map confidence value to signal type.
    
    Args:
        confidence: Confidence value (0.0 to 1.0)
        
    Returns:
        Corresponding SignalType value
    """
    if confidence >= SIGNAL_CONFIDENCE_THRESHOLDS["STRONG_BUY_MIN"]:
        return SignalType.STRONG_BUY.value
    elif confidence >= SIGNAL_CONFIDENCE_THRESHOLDS["BUY_MIN"]:
        return SignalType.BUY.value
    elif confidence <= SIGNAL_CONFIDENCE_THRESHOLDS["STRONG_SELL_MAX"]:
        return SignalType.STRONG_SELL.value
    elif confidence <= SIGNAL_CONFIDENCE_THRESHOLDS["SELL_MAX"]:
        return SignalType.SELL.value
    else:
        return SignalType.HOLD.value