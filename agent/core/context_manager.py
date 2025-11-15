"""
Context manager for agent state and decision context.

Manages agent context, state transitions, and decision history.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import deque
import json

from agent.core.state_machine import AgentState


class AgentContext:
    """Agent context for decision-making."""
    
    def __init__(self):
        """Initialize agent context."""
        self.current_state: AgentState = AgentState.INITIALIZING
        self.symbol: str = "BTCUSD"
        self.current_price: Optional[float] = None
        self.market_data: Dict[str, Any] = {}
        self.features: Dict[str, float] = {}
        self.model_predictions: List[Dict[str, Any]] = []
        self.reasoning_chain_id: Optional[str] = None
        self.last_decision: Optional[Dict[str, Any]] = None
        self.last_trade: Optional[Dict[str, Any]] = None
        self.position: Optional[Dict[str, Any]] = None
        self.portfolio_value: float = 10000.0  # Starting balance
        self.available_balance: float = 10000.0
        self.timestamp: datetime = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "current_state": self.current_state.value if isinstance(self.current_state, AgentState) else str(self.current_state),
            "symbol": self.symbol,
            "current_price": self.current_price,
            "market_data": self.market_data,
            "features": self.features,
            "model_predictions": self.model_predictions,
            "reasoning_chain_id": self.reasoning_chain_id,
            "last_decision": self.last_decision,
            "last_trade": self.last_trade,
            "position": self.position,
            "portfolio_value": self.portfolio_value,
            "available_balance": self.available_balance,
            "timestamp": self.timestamp.isoformat()
        }
    
    def update_state(self, new_state: AgentState):
        """Update agent state."""
        self.current_state = new_state
        self.timestamp = datetime.utcnow()
    
    def update_market_data(self, market_data: Dict[str, Any]):
        """Update market data."""
        self.market_data = market_data
        if "price" in market_data:
            self.current_price = market_data["price"]
        self.timestamp = datetime.utcnow()
    
    def update_features(self, features: Dict[str, float]):
        """Update features."""
        self.features = features
        self.timestamp = datetime.utcnow()
    
    def update_predictions(self, predictions: List[Dict[str, Any]]):
        """Update model predictions."""
        self.model_predictions = predictions
        self.timestamp = datetime.utcnow()
    
    def update_decision(self, decision: Dict[str, Any]):
        """Update last decision."""
        self.last_decision = decision
        self.reasoning_chain_id = decision.get("reasoning_chain_id")
        self.timestamp = datetime.utcnow()
    
    def update_trade(self, trade: Dict[str, Any]):
        """Update last trade."""
        self.last_trade = trade
        self.timestamp = datetime.utcnow()
    
    def update_position(self, position: Dict[str, Any]):
        """Update current position."""
        self.position = position
        self.timestamp = datetime.utcnow()
    
    def update_portfolio(self, portfolio_value: float, available_balance: float):
        """Update portfolio values."""
        self.portfolio_value = portfolio_value
        self.available_balance = available_balance
        self.timestamp = datetime.utcnow()


class ContextManager:
    """Context manager for agent state and history."""
    
    def __init__(self, max_history: int = 1000):
        """Initialize context manager."""
        self.current_context = AgentContext()
        self.decision_history: deque = deque(maxlen=max_history)
        self.trade_history: deque = deque(maxlen=max_history)
        self.state_history: deque = deque(maxlen=100)
        
    def get_current_context(self) -> AgentContext:
        """Get current agent context."""
        return self.current_context
    
    def update_context(self, updates: Dict[str, Any]):
        """Update current context."""
        if "state" in updates:
            state = updates["state"]
            if isinstance(state, str):
                try:
                    state = AgentState(state)
                except ValueError:
                    pass
            self.current_context.update_state(state)
        
        if "market_data" in updates:
            self.current_context.update_market_data(updates["market_data"])
        
        if "features" in updates:
            self.current_context.update_features(updates["features"])
        
        if "predictions" in updates:
            self.current_context.update_predictions(updates["predictions"])
        
        if "decision" in updates:
            self.current_context.update_decision(updates["decision"])
            self.decision_history.append(updates["decision"])
        
        if "trade" in updates:
            self.current_context.update_trade(updates["trade"])
            self.trade_history.append(updates["trade"])
        
        if "position" in updates:
            self.current_context.update_position(updates["position"])
        
        if "portfolio" in updates:
            portfolio = updates["portfolio"]
            self.current_context.update_portfolio(
                portfolio.get("value", self.current_context.portfolio_value),
                portfolio.get("balance", self.current_context.available_balance)
            )
    
    def add_state_transition(self, from_state: AgentState, to_state: AgentState, reason: str = ""):
        """Record state transition."""
        transition = {
            "from_state": from_state.value if isinstance(from_state, AgentState) else str(from_state),
            "to_state": to_state.value if isinstance(to_state, AgentState) else str(to_state),
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.state_history.append(transition)
    
    def get_recent_decisions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent decisions."""
        return list(self.decision_history)[-limit:]
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent trades."""
        return list(self.trade_history)[-limit:]
    
    def get_recent_state_transitions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent state transitions."""
        return list(self.state_history)[-limit:]
    
    def get_context_summary(self) -> Dict[str, Any]:
        """Get context summary for reporting."""
        return {
            "current_state": self.current_context.current_state.value if isinstance(self.current_context.current_state, AgentState) else str(self.current_context.current_state),
            "symbol": self.current_context.symbol,
            "current_price": self.current_context.current_price,
            "portfolio_value": self.current_context.portfolio_value,
            "available_balance": self.current_context.available_balance,
            "has_position": self.current_context.position is not None,
            "decisions_count": len(self.decision_history),
            "trades_count": len(self.trade_history),
            "last_update": self.current_context.timestamp.isoformat()
        }


# Global context manager instance
context_manager = ContextManager()

