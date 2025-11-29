"""
Portfolio service.

Provides portfolio calculations and performance metrics.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, select
import structlog

from backend.core.database import Position, Trade, TradeStatus, PositionStatus
from backend.core.config import settings

logger = structlog.get_logger()


class PortfolioService:
    """Service for portfolio calculations."""
    
    async def get_portfolio_summary(self, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Get portfolio summary with positions and PnL.
        
        Uses database transaction to ensure data consistency across multiple queries.
        """
        
        # Use transaction to ensure consistent snapshot of data
        try:
            async with db.begin():
                # Get all open positions
                query = select(Position).where(Position.status == PositionStatus.OPEN)
                result = await db.execute(query)
                open_positions = result.scalars().all()
                
                # Get initial balance from config (defaults to 10000.0)
                initial_balance = Decimal(str(getattr(settings, 'initial_balance', 10000.0)))
                
                # Calculate totals - start with initial balance
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
                
                # Calculate available balance (initial balance minus positions value)
                available_balance = initial_balance - positions_value
                
                # Ensure available balance doesn't go negative (shouldn't happen, but safety check)
                if available_balance < 0:
                    logger.warning(
                        "portfolio_available_balance_negative",
                        available_balance=float(available_balance),
                        positions_value=float(positions_value),
                        initial_balance=float(initial_balance),
                        message="Available balance is negative, setting to 0"
                    )
                    available_balance = Decimal("0.0")
                
                # Get realized PnL from closed positions
                query = select(Position).where(Position.status == PositionStatus.CLOSED)
                result = await db.execute(query)
                closed_positions = result.scalars().all()
                
                total_realized_pnl = Decimal("0.0")
                for pos in closed_positions:
                    if pos.unrealized_pnl:  # This would be realized PnL when closed
                        total_realized_pnl += Decimal(str(pos.unrealized_pnl))
                
                # Calculate total portfolio value: initial balance + unrealized PnL + realized PnL
                total_value = initial_balance + total_unrealized_pnl + total_realized_pnl
                
                return {
                    "total_value": total_value,
                    "available_balance": available_balance,
                    "open_positions": len(open_positions),
                    "total_unrealized_pnl": total_unrealized_pnl,
                    "total_realized_pnl": total_realized_pnl,
                    "positions": positions_list
                }
                
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            # Check if it's a table doesn't exist error
            if "does not exist" in error_msg.lower() or "relation" in error_msg.lower():
                logger.error(
                    "portfolio_service_get_summary_failed_table_missing",
                    error=error_msg,
                    error_type=error_type,
                    message="Database tables may not be initialized. Run database setup script.",
                    exc_info=True
                )
            else:
                logger.error(
                    "portfolio_service_get_summary_failed",
                    error=error_msg,
                    error_type=error_type,
                    exc_info=True
                )
            # Transaction will be rolled back automatically on exception
            return None
    
    async def get_performance_metrics(
        self,
        db: AsyncSession,
        days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Get performance metrics for specified period.
        
        Uses database transaction to ensure data consistency.
        """
        
        # Use transaction to ensure consistent snapshot of data
        async with db.begin():
            try:
                # Calculate date range
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)
                
                # Get trades in period
                query = select(Trade).where(
                    Trade.executed_at >= start_date,
                    Trade.status == TradeStatus.EXECUTED
                )
                result = await db.execute(query)
                trades = result.scalars().all()
                
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
                logger.error(
                    "portfolio_service_get_performance_metrics_failed",
                    days=days,
                    error=str(e),
                    exc_info=True
                )
                # Transaction will be rolled back automatically on exception
                return None


# Global portfolio service instance
portfolio_service = PortfolioService()

