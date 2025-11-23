"""
Event system for trading agent.

Provides event-driven architecture for reactive trading decisions.
"""

from agent.events.schemas import (
    BaseEvent,
    MarketTickEvent,
    CandleClosedEvent,
    FeatureRequestEvent,
    FeatureComputedEvent,
    ModelPredictionRequestEvent,
    ModelPredictionEvent,
    ModelPredictionCompleteEvent,
    ReasoningRequestEvent,
    ReasoningCompleteEvent,
    DecisionReadyEvent,
    RiskAlertEvent,
    RiskApprovedEvent,
    EmergencyStopEvent,
    OrderSubmittedEvent,
    OrderFillEvent,
    ExecutionFailedEvent,
    AgentCommandEvent,
    StateTransitionEvent,
    ModelWeightUpdateEvent,
    StrategyAdaptationEvent,
    LearningCompleteEvent,
    PositionClosedEvent,
)
from agent.events.event_bus import EventBus, event_bus
from agent.events.utils import (
    generate_event_id,
    create_correlation_context,
    serialize_event,
    deserialize_event,
)

__all__ = [
    # Event schemas
    "BaseEvent",
    "MarketTickEvent",
    "CandleClosedEvent",
    "FeatureRequestEvent",
    "FeatureComputedEvent",
    "ModelPredictionRequestEvent",
    "ModelPredictionEvent",
    "ModelPredictionCompleteEvent",
    "ReasoningRequestEvent",
    "ReasoningCompleteEvent",
    "DecisionReadyEvent",
    "RiskAlertEvent",
    "RiskApprovedEvent",
    "EmergencyStopEvent",
    "OrderSubmittedEvent",
    "OrderFillEvent",
    "ExecutionFailedEvent",
    "AgentCommandEvent",
    "StateTransitionEvent",
    "ModelWeightUpdateEvent",
    "StrategyAdaptationEvent",
    "LearningCompleteEvent",
    "PositionClosedEvent",
    # Event bus
    "EventBus",
    "event_bus",
    # Utilities
    "generate_event_id",
    "create_correlation_context",
    "serialize_event",
    "deserialize_event",
]

