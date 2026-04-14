"""
Portfolio service.

Provides portfolio calculations and performance metrics.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, select, case, cast, String, delete
from sqlalchemy.types import Numeric
import structlog

from backend.core.database import Position, Trade, TradeStatus, PositionStatus, TradeSide
from backend.core.config import settings
from backend.core.redis import get_cache, set_cache, delete_cache, get_cache_keys
from backend.services.time_service import time_service
from backend.services.fx_rate_service import get_usdinr_rate
from backend.utils.futures_contract import isolated_margin_usd, unrealized_pnl_usd

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
            oa = pos.get("opened_at")
            if isinstance(oa, datetime):
                dt = oa if oa.tzinfo is not None else oa.replace(tzinfo=timezone.utc)
                opened_at_str = dt.isoformat()
            elif oa is not None:
                opened_at_str = str(oa)
            else:
                opened_at_str = None
            serialized_pos = {
                "position_id": str(pos.get("position_id", "")),
                "symbol": str(pos.get("symbol", "")),
                "side": str(pos.get("side", "")),
                "quantity": float(pos.get("quantity", 0)),
                "entry_price": float(pos.get("entry_price", 0)),
                "current_price": float(pos.get("current_price", 0)) if pos.get("current_price") else None,
                "unrealized_pnl": float(pos.get("unrealized_pnl", 0)),
                "entry_price_usd": float(pos.get("entry_price_usd", pos.get("entry_price", 0))),
                "current_price_usd": float(pos.get("current_price_usd", pos.get("current_price", 0)))
                if pos.get("current_price_usd") is not None or pos.get("current_price") is not None
                else None,
                "unrealized_pnl_usd": float(pos.get("unrealized_pnl_usd", pos.get("unrealized_pnl", 0))),
                "unrealized_pnl_inr": float(pos.get("unrealized_pnl_inr", pos.get("unrealized_pnl", 0))),
                "status": str(pos.get("status", "")),
                "opened_at": opened_at_str,
                "stop_loss": float(pos.get("stop_loss", 0)) if pos.get("stop_loss") else None,
                "take_profit": float(pos.get("take_profit", 0)) if pos.get("take_profit") else None,
                "stop_loss_usd": float(pos.get("stop_loss_usd", pos.get("stop_loss", 0))) if pos.get("stop_loss") else None,
                "take_profit_usd": float(pos.get("take_profit_usd", pos.get("take_profit", 0))) if pos.get("take_profit") else None,
            }
            positions_list.append(serialized_pos)
        
        # Get timestamp from time_service for consistency
        time_info = time_service.get_time_info()
        
        # Serialize portfolio summary - convert Decimal to float, ensure consistent field names
        serialized = {
            "total_value": float(summary.get("total_value", 0)),
            "available_balance": float(summary.get("available_balance", 0)),
            "margin_used": float(summary.get("margin_used", 0)),
            "usd_inr_rate": float(summary.get("usd_inr_rate", 0)),
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
                
                # Single contract_value from settings for all open rows: OK for one symbol (e.g.
                # BTCUSD). Multi-asset books should resolve contract_value per symbol (product specs).
                cv = float(getattr(settings, "contract_value_btc", 0.001))
                # Isolated margin uses config leverage, not exchange-reported leverage; optional
                # future: reconcile margin with GET /v2/positions (per-position leverage).
                lev = int(getattr(settings, "isolated_margin_leverage", 5))

                query = select(Position).where(Position.status == PositionStatus.OPEN)
                result = await db.execute(query)
                open_positions = result.scalars().all()
                position_count = len(open_positions)

                total_unrealized_pnl = Decimal("0.0")
                margin_locked_usd = Decimal("0.0")
                for pos in open_positions:
                    ep = float(pos.entry_price)
                    cp = float(pos.current_price) if pos.current_price is not None else ep
                    q = float(pos.quantity)
                    u = unrealized_pnl_usd(ep, cp, q, pos.side, cv)
                    pos.unrealized_pnl = Decimal(str(u))
                    total_unrealized_pnl += Decimal(str(u))
                    margin_locked_usd += Decimal(
                        str(isolated_margin_usd(ep, q, cv, lev))
                    )
                
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
                
                # FX conversion (USD -> INR): one rate per summary for PnL and margin so ROE ratios
                # in the UI are not distorted by mixing rates. Priority: cached live feed, fallback.
                usdinr_rate = Decimal(str(await get_usdinr_rate()))

                # Get realized PnL from closed positions using SQL aggregation
                closed_positions_agg = select(
                    func.sum(
                        case(
                            (Position.realized_pnl.isnot(None), Position.realized_pnl),
                            else_=0
                        )
                    ).label('total_realized_pnl')
                ).where(Position.status == PositionStatus.CLOSED)
                
                result = await db.execute(closed_positions_agg)
                agg_result = result.first()
                total_realized_pnl = Decimal(str(agg_result.total_realized_pnl or 0))
                
                # NOTE: initial_balance is in INR (from config), positions/PnL are in USD
                # Available = initial + realized (USD->INR) - isolated margin locked (USD->INR)
                available_balance_inr = initial_balance + (total_realized_pnl * usdinr_rate) - (
                    margin_locked_usd * usdinr_rate
                )
                
                # Ensure available balance doesn't go negative (shouldn't happen, but safety check)
                if available_balance_inr < 0:
                    logger.warning(
                        "portfolio_available_balance_inr_negative",
                        available_balance_inr=float(available_balance_inr),
                        message="Available balance is negative, setting to 0"
                    )
                    available_balance_inr = Decimal("0.0")
                
                # Calculate total portfolio value: initial_balance_inr + unrealized_pnl_inr + realized_pnl_inr
                total_value_inr = initial_balance + (total_unrealized_pnl * usdinr_rate) + (total_realized_pnl * usdinr_rate)
                
                # Convert positions to INR while keeping market prices in USD
                for pos in positions_list:
                    # Keep original USD values
                    pos["entry_price_usd"] = pos["entry_price"]
                    pos["current_price_usd"] = pos["current_price"]
                    pos["unrealized_pnl_usd"] = pos["unrealized_pnl"]
                    if pos.get("stop_loss"):
                        pos["stop_loss_usd"] = pos["stop_loss"]
                    if pos.get("take_profit"):
                        pos["take_profit_usd"] = pos["take_profit"]
                    
                    # Add INR versions for display
                    pos["unrealized_pnl_inr"] = pos["unrealized_pnl"] * usdinr_rate

                margin_used_inr = margin_locked_usd * usdinr_rate
                total_unrealized_pnl_inr = total_unrealized_pnl * usdinr_rate
                total_realized_pnl_inr = total_realized_pnl * usdinr_rate
                
                summary = {
                    "total_value": total_value_inr,
                    "available_balance": available_balance_inr,
                    "margin_used": margin_used_inr,
                    "open_positions": position_count,
                    "total_unrealized_pnl": total_unrealized_pnl_inr,
                    "total_realized_pnl": total_realized_pnl_inr,
                    "usd_inr_rate": usdinr_rate,
                    "positions": positions_list
                }
                
                # Cache result for 5 seconds (serialize Decimals to floats for JSON compatibility)
                cacheable_summary = self._serialize_for_cache(summary)
                await set_cache(cache_key, cacheable_summary, ttl=5)
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

    async def invalidate_all_portfolio_caches(self) -> None:
        """Clear portfolio summary and all cached performance metric keys."""
        await delete_cache("portfolio:summary")
        perf_keys = await get_cache_keys("portfolio:performance:*")
        for key in perf_keys:
            await delete_cache(key)
        logger.debug(
            "portfolio_all_caches_invalidated",
            performance_keys=len(perf_keys),
        )

    async def delete_all_trades_and_positions(self, db: AsyncSession) -> None:
        """Delete all trade and position rows. Caller session commits (e.g. FastAPI get_db)."""
        await db.execute(delete(Trade))
        await db.execute(delete(Position))
        logger.info("portfolio_delete_all_trades_and_positions")
    
    def _serialize_for_cache(self, obj):
        """Recursively convert Decimal → float for JSON-serializable cache."""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._serialize_for_cache(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_cache(item) for item in obj]
        return obj
    
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
            usdinr_rate = Decimal(str(await get_usdinr_rate()))

            for pos in closed_positions:
                pnl_usd = float(pos.realized_pnl or 0)
                pnl_inr = pnl_usd * float(usdinr_rate)
                total_pnl += Decimal(str(pnl_inr))
                if pnl_inr > 0:
                    winning_count += 1
                elif pnl_inr < 0:
                    losing_count += 1

                closed_trades.append({
                    "position_id": pos.position_id,
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "quantity": float(pos.quantity),
                    "entry_price": float(pos.entry_price),
                    "exit_price": float(pos.current_price or pos.entry_price),
                    "pnl": pnl_inr,
                    "pnl_usd": pnl_usd,
                    "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                })

            return {
                "closed_trades": closed_trades,
                "summary": {
                    "total_pnl": float(total_pnl),
                    "usd_inr_rate": float(usdinr_rate),
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

