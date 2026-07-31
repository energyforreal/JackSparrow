"""Trade outcome record used by state machine and execution."""

from __future__ import annotations

from datetime import datetime


class TradeOutcome:
    """Represents the outcome of a completed trade."""

    def __init__(
        self,
        trade_id: str,
        symbol: str,
        entry_price: float,
        exit_price: float,
        entry_time: datetime,
        exit_time: datetime,
        position_size: float,
        predicted_signal: str,
        actual_pnl: float,
        holding_period_hours: float,
    ) -> None:
        self.trade_id = trade_id
        self.symbol = symbol
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.position_size = position_size
        self.predicted_signal = predicted_signal
        self.actual_pnl = actual_pnl
        self.holding_period_hours = holding_period_hours
        denom = entry_price * position_size
        self.pnl_percentage = (actual_pnl / denom) * 100 if denom else 0.0

    def was_profitable(self) -> bool:
        return self.actual_pnl > 0
