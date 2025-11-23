"""
Event schemas for trading agent.

Defines all event types used in the event-driven architecture.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
import uuid


class EventType(str, Enum):
    """Event type enumeration."""
    
    # Market data events
    MARKET_TICK = "market_tick"
    CANDLE_CLOSED = "candle_closed"
    
    # Feature events
    FEATURE_REQUEST = "feature_request"
    FEATURE_COMPUTED = "feature_computed"
    
    # Model events
    MODEL_PREDICTION_REQUEST = "model_prediction_request"
    MODEL_PREDICTION = "model_prediction"
    MODEL_PREDICTION_COMPLETE = "model_prediction_complete"
    
    # Reasoning events
    REASONING_REQUEST = "reasoning_request"
    REASONING_COMPLETE = "reasoning_complete"
    DECISION_READY = "decision_ready"
    
    # Risk events
    RISK_ALERT = "risk_alert"
    RISK_APPROVED = "risk_approved"
    EMERGENCY_STOP = "emergency_stop"
    
    # Execution events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILL = "order_fill"
    EXECUTION_FAILED = "execution_failed"
    
    # Control events
    AGENT_COMMAND = "agent_command"
    STATE_TRANSITION = "state_transition"
    
    # Learning events
    MODEL_WEIGHT_UPDATE = "model_weight_update"
    STRATEGY_ADAPTATION = "strategy_adaptation"
    LEARNING_COMPLETE = "learning_complete"
    POSITION_CLOSED = "position_closed"


class BaseEvent(BaseModel):
    """Base event class."""
    
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(..., description="Component that emitted the event")
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, description="Correlation ID for event chains")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Market Data Events

class MarketTickEvent(BaseEvent):
    """Real-time market price tick event."""
    
    event_type: EventType = EventType.MARKET_TICK
    
    class Payload(BaseModel):
        symbol: str
        price: float
        volume: float
        timestamp: datetime


class CandleClosedEvent(BaseEvent):
    """OHLCV candle completion event."""
    
    event_type: EventType = EventType.CANDLE_CLOSED
    
    class Payload(BaseModel):
        symbol: str
        interval: str
        open: float
        high: float
        low: float
        close: float
        volume: float
        timestamp: datetime


# Feature Events

class FeatureRequestEvent(BaseEvent):
    """Request for feature computation."""
    
    event_type: EventType = EventType.FEATURE_REQUEST
    
    class Payload(BaseModel):
        symbol: str
        feature_names: List[str]
        timestamp: Optional[datetime] = None
        version: str = "latest"


class FeatureComputedEvent(BaseEvent):
    """Features computed and ready."""
    
    event_type: EventType = EventType.FEATURE_COMPUTED
    
    class Payload(BaseModel):
        symbol: str
        features: Dict[str, float]
        quality_score: float
        timestamp: datetime


# Model Events

class ModelPredictionRequestEvent(BaseEvent):
    """Request for model predictions."""
    
    event_type: EventType = EventType.MODEL_PREDICTION_REQUEST
    
    class Payload(BaseModel):
        symbol: str
        features: Dict[str, float]
        context: Dict[str, Any]
        require_explanation: bool = True


class ModelPredictionEvent(BaseEvent):
    """Single model prediction."""
    
    event_type: EventType = EventType.MODEL_PREDICTION
    
    class Payload(BaseModel):
        model_config = ConfigDict(protected_namespaces=())
        model_name: str
        model_version: str
        prediction: float  # -1.0 to +1.0
        confidence: float  # 0.0 to 1.0
        reasoning: str
        features_used: List[str]
        feature_importance: Dict[str, float]
        computation_time_ms: float
        health_status: str


class ModelPredictionCompleteEvent(BaseEvent):
    """All model predictions complete."""
    
    event_type: EventType = EventType.MODEL_PREDICTION_COMPLETE
    
    class Payload(BaseModel):
        symbol: str
        predictions: List[Dict[str, Any]]
        consensus_signal: float
        consensus_confidence: float
        timestamp: datetime


# Reasoning Events

class ReasoningRequestEvent(BaseEvent):
    """Request for reasoning chain generation."""
    
    event_type: EventType = EventType.REASONING_REQUEST
    
    class Payload(BaseModel):
        symbol: str
        market_context: Dict[str, Any]
        use_memory: bool = True


class ReasoningCompleteEvent(BaseEvent):
    """Reasoning chain generated."""
    
    event_type: EventType = EventType.REASONING_COMPLETE
    
    class Payload(BaseModel):
        symbol: str
        reasoning_chain: Dict[str, Any]
        final_confidence: float
        timestamp: datetime


class DecisionReadyEvent(BaseEvent):
    """Trading decision ready for execution."""
    
    event_type: EventType = EventType.DECISION_READY
    
    class Payload(BaseModel):
        symbol: str
        signal: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
        confidence: float
        position_size: float
        reasoning_chain: Dict[str, Any]
        timestamp: datetime


# Risk Events

class RiskAlertEvent(BaseEvent):
    """Risk violation detected."""
    
    event_type: EventType = EventType.RISK_ALERT
    
    class Payload(BaseModel):
        alert_type: str  # POSITION_SIZE, PORTFOLIO_HEAT, STOP_LOSS, etc.
        severity: str  # WARNING, CRITICAL
        message: str
        current_value: float
        threshold: float
        symbol: Optional[str] = None


class RiskApprovedEvent(BaseEvent):
    """Trade approved by risk manager."""
    
    event_type: EventType = EventType.RISK_APPROVED
    
    class Payload(BaseModel):
        symbol: str
        side: str  # BUY, SELL
        quantity: float
        price: float
        risk_score: float
        timestamp: datetime


class EmergencyStopEvent(BaseEvent):
    """Emergency stop triggered."""
    
    event_type: EventType = EventType.EMERGENCY_STOP
    
    class Payload(BaseModel):
        reason: str
        triggered_by: str
        timestamp: datetime


# Execution Events

class OrderSubmittedEvent(BaseEvent):
    """Order submitted to exchange."""
    
    event_type: EventType = EventType.ORDER_SUBMITTED
    
    class Payload(BaseModel):
        order_id: str
        symbol: str
        side: str
        quantity: float
        price: float
        timestamp: datetime


class OrderFillEvent(BaseEvent):
    """Order filled/executed."""
    
    event_type: EventType = EventType.ORDER_FILL
    
    class Payload(BaseModel):
        order_id: str
        trade_id: str
        symbol: str
        side: str
        quantity: float
        fill_price: float
        timestamp: datetime


class ExecutionFailedEvent(BaseEvent):
    """Trade execution failed."""
    
    event_type: EventType = EventType.EXECUTION_FAILED
    
    class Payload(BaseModel):
        order_id: Optional[str]
        symbol: str
        reason: str
        error: str
        timestamp: datetime


# Control Events

class AgentCommandEvent(BaseEvent):
    """Control command from backend."""
    
    event_type: EventType = EventType.AGENT_COMMAND
    
    class Payload(BaseModel):
        command: str  # predict, execute_trade, get_status, control
        parameters: Dict[str, Any]
        request_id: str


class StateTransitionEvent(BaseEvent):
    """State machine transition."""
    
    event_type: EventType = EventType.STATE_TRANSITION
    
    class Payload(BaseModel):
        from_state: str
        to_state: str
        reason: str
        timestamp: datetime


# Learning Events

class ModelWeightUpdateEvent(BaseEvent):
    """Model weight updated."""
    
    event_type: EventType = EventType.MODEL_WEIGHT_UPDATE
    
    class Payload(BaseModel):
        model_config = ConfigDict(protected_namespaces=())
        model_name: str
        old_weight: float
        new_weight: float
        reason: str
        timestamp: datetime


class StrategyAdaptationEvent(BaseEvent):
    """Strategy parameters adapted."""
    
    event_type: EventType = EventType.STRATEGY_ADAPTATION
    
    class Payload(BaseModel):
        parameter_name: str
        old_value: Any
        new_value: Any
        reason: str
        timestamp: datetime


class LearningCompleteEvent(BaseEvent):
    """Learning cycle complete."""
    
    event_type: EventType = EventType.LEARNING_COMPLETE
    
    class Payload(BaseModel):
        model_config = ConfigDict(protected_namespaces=())
        trade_id: str
        performance_metrics: Dict[str, float]
        model_updates: List[Dict[str, Any]]
        timestamp: datetime


class PositionClosedEvent(BaseEvent):
    """Position closed."""
    
    event_type: EventType = EventType.POSITION_CLOSED
    
    class Payload(BaseModel):
        position_id: str
        symbol: str
        entry_price: float
        exit_price: float
        pnl: float
        duration_seconds: float
        timestamp: datetime

