"""
Event schemas for trading agent.

Defines all event types used in the event-driven architecture.
See ``docs/canonical_events.md`` for handler wiring and pipeline overview.
"""

from typing import Dict, Any, Optional, List, Literal
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
import uuid


class PolicyAuthority(str, Enum):
    """Who issued the trade intent carried on DecisionReadyEvent."""

    AGENT_POLICY = "agent_policy"
    ML_EVIDENCE_ONLY = "ml_evidence_only"  # legacy / diagnostics — not used for live emits


class EventType(str, Enum):
    """Event type enumeration."""

    # Market data events
    MARKET_TICK = "market_tick"
    PRICE_FLUCTUATION = "price_fluctuation"
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
    EVIDENCE_READY = "evidence_ready"
    DECISION_READY = "decision_ready"
    
    # Risk events
    RISK_ALERT = "risk_alert"
    RISK_APPROVED = "risk_approved"
    EMERGENCY_STOP = "emergency_stop"
    
    # Execution events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILL = "order_fill"
    PARTIAL_FILL = "partial_fill"
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
    """Real-time market price tick event with rich market data."""

    event_type: EventType = EventType.MARKET_TICK


class PriceFluctuationEvent(BaseEvent):
    """Major price fluctuation event that triggers ML pipeline."""

    event_type: EventType = EventType.PRICE_FLUCTUATION

    class Payload(BaseModel):
        symbol: str
        price: float
        previous_price: float
        change_pct: float
        volume: float
        timestamp: datetime
        threshold_pct: float


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


class MLEvidenceSnapshot(BaseModel):
    """Structured ML output and gates — advisory evidence for the agent policy layer."""

    model_config = ConfigDict(protected_namespaces=())

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    source: Literal["v43_orchestrator", "reasoning_path", "unknown"] = "unknown"
    ml_candidate_signal: str = Field(
        ...,
        description="Discrete label proposed from ML+gates / reasoning before agent policy.",
    )
    ml_candidate_confidence: float = 0.0
    ml_candidate_position_size: float = 0.0
    consensus_signal: Optional[float] = None
    consensus_confidence: Optional[float] = None
    model_predictions: List[Dict[str, Any]] = Field(default_factory=list)
    v43_gate_reject: Optional[str] = None
    v43_regime: Optional[str] = None
    market_context_excerpt: Dict[str, Any] = Field(
        default_factory=dict,
        description="Small excerpt (e.g. v43 flags) for audit — not full OHLCV.",
    )
    thesis_signal: Optional[str] = Field(
        default=None,
        description="Deterministic strategy signal from AgentThesisEngine.",
    )
    trade_score: Optional[float] = Field(
        default=None,
        description="Confluence score 0-100 from trade scorer.",
    )
    ml_confirms: Optional[bool] = Field(
        default=None,
        description="Whether ML validation agreed with structural setup.",
    )
    p_regime_favorable: Optional[float] = Field(
        default=None,
        description="State-head probability that regime is favorable for entry.",
    )
    p_setup_quality: Optional[float] = Field(
        default=None,
        description="State-head probability of TP-first trade quality.",
    )
    p_vol_expansion: Optional[float] = Field(
        default=None,
        description="State-head probability of volatility expansion.",
    )
    uncertainty_score: Optional[float] = Field(
        default=None,
        description="Ensemble disagreement / abstention signal (higher = less confident).",
    )


class PolicyVerdict(BaseModel):
    """Agent policy output: sole authority for trade intent on the event bus."""

    model_config = ConfigDict(protected_namespaces=())

    authority: Literal["agent_policy"] = "agent_policy"
    signal: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    confidence: float
    position_size: float
    reason_codes: List[str] = Field(default_factory=list)
    ml_evidence_id: Optional[str] = None
    adopted_ml_candidate: bool = Field(
        default=False,
        description="True when policy chose to align with the ML candidate after evaluation.",
    )
    memory_size_scale: float = Field(
        default=1.0,
        description="Bounded multiplier from vector-memory historical win rate (0.8–1.0).",
    )


