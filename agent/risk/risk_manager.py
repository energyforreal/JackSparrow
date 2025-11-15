"""Risk management service."""

from typing import Dict, Any, Optional, List
from decimal import Decimal

from agent.core.config import settings


class RiskManager:
    """Risk management service."""
    
    def __init__(self):
        """Initialize risk manager."""
        self.max_position_size = settings.max_position_size
        self.max_portfolio_heat = settings.max_portfolio_heat
        self.stop_loss_pct = settings.stop_loss_percentage
        self.take_profit_pct = settings.take_profit_percentage
    
    def assess_risk(
        self,
        signal_strength: float,
        portfolio_value: float,
        available_balance: float,
        current_positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Assess risk for trade."""
        
        # Calculate portfolio heat
        total_exposure = sum(pos.get("value", 0) for pos in current_positions)
        portfolio_heat = total_exposure / portfolio_value if portfolio_value > 0 else 0.0
        
        # Check limits
        can_trade = (
            portfolio_heat < self.max_portfolio_heat and
            available_balance > 0
        )
        
        return {
            "can_trade": can_trade,
            "portfolio_heat": portfolio_heat,
            "max_portfolio_heat": self.max_portfolio_heat,
            "available_balance": available_balance
        }
    
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Calculate stop loss price."""
        if side == "BUY":
            return entry_price * (1 - self.stop_loss_pct)
        else:
            return entry_price * (1 + self.stop_loss_pct)
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Calculate take profit price."""
        if side == "BUY":
            return entry_price * (1 + self.take_profit_pct)
        else:
            return entry_price * (1 - self.take_profit_pct)

