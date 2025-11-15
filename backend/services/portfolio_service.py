"""
Portfolio service.

Provides portfolio calculations and performance metrics.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from backend.core.database import Position, Trade, TradeStatus, PositionStatus


class PortfolioService:
    """Service for portfolio calculations."""
    
    async def get_portfolio_summary(self, db: Session) -> Optional[Dict[str, Any]]:
        """Get portfolio summary with positions and PnL."""
        
        try:
            # Get all open positions
            open_positions = db.query(Position).filter(
                Position.status == PositionStatus.OPEN
            ).all()
            
            # Calculate totals
            total_value = Decimal("10000.0")  # Starting balance (configurable)
            total_unrealized_pnl = Decimal("0.0")
            positions_value = Decimal("0.0")
            
            positions_list = []
            for pos in open_positions:
                if pos.current_price and pos.quantity:
                    position_value = Decimal(str(pos.current_price)) * Decimal(str(pos.quantity))
                    positions_value += position_value
                    
                    # Calculate unrealized PnL
                    if pos.side.value == "BUY":
                        unrealized = (Decimal(str(pos.current_price)) - Decimal(str(pos.entry_price))) * Decimal(str(pos.quantity))
                    else:
                        unrealized = (Decimal(str(pos.entry_price)) - Decimal(str(pos.current_price))) * Decimal(str(pos.quantity))
                    
                    if pos.unrealized_pnl:
                        total_unrealized_pnl += Decimal(str(pos.unrealized_pnl))
                    else:
                        total_unrealized_pnl += unrealized
                
                positions_list.append({
                    "position_id": pos.position_id,
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "unrealized_pnl": pos.unrealized_pnl or Decimal("0.0"),
                    "status": pos.status.value,
                    "opened_at": pos.opened_at,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit
                })
            
            # Calculate available balance
            available_balance = total_value - positions_value
            
            # Get realized PnL from closed positions
            closed_positions = db.query(Position).filter(
                Position.status == PositionStatus.CLOSED
            ).all()
            
            total_realized_pnl = Decimal("0.0")
            for pos in closed_positions:
                if pos.unrealized_pnl:  # This would be realized PnL when closed
                    total_realized_pnl += Decimal(str(pos.unrealized_pnl))
            
            return {
                "total_value": total_value + total_unrealized_pnl,
                "available_balance": available_balance,
                "open_positions": len(open_positions),
                "total_unrealized_pnl": total_unrealized_pnl,
                "total_realized_pnl": total_realized_pnl,
                "positions": positions_list
            }
            
        except Exception as e:
            print(f"Error getting portfolio summary: {e}")
            return None
    
    async def get_performance_metrics(
        self,
        db: Session,
        days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Get performance metrics for specified period."""
        
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Get trades in period
            trades = db.query(Trade).filter(
                Trade.executed_at >= start_date,
                Trade.status == TradeStatus.EXECUTED
            ).all()
            
            if not trades:
                return {
                    "total_return": 0,
                    "total_return_pct": 0,
                    "win_rate": 0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "average_win": 0,
                    "average_loss": 0,
                    "profit_factor": 0,
                    "sharpe_ratio": 0
                }
            
            # Calculate metrics (simplified - actual implementation would need trade outcomes)
            total_trades = len(trades)
            winning_trades = 0  # Would need to calculate from trade outcomes
            losing_trades = 0
            total_profit = Decimal("0.0")
            total_loss = Decimal("0.0")
            
            # For now, return placeholder metrics
            return {
                "total_return": 0,
                "total_return_pct": 0,
                "win_rate": 0,
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "average_win": 0,
                "average_loss": 0,
                "profit_factor": 0,
                "sharpe_ratio": 0
            }
            
        except Exception as e:
            print(f"Error getting performance metrics: {e}")
            return None


# Global portfolio service instance
portfolio_service = PortfolioService()