class AgentIntrospectionSnapshot(BaseModel):
    """Deterministic read-only self-awareness block at decision time."""

    version: str = "1.0"
    timestamp: str = ""
    symbol: str = ""
    agent_state: str = "unknown"
    policy_mode: str = ""
    policy_signal: str = ""
    policy_confidence: float = 0.0
    policy_reason_codes: List[str] = Field(default_factory=list)
    ml_candidate_signal: Optional[str] = None
    thesis_signal: Optional[str] = None
    trade_score: Optional[float] = None
    trade_score_pass: Optional[bool] = None
    v43_regime: Optional[str] = None
    v43_gate_reject: Optional[str] = None
    p_regime_favorable: Optional[float] = None
    p_setup_quality: Optional[float] = None
    p_vol_expansion: Optional[float] = None
    uncertainty_score: Optional[float] = None
    regime_bar_age: Optional[int] = None
    regime_transition_risk: Optional[str] = None
    portfolio_guard_action: Optional[str] = None
    portfolio_guard_reason_codes: List[str] = Field(default_factory=list)
    memory_enabled: bool = False
    memory_context_count: int = 0
    limits: Dict[str, Any] = Field(default_factory=dict)


class ReflectionSnapshot(BaseModel):
    """Deterministic advisory post-trade reflection block."""

    version: str = "1.0"
    timestamp: str = ""
    symbol: str = ""
    position_id: str = ""
    advisory_only: bool = True
    predicted_signal: str = ""
    exit_reason: str = ""
    pnl: float = 0.0
    was_profitable: bool = False
    direction_correct: Optional[bool] = None
    confidence_at_entry: Optional[float] = None
    calibration_bucket: str = "unknown"
    quality_score: float = 0.0
    diagnostics: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class EvidenceReadyEvent(BaseEvent):
    """ML evidence computed; downstream policy may emit DecisionReady."""

    event_type: EventType = EventType.EVIDENCE_READY

    class Payload(BaseModel):
        symbol: str
        ml_evidence_snapshot: Dict[str, Any]
        timestamp: datetime
        correlation_id: Optional[str] = None


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
        policy_authority: str = Field(
            default=PolicyAuthority.AGENT_POLICY.value,
            description="Must be agent_policy for autonomous pipeline emits.",
        )
        policy_reason_codes: List[str] = Field(default_factory=list)
        ml_evidence_snapshot: Optional[Dict[str, Any]] = None
        policy_verdict: Optional[Dict[str, Any]] = None
        strategy_origin: bool = Field(
            default=False,
            description="True when entry originated from agent thesis (not ML-only).",
        )
        trade_score: Optional[float] = None
        thesis_signal: Optional[str] = None
        anticipated_horizon_bars: Optional[int] = Field(
            default=None,
            description="Expected movement horizon in 5m bars (2/6/12/24).",
        )
        anticipated_horizon_minutes: Optional[int] = None
        agent_introspection: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Deterministic self-awareness snapshot (read-only telemetry).",
        )
        memory_context_id: Optional[str] = Field(
            default=None,
            description="Vector memory context id for outcome backfill on position close.",
        )
        decision_event_id: Optional[str] = Field(
            default=None,
            description="DecisionReadyEvent.event_id for audit correlation.",
        )


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


class PartialFillEvent(BaseEvent):
    """Order partially filled; remainder may be completed or closed."""

    event_type: EventType = EventType.PARTIAL_FILL

    class Payload(BaseModel):
        order_id: str
        symbol: str
        side: str
        requested_quantity: float
        filled_quantity: float
        fill_price: float
        timestamp: datetime
        exchange_order_id: Optional[int] = None


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
        exit_reason: str  # stop_loss, take_profit, manual, signal_reversal
        timestamp: datetime
        reflection_snapshot: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Advisory deterministic post-trade reflection (no policy mutation).",
        )
        memory_context_id: Optional[str] = Field(
            default=None,
            description="Linked decision memory context id when available.",
        )
        reasoning_chain_id: Optional[str] = None
        predicted_signal: Optional[str] = None
        confidence_at_entry: Optional[float] = None
        agent_introspection_at_entry: Optional[Dict[str, Any]] = None

