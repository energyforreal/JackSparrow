"""
Shared enumeration definitions for backend-frontend synchronization.

These enums ensure consistent values across the entire system and serve as
a single source of truth for signal types, statuses, and states.
"""

from enum import Enum
from typing import List


class SignalType(str, Enum):
    """Trading signal type enumeration.
    
    Canonical labels use LONG/SHORT. Legacy BUY/SELL aliases are accepted via
    ``normalize()`` and ``is_valid()`` for backward compatibility.
    
    Must match frontend SignalType in frontend/types/enums.ts
    """
    STRONG_LONG = "STRONG_LONG"
    LONG = "LONG"
    HOLD = "HOLD"
    SHORT = "SHORT"
    STRONG_SHORT = "STRONG_SHORT"
    
    @classmethod
    def get_valid_values(cls) -> List[str]:
        """Get list of valid signal values."""
        return [member.value for member in cls]
    
    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check if value is a valid signal (canonical or legacy alias)."""
        from agent.core.signal_vocabulary import normalize_signal
        normalized = normalize_signal(value, default="")
        return normalized in cls.get_valid_values()
    
    @classmethod
    def normalize(cls, value: str, default: str = "HOLD") -> str:
        """Normalize and validate a signal value.
        
        Args:
            value: Signal value to normalize
            default: Default value if invalid
            
        Returns:
            Valid canonical signal value
        """
        from agent.core.signal_vocabulary import normalize_signal
        normalized = normalize_signal(value, default=default)
        if normalized in cls.get_valid_values():
            return normalized
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
    "STRONG_LONG_MIN": 0.8,
    "LONG_MIN": 0.65,
    "SHORT_MAX": 0.35,
    "STRONG_SHORT_MAX": 0.2,
}


def get_signal_from_confidence(confidence: float) -> str:
    """Map confidence value to signal type.
    
    Args:
        confidence: Confidence value (0.0 to 1.0)
        
    Returns:
        Corresponding SignalType value
    """
    if confidence >= SIGNAL_CONFIDENCE_THRESHOLDS["STRONG_LONG_MIN"]:
        return SignalType.STRONG_LONG.value
    elif confidence >= SIGNAL_CONFIDENCE_THRESHOLDS["LONG_MIN"]:
        return SignalType.LONG.value
    elif confidence <= SIGNAL_CONFIDENCE_THRESHOLDS["STRONG_SHORT_MAX"]:
        return SignalType.STRONG_SHORT.value
    elif confidence <= SIGNAL_CONFIDENCE_THRESHOLDS["SHORT_MAX"]:
        return SignalType.SHORT.value
    else:
        return SignalType.HOLD.value