"""Legacy position sizing helper.

Prefer `RiskManager.calculate_position_size()` in active runtime paths.
"""

from agent.core.config import settings


class PositionSizer:
    """Legacy standalone Kelly-based position sizing helper."""
    
    def __init__(self):
        """Initialize position sizer."""
        self.max_position_size = settings.max_position_size
    
    def calculate_position_size(
        self,
        signal_strength: float,
        confidence: float,
        win_rate: float = 0.5,
        avg_win: float = 1.0,
        avg_loss: float = 1.0,
        portfolio_value: float = 10000.0,
        available_balance: float = 10000.0
    ) -> float:
        """Calculate position size using Kelly Criterion."""
        
        # Kelly fraction
        if avg_loss > 0:
            kelly_fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_loss
        else:
            kelly_fraction = 0.0
        
        # Apply fractional Kelly (reduce to 1/4 for safety)
        fractional_kelly = kelly_fraction * 0.25
        
        # Adjust based on signal strength and confidence
        adjusted_size = fractional_kelly * abs(signal_strength) * confidence
        
        # Clamp to max position size
        position_size = min(adjusted_size, self.max_position_size)
        
        # Calculate position value
        position_value = portfolio_value * position_size
        
        # Ensure we have enough balance
        if portfolio_value <= 0:
            return 0.0

        if position_value > available_balance:
            position_size = available_balance / portfolio_value
        
        return max(0.0, min(position_size, self.max_position_size))

