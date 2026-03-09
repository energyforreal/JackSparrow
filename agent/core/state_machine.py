"""
Agent state machine.

Manages agent state transitions and state-specific behavior.
Event-driven state transitions.
"""

from enum import Enum
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime, timezone
import structlog

from agent.events.event_bus import event_bus
from agent.events.schemas import (
    CandleClosedEvent,
    ReasoningCompleteEvent,
    RiskApprovedEvent,
    OrderFillEvent,
    RiskAlertEvent,
    EmergencyStopEvent,
    PositionClosedEvent,
    StateTransitionEvent,
    DecisionReadyEvent,
    EventType,
)
from agent.core.learning_system import TradeOutcome

logger = structlog.get_logger()


class AgentState(Enum):
    """Agent state enumeration."""
    
    INITIALIZING = "INITIALIZING"
    OBSERVING = "OBSERVING"
    THINKING = "THINKING"
    DELIBERATING = "DELIBERATING"
    ANALYZING = "ANALYZING"
    EXECUTING = "EXECUTING"
    MONITORING_POSITION = "MONITORING_POSITION"
    DEGRADED = "DEGRADED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class StateTransition:
    """State transition definition."""
    
    def __init__(
        self,
        from_state: AgentState,
        to_state: AgentState,
        condition: Callable[[Dict[str, Any]], bool],
        reason: str = ""
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.reason = reason


class AgentStateMachine:
    """Agent state machine manager."""
    
    def __init__(self, context_manager, learning_system=None, model_registry=None):
        """Initialize state machine."""
        self.current_state = AgentState.INITIALIZING
        self.previous_state: Optional[AgentState] = None
        self.state_entry_time = datetime.utcnow()
        self.transitions: Dict[AgentState, List[StateTransition]] = {}
        self.state_handlers: Dict[AgentState, Callable] = {}
        self.context_manager = context_manager
        self.learning_system = learning_system
        self.model_registry = model_registry

        # Initialize transitions
        self._initialize_transitions()
    
    async def initialize(self):
        """Initialize state machine and register event handlers."""
        event_bus.subscribe(EventType.CANDLE_CLOSED, self._handle_candle_closed)
        event_bus.subscribe(EventType.REASONING_COMPLETE, self._handle_reasoning_complete)
        event_bus.subscribe(EventType.DECISION_READY, self._handle_decision_ready)
        event_bus.subscribe(EventType.RISK_APPROVED, self._handle_risk_approved)
        event_bus.subscribe(EventType.ORDER_FILL, self._handle_order_fill)
        event_bus.subscribe(EventType.RISK_ALERT, self._handle_risk_alert)
        event_bus.subscribe(EventType.EMERGENCY_STOP, self._handle_emergency_stop)
        event_bus.subscribe(EventType.POSITION_CLOSED, self._handle_position_closed)
    
    async def _handle_candle_closed(self, event: CandleClosedEvent):
        """Handle candle closed event - transition OBSERVING -> THINKING."""
        if self.current_state == AgentState.OBSERVING:
            await self._transition_to(AgentState.THINKING, "Candle closed - analyzing market")
    
    async def _handle_reasoning_complete(self, event: ReasoningCompleteEvent):
        """Handle reasoning complete event - transition THINKING -> DELIBERATING."""
        if self.current_state == AgentState.THINKING:
            await self._transition_to(AgentState.DELIBERATING, "Reasoning chain complete")
    
    async def _handle_decision_ready(self, event: DecisionReadyEvent):
        """Handle decision ready event - transition DELIBERATING -> OBSERVING if HOLD, or stay in DELIBERATING for trade signals."""
        if self.current_state == AgentState.DELIBERATING:
            signal = event.payload.get("signal", "")
            # If HOLD decision, transition back to OBSERVING to continue monitoring
            if signal == "HOLD":
                await self._transition_to(AgentState.OBSERVING, "HOLD decision - returning to observation mode")
            # For BUY/SELL signals, stay in DELIBERATING to wait for risk approval
            # The transition to EXECUTING will happen when RISK_APPROVED event is received
    
    async def _handle_risk_approved(self, event: RiskApprovedEvent):
        """Handle risk approved event - transition DELIBERATING/ANALYZING -> EXECUTING."""
        if self.current_state in [AgentState.DELIBERATING, AgentState.ANALYZING]:
            await self._transition_to(AgentState.EXECUTING, "Risk approved - executing trade")
    
    async def _handle_order_fill(self, event: OrderFillEvent):
        """Handle order fill event - transition EXECUTING -> MONITORING_POSITION."""
        if self.current_state == AgentState.EXECUTING:
            await self._transition_to(AgentState.MONITORING_POSITION, "Order filled - monitoring position")
    
    async def _handle_risk_alert(self, event: RiskAlertEvent):
        """Handle risk alert event - transition to DEGRADED."""
        if event.payload.get("severity") == "CRITICAL":
            await self._transition_to(AgentState.DEGRADED, f"Risk alert: {event.payload.get('message')}")
    
    async def _handle_emergency_stop(self, event: EmergencyStopEvent):
        """Handle emergency stop event - transition to EMERGENCY_STOP."""
        await self._transition_to(AgentState.EMERGENCY_STOP, f"Emergency stop: {event.payload.get('reason')}")
    
    async def _handle_position_closed(self, event: PositionClosedEvent):
        """Handle position closed event - transition MONITORING_POSITION -> OBSERVING and record outcome for learning."""
        payload = event.payload
        if self.current_state == AgentState.MONITORING_POSITION:
            exit_reason = payload.get("exit_reason", "unknown")
            await self._transition_to(
                AgentState.OBSERVING,
                f"Position closed - {exit_reason}"
            )
            # Update context to clear position
            await self.context_manager.update_state({
                "position": None,
                "position_opened": False
            })

        # Trade outcome feedback loop: record outcome and update model weights
        model_predictions = payload.get("model_predictions")
        if model_predictions is not None and len(model_predictions) > 0 and self.learning_system and self.model_registry:
            try:
                entry_time = payload.get("entry_time")
                exit_time = payload.get("timestamp")
                now = datetime.now(timezone.utc)
                et = entry_time
                xt = exit_time
                if et is not None and getattr(et, "tzinfo", None) is None and hasattr(et, "replace"):
                    et = et.replace(tzinfo=timezone.utc)
                if xt is not None and getattr(xt, "tzinfo", None) is None and hasattr(xt, "replace"):
                    xt = xt.replace(tzinfo=timezone.utc)
                if et is not None and xt is not None:
                    holding_hours = (xt - et).total_seconds() / 3600.0
                else:
                    holding_hours = 0.0
                trade_outcome = TradeOutcome(
                    trade_id=payload.get("position_id", ""),
                    symbol=payload.get("symbol", ""),
                    entry_price=float(payload.get("entry_price", 0)),
                    exit_price=float(payload.get("exit_price", 0)),
                    entry_time=et or now,
                    exit_time=xt or now,
                    position_size=float(payload.get("quantity", 0)),
                    predicted_signal=payload.get("predicted_signal", ""),
                    actual_pnl=float(payload.get("pnl", 0)),
                    holding_period_hours=holding_hours,
                )
                await self.learning_system.record_trade_outcome(trade_outcome, model_predictions)
                model_names = list(self.model_registry.models.keys()) if self.model_registry.models else []
                n = max(1, len(model_names))
                current_weights = {
                    m: self.model_registry.model_weights.get(m, 1.0 / n)
                    for m in model_names
                }
                if not current_weights and model_names:
                    current_weights = {m: 1.0 / len(model_names) for m in model_names}
                updated_weights = await self.learning_system.get_updated_model_weights(current_weights)
                if updated_weights:
                    self.model_registry.update_weights_from_performance(updated_weights)
            except Exception as e:
                logger.warning(
                    "position_closed_learning_failed",
                    error=str(e),
                    exc_info=True,
                )
    
    async def _transition_to(self, new_state: AgentState, reason: str):
        """Transition to new state and emit event.
        
        Args:
            new_state: New state to transition to
            reason: Reason for transition
        """
        if self.current_state == new_state:
            return
        
        from_state = self.current_state
        self.previous_state = self.current_state
        self.current_state = new_state
        self.state_entry_time = datetime.utcnow()
        
        # Update context
        await self.context_manager.update_state({"state": new_state})
        self.context_manager.add_state_transition(from_state, new_state, reason)
        
        # Emit state transition event
        transition_event = StateTransitionEvent(
            source="state_machine",
            payload={
                "from_state": from_state.value,
                "to_state": new_state.value,
                "reason": reason,
                "timestamp": datetime.utcnow()
            }
        )
        
        await event_bus.publish(transition_event)
        
        logger.info(
            "state_transition",
            from_state=from_state.value,
            to_state=new_state.value,
            reason=reason,
            event_id=transition_event.event_id
        )
    
    def _initialize_transitions(self):
        """Initialize state transitions."""
        
        # INITIALIZING -> OBSERVING
        self.add_transition(
            AgentState.INITIALIZING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("initialized", False),
            "Initialization complete"
        )
        
        # OBSERVING -> THINKING
        self.add_transition(
            AgentState.OBSERVING,
            AgentState.THINKING,
            lambda ctx: ctx.get("significant_change", False),
            "Significant market change detected"
        )
        
        # THINKING -> DELIBERATING
        self.add_transition(
            AgentState.THINKING,
            AgentState.DELIBERATING,
            lambda ctx: ctx.get("reasoning_complete", False),
            "Reasoning chain complete"
        )
        
        # DELIBERATING -> ANALYZING
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.ANALYZING,
            lambda ctx: ctx.get("needs_analysis", False),
            "More analysis needed"
        )
        
        # DELIBERATING -> EXECUTING
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.EXECUTING,
            lambda ctx: ctx.get("trade_decision", False) and ctx.get("can_execute", True),
            "Trade decision made"
        )
        
        # DELIBERATING -> OBSERVING (when HOLD decision is made)
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("decision_signal") == "HOLD",
            "HOLD decision - no trade"
        )
        
        # ANALYZING -> EXECUTING
        self.add_transition(
            AgentState.ANALYZING,
            AgentState.EXECUTING,
            lambda ctx: ctx.get("entry_conditions_met", False),
            "Entry conditions met"
        )
        
        # ANALYZING -> OBSERVING
        self.add_transition(
            AgentState.ANALYZING,
            AgentState.OBSERVING,
            lambda ctx: not ctx.get("entry_conditions_met", False) and ctx.get("analysis_complete", False),
            "No trade opportunity"
        )
        
        # EXECUTING -> MONITORING_POSITION
        self.add_transition(
            AgentState.EXECUTING,
            AgentState.MONITORING_POSITION,
            lambda ctx: ctx.get("position_opened", False),
            "Position opened"
        )
        
        # EXECUTING -> OBSERVING
        self.add_transition(
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("execution_failed", False),
            "Execution failed"
        )
        
        # MONITORING_POSITION -> OBSERVING
        self.add_transition(
            AgentState.MONITORING_POSITION,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("position_closed", False) or ctx.get("position") is None,
            "Position closed"
        )
        
        # DEGRADED -> OBSERVING
        self.add_transition(
            AgentState.DEGRADED,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("services_restored", False),
            "Services restored"
        )
        
        # Any -> EMERGENCY_STOP
        for state in AgentState:
            if state != AgentState.EMERGENCY_STOP:
                self.add_transition(
                    state,
                    AgentState.EMERGENCY_STOP,
                    lambda ctx: ctx.get("emergency", False),
                    "Emergency stop triggered"
                )
        
        # EMERGENCY_STOP -> INITIALIZING (manual reset)
        self.add_transition(
            AgentState.EMERGENCY_STOP,
            AgentState.INITIALIZING,
            lambda ctx: ctx.get("manual_reset", False),
            "Manual reset"
        )
    
    def add_transition(
        self,
        from_state: AgentState,
        to_state: AgentState,
        condition: Callable[[Dict[str, Any]], bool],
        reason: str = ""
    ):
        """Add state transition."""
        if from_state not in self.transitions:
            self.transitions[from_state] = []
        
        transition = StateTransition(from_state, to_state, condition, reason)
        self.transitions[from_state].append(transition)
    
    def can_transition(self, context: Dict[str, Any]) -> Optional[AgentState]:
        """Check if state transition is possible."""
        
        if self.current_state not in self.transitions:
            return None
        
        for transition in self.transitions[self.current_state]:
            if transition.condition(context):
                return transition.to_state
        
        return None
    
    def transition_to(self, new_state: AgentState, context: Dict[str, Any]) -> bool:
        """Transition to new state."""
        
        # Check if transition is valid
        possible_state = self.can_transition(context)
        if possible_state == new_state:
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.utcnow()
            return True
        
        # Allow direct transition to EMERGENCY_STOP from any state
        if new_state == AgentState.EMERGENCY_STOP:
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.utcnow()
            return True
        
        # Allow manual transitions in development (can be restricted)
        if context.get("manual_transition", False):
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.utcnow()
            return True
        
        return False
    
    def get_state_info(self) -> Dict[str, Any]:
        """Get current state information."""
        return {
            "current_state": self.current_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "state_entry_time": self.state_entry_time.isoformat(),
            "time_in_state_seconds": (datetime.utcnow() - self.state_entry_time).total_seconds()
        }
    
    def is_operational(self) -> bool:
        """Check if agent is in operational state."""
        operational_states = [
            AgentState.OBSERVING,
            AgentState.THINKING,
            AgentState.DELIBERATING,
            AgentState.ANALYZING,
            AgentState.EXECUTING,
            AgentState.MONITORING_POSITION
        ]
        return self.current_state in operational_states
    
    def can_trade(self) -> bool:
        """Check if agent can execute trades."""
        tradeable_states = [
            AgentState.ANALYZING,
            AgentState.EXECUTING
        ]
        return self.current_state in tradeable_states and not self.current_state == AgentState.EMERGENCY_STOP