"""
Agent state machine.

Manages agent state transitions and state-specific behavior.
"""

from enum import Enum
from typing import Optional, Callable, Dict, Any
from datetime import datetime


class AgentState(Enum):
    """Agent state enumeration."""
    
    INITIALIZING = "INITIALIZING"
    OBSERVING = "OBSERVING"
    THINKING = "THINKING"
    DELIBERATING = "DELIBERATING"
    ANALYZING = "ANALYZING"
    EXECUTING = "EXECUTING"
    MONITORING_POSITION = "MONITORING_POSITION"
    LEARNING = "LEARNING"
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
    
    def __init__(self):
        """Initialize state machine."""
        self.current_state = AgentState.INITIALIZING
        self.previous_state: Optional[AgentState] = None
        self.state_entry_time = datetime.utcnow()
        self.transitions: Dict[AgentState, List[StateTransition]] = {}
        self.state_handlers: Dict[AgentState, Callable] = {}
        
        # Initialize transitions
        self._initialize_transitions()
    
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
        
        # MONITORING_POSITION -> LEARNING
        self.add_transition(
            AgentState.MONITORING_POSITION,
            AgentState.LEARNING,
            lambda ctx: ctx.get("position_closed", False),
            "Position closed"
        )
        
        # LEARNING -> OBSERVING
        self.add_transition(
            AgentState.LEARNING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("learning_complete", False),
            "Learning complete"
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
            AgentState.MONITORING_POSITION,
            AgentState.LEARNING
        ]
        return self.current_state in operational_states
    
    def can_trade(self) -> bool:
        """Check if agent can execute trades."""
        tradeable_states = [
            AgentState.ANALYZING,
            AgentState.EXECUTING
        ]
        return self.current_state in tradeable_states and not self.current_state == AgentState.EMERGENCY_STOP


# Global state machine instance
state_machine = AgentStateMachine()

