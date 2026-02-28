"""
Portfolio service.

Provides portfolio calculations and performance metrics.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, select, case, cast, String
from sqlalchemy.types import Numeric
import structlog

from backend.core.database import Position, Trade, TradeStatus, PositionStatus, TradeSide
from backend.core.config import settings
from backend.core.redis import get_cache, set_cache, delete_cache
from backend.services.time_service import time_service

logger = structlog.get_logger()


class PortfolioService:
    """Service for portfolio calculations."""
    
    def serialize_portfolio_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize portfolio summary for consistent format across API and WebSocket.
        
        Converts Decimal types to float and ensures consistent field names and structure.
        This ensures WebSocket broadcasts and API responses have identical formats.
        
        Args:
            summary: Raw portfolio summary dictionary with Decimal types
            
        Returns:
            Serialized portfolio summary with float types and consistent structure
            
        Raises:
            ValueError: If summary data structure is invalid
        """
        if not summary:
            logger.warning("portfolio_serialization_empty_summary", message="Empty summary provided")
            return {}
        
        # Validate required fields
        required_fields = ["total_value", "available_balance", "open_positions", "total_unrealized_pnl", "total_realized_pnl"]
        missing_fields = [field for field in required_fields if field not in summary]
        if missing_fields:
            logger.error(
                "portfolio_serialization_missing_fields",
                missing_fields=missing_fields,
                available_fields=list(summary.keys()),
                message="Required fields missing from portfolio summary"
            )
            raise ValueError(f"Portfolio summary missing required fields: {missing_fields}")
        
        # Serialize positions list - convert Decimal to float, ensure consistent structure
        positions_list = []
        for pos in summary.get("positions", []):
            serialized_pos = {
                "position_id": str(pos.get("position_id", "")),
                "symbol": str(pos.get("symbol", "")),
                "side": str(pos.get("side", "")),
                "quantity": float(pos.get("quantity", 0)),
                "entry_price": float(pos.get("entry_price", 0)),
                "current_price": float(pos.get("current_price", 0)) if pos.get("current_price") else None,
                "unrealized_pnl": float(pos.get("unrealized_pnl", 0)),
                "status": str(pos.get("status", "")),
                "opened_at": pos.get("opened_at").isoformat() if isinstance(pos.get("opened_at"), datetime) else str(pos.get("opened_at", "")),
                "stop_loss": float(pos.get("stop_loss", 0)) if pos.get("stop_loss") else None,
                "take_profit": float(pos.get("take_profit", 0)) if pos.get("take_profit") else None,
            }
            positions_list.append(serialized_pos)
        
        # Get timestamp from time_service for consistency
        time_info = time_service.get_time_info()
        
        # Serialize portfolio summary - convert Decimal to float, ensure consistent field names
        serialized = {
            "total_value": float(summary.get("total_value", 0)),
            "available_balance": float(summary.get("available_balance", 0)),
            "open_positions": int(summary.get("open_positions", 0)),  # Ensure int type
            "total_unrealized_pnl": float(summary.get("total_unrealized_pnl", 0)),
            "total_realized_pnl": float(summary.get("total_realized_pnl", 0)),
            "positions": positions_list,
            "timestamp": time_info["server_time"]  # Use time_service for consistent format
        }
        
        logger.debug(
            "portfolio_summary_serialized",
            total_value=serialized["total_value"],
            open_positions=serialized["open_positions"],
            positions_count=len(positions_list)
        )
        
        return serialized
    
    async def get_portfolio_summary(self, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Get portfolio summary with positions and PnL.
        
        Uses database transaction to ensure data consistency across multiple queries.
        Cached for 5 seconds to reduce database load.
        """
        
        # Check cache first
        cache_key = "portfolio:summary"
        cached = await get_cache(cache_key)
        if cached:
            logger.debug("portfolio_summary_cache_hit", cache_key=cache_key)
            return cached
        
        # Use transaction to ensure consistent snapshot of data
        try:
            async with db.begin():
                # Get initial balance from config (defaults to 10000.0)
                initial_balance = Decimal(str(getattr(settings, 'initial_balance', 10000.0)))
                
                # Use SQL aggregation for open positions calculations
                # Calculate positions value (cost basis) and unrealized PnL using SQL
                # positions_value should be entry_price * quantity (cost basis), not current_price * quantity
                open_positions_agg = select(
                    func.count(Position.id).label('position_count'),
                    func.sum(
                        case(
                            ((Position.entry_price.isnot(None)) & (Position.quantity.isnot(None)),
                             Position.entry_price * Position.quantity),
                            else_=0
                        )
                    ).label('positions_value'),
                    func.sum(
                        case(
                            (Position.unrealized_pnl.isnot(None), Position.unrealized_pnl),
                            else_=case(
                                (
                                    (Position.current_price.isnot(None))
                                    & (Position.quantity.isnot(None))
                                    & (cast(Position.side, String) == TradeSide.BUY.value),
                                 (Position.current_price - Position.entry_price) * Position.quantity),
                                (
                                    (Position.current_price.isnot(None))
                                    & (Position.quantity.isnot(None))
                                    & (cast(Position.side, String) == TradeSide.SELL.value),
                                 (Position.entry_price - Position.current_price) * Position.quantity),
                                else_=0
                            )
                        )
                    ).label('total_unrealized_pnl')
                ).where(cast(Position.status, String) == PositionStatus.OPEN.value)
                
                result = await db.execute(open_positions_agg)
                agg_result = result.first()
                
                # Extract aggregated values
                position_count = agg_result.position_count or 0
                positions_value = Decimal(str(agg_result.positions_value or 0))
                total_unrealized_pnl = Decimal(str(agg_result.total_unrealized_pnl or 0))
                
                # Get position details for response (still need individual positions)
                query = select(Position).where(Position.status == PositionStatus.OPEN)
                result = await db.execute(query)
                open_positions = result.scalars().all()
                
                positions_list = [
                    {
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
                    }
                    for pos in open_positions
                ]
                
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
                
                # Get realized PnL from closed positions using SQL aggregation
                closed_positions_agg = select(
                    func.sum(
                        case(
                            (Position.unrealized_pnl.isnot(None), Position.unrealized_pnl),
                            else_=0
                        )
                    ).label('total_realized_pnl')
                ).where(Position.status == PositionStatus.CLOSED)
                
                result = await db.execute(closed_positions_agg)
                agg_result = result.first()
                total_realized_pnl = Decimal(str(agg_result.total_realized_pnl or 0))
                
                # Calculate total portfolio value: initial balance + unrealized PnL + realized PnL
                total_value = initial_balance + total_unrealized_pnl + total_realized_pnl
                
                summary = {
                    "total_value": total_value,
                    "available_balance": available_balance,
                    "open_positions": position_count,
                    "total_unrealized_pnl": total_unrealized_pnl,
                    "total_realized_pnl": total_realized_pnl,
                    "positions": positions_list
                }
                
                # Cache result for 5 seconds (store raw summary with Decimal types)
                await set_cache(cache_key, summary, ttl=5)
                logger.debug("portfolio_summary_cache_set", cache_key=cache_key, ttl=5)
                
                return summary
                
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
    
    async def invalidate_portfolio_cache(self):
        """Invalidate portfolio summary cache.
        
        Call this immediately after trade/position creation to ensure fresh data.
        """
        cache_key = "portfolio:summary"
        await delete_cache(cache_key)
        logger.debug("portfolio_summary_cache_invalidated", cache_key=cache_key)
    
    async def get_performance_metrics(
        self,
        db: AsyncSession,
        days: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Get performance metrics for specified period.
        
        Uses database transaction to ensure data consistency.
        Cached for 30 seconds to reduce database load.
        """
        
        # Check cache first
        cache_key = f"portfolio:performance:{days}"
        cached = await get_cache(cache_key)
        if cached:
            logger.debug("portfolio_performance_cache_hit", cache_key=cache_key, days=days)
            return cached
        
        # Use transaction to ensure consistent snapshot of data
        async with db.begin():
            try:
                # Calculate date range
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)
                
                # Use SQL aggregation for performance metrics
                # Note: This assumes Trade model has pnl field or we calculate from positions
                # For now, we'll use SQL aggregation for trade counts and basic metrics
                metrics_query = select(
                    func.count(Trade.id).label('total_trades'),
                    # Note: Actual PnL calculation would require trade outcomes or position data
                    # This is a placeholder structure for when trade PnL tracking is implemented
                ).where(
                    Trade.executed_at >= start_date,
                    Trade.status == TradeStatus.EXECUTED
                )
                
                result = await db.execute(metrics_query)
                metrics = result.first()
                
                total_trades = metrics.total_trades or 0
                
                if total_trades == 0:
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
                
                # TODO: When trade PnL tracking is implemented, use SQL aggregation:
                # winning_trades = func.sum(case((Trade.pnl > 0, 1), else_=0))
                # losing_trades = func.sum(case((Trade.pnl < 0, 1), else_=0))
                # total_profit = func.sum(case((Trade.pnl > 0, Trade.pnl), else_=0))
                # total_loss = func.sum(case((Trade.pnl < 0, abs(Trade.pnl)), else_=0))
                # average_win = func.avg(case((Trade.pnl > 0, Trade.pnl), else_=None))
                # average_loss = func.avg(case((Trade.pnl < 0, Trade.pnl), else_=None))
                
                # Placeholder metrics until trade PnL tracking is implemented
                metrics = {
                    "total_return": 0,
                    "total_return_pct": 0,
                    "win_rate": 0,
                    "total_trades": total_trades,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "average_win": 0,
                    "average_loss": 0,
                    "profit_factor": 0,
                    "sharpe_ratio": 0
                }
                
                # Cache result for 30 seconds
                await set_cache(cache_key, metrics, ttl=30)
                logger.debug("portfolio_performance_cache_set", cache_key=cache_key, ttl=30, days=days)
                
                return metrics
                
            except Exception as e:
                logger.error(
                    "portfolio_service_get_performance_metrics_failed",
                    days=days,
                    error=str(e),
                    exc_info=True
                )
                # Transaction will be rolled back automatically on exception
                return None

    async def get_pnl_summary(
        self,
        db: AsyncSession,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """Get P&L summary for closed paper trades.

        Returns closed positions with realized P&L for audit and profit/loss identification.

        Args:
            db: Database session
            from_date: Start of date range (inclusive)
            to_date: End of date range (inclusive)
            symbol: Optional symbol filter
            limit: Maximum number of closed positions to return

        Returns:
            Dict with closed_trades list and summary (total_pnl, winning_count, losing_count)
        """
        try:
            query = select(Position).where(
                cast(Position.status, String) == PositionStatus.CLOSED.value
            )

            if from_date:
                query = query.where(Position.closed_at >= from_date)
            if to_date:
                query = query.where(Position.closed_at <= to_date)
            if symbol:
                query = query.where(Position.symbol == symbol)

            query = query.order_by(desc(Position.closed_at)).limit(limit)
            result = await db.execute(query)
            closed_positions = result.scalars().all()

            closed_trades = []
            total_pnl = Decimal("0")
            winning_count = 0
            losing_count = 0

            for pos in closed_positions:
                pnl = float(pos.unrealized_pnl or 0)  # Realized PnL stored in unrealized_pnl when closed
                total_pnl += Decimal(str(pnl))
                if pnl > 0:
                    winning_count += 1
                elif pnl < 0:
                    losing_count += 1

                closed_trades.append({
                    "position_id": pos.position_id,
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "quantity": float(pos.quantity),
                    "entry_price": float(pos.entry_price),
                    "exit_price": float(pos.current_price or pos.entry_price),
                    "pnl": pnl,
                    "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                })

            return {
                "closed_trades": closed_trades,
                "summary": {
                    "total_pnl": float(total_pnl),
                    "total_trades": len(closed_trades),
                    "winning_trades": winning_count,
                    "losing_trades": losing_count,
                    "win_rate": winning_count / len(closed_trades) if closed_trades else 0,
                },
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
            }
        except Exception as e:
            logger.error(
                "portfolio_service_get_pnl_summary_failed",
                error=str(e),
                exc_info=True,
            )
            return {
                "closed_trades": [],
                "summary": {
                    "total_pnl": 0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0,
                },
                "from_date": None,
                "to_date": None,
                "error": str(e),
            }


# Global portfolio service instance
portfolio_service = PortfolioService()

