"""
Portfolio management endpoints.

Provides portfolio status, positions, and performance metrics.
"""

import re
from fastapi import APIRouter, Depends, HTTPException, status, Query
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, select, text
from typing import Optional, List
import structlog

from backend.core.database import get_db, Position, Trade, PositionStatus, TradeStatus
from backend.core.config import settings
from backend.api.models.requests import PortfolioRequest
from backend.api.models.responses import PortfolioSummaryResponse, PositionResponse, TradeResponse, ErrorResponse
from backend.services.portfolio_service import portfolio_service
from backend.api.middleware.auth import require_auth

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_auth)])


def validate_symbol(symbol: Optional[str]) -> Optional[str]:
    """Validate and sanitize symbol parameter.
    
    Args:
        symbol: Symbol string to validate
        
    Returns:
        Validated symbol or None
        
    Raises:
        HTTPException: If symbol is invalid
    """
    if symbol is None:
        return None
    
    # Remove whitespace
    symbol = symbol.strip()
    
    # Validate length (max 50 chars per database schema)
    if len(symbol) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Symbol must be 50 characters or less"
        )
    
    # Validate format: alphanumeric and common trading symbols (BTCUSD, ETH-USD, etc.)
    if not re.match(r'^[A-Z0-9\-_]+$', symbol.upper()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Symbol contains invalid characters. Use uppercase letters, numbers, hyphens, or underscores"
        )
    
    return symbol.upper()


def validate_status(status: Optional[str], valid_statuses: List[str]) -> Optional[str]:
    """Validate and sanitize status parameter.
    
    Args:
        status: Status string to validate
        valid_statuses: List of valid status values
        
    Returns:
        Validated status or None
        
    Raises:
        HTTPException: If status is invalid
    """
    if status is None:
        return None
    
    # Remove whitespace and convert to uppercase
    status = status.strip().upper()
    
    # Validate against allowed values
    if status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Status must be one of: {', '.join(valid_statuses)}"
        )
    
    return status


@router.get("/portfolio/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary(
    db: AsyncSession = Depends(get_db)
):
    """
    Get portfolio summary.
    
    Returns comprehensive portfolio information including:
    - Total portfolio value
    - Available balance
    - Total unrealized and realized PnL
    - Position count and details
    
    **Example Response:**
    ```json
    {
      "total_value": 10000.50,
      "available_balance": 5000.00,
      "total_unrealized_pnl": 150.25,
      "total_realized_pnl": 200.00,
      "position_count": 2
    }
    ```
    """
    
    try:
        summary = await portfolio_service.get_portfolio_summary(db)
        
        if not summary:
            # Get initial balance from config for fallback
            initial_balance = float(getattr(settings, 'initial_balance', 10000.0))
            
            # Check if this is a database initialization issue
            # Try a simple query to see if tables exist
            try:
                await db.execute(text("SELECT 1 FROM positions LIMIT 1"))
                # Table exists, just no data - return portfolio with initial balance
                logger.info(
                    "portfolio_summary_no_data",
                    message="No positions found, returning portfolio with initial balance",
                    initial_balance=initial_balance
                )
                return PortfolioSummaryResponse(
                    total_value=initial_balance,
                    available_balance=initial_balance,
                    open_positions=0,
                    total_unrealized_pnl=0,
                    total_realized_pnl=0,
                    positions=[]
                )
            except Exception as table_error:
                # Table doesn't exist - this is a configuration issue
                error_msg = str(table_error)
                if "does not exist" in error_msg.lower() or "relation" in error_msg.lower():
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Database tables not initialized. Please run the database setup script (scripts/setup_db.py) to create required tables."
                    )
                # Other database error - return portfolio with initial balance but log it
                logger.warning(
                    "portfolio_summary_table_check_failed",
                    error=error_msg,
                    initial_balance=initial_balance,
                    message="Returning portfolio with initial balance due to database error"
                )
                return PortfolioSummaryResponse(
                    total_value=initial_balance,
                    available_balance=initial_balance,
                    open_positions=0,
                    total_unrealized_pnl=0,
                    total_realized_pnl=0,
                    positions=[]
                )
        
        return PortfolioSummaryResponse(**summary)
        
    except HTTPException:
        # Re-raise HTTP exceptions (like the 503 above)
        raise
    except Exception as e:
        logger.error(
            "portfolio_summary_endpoint_error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get portfolio summary: {str(e)}"
        )


@router.get("/portfolio/positions", response_model=List[PositionResponse])
async def get_positions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    status: Optional[str] = Query(None, description="Filter by status (OPEN/CLOSED/LIQUIDATED)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get positions list.
    
    Returns list of positions with optional filtering.
    """
    
    try:
        # Validate and sanitize input parameters
        validated_symbol = validate_symbol(symbol)
        validated_status = validate_status(
            status,
            [s.value for s in PositionStatus]
        )
        
        # Build query
        query = select(Position)
        
        if validated_symbol:
            query = query.where(Position.symbol == validated_symbol)
        
        if validated_status:
            query = query.where(Position.status == validated_status)
        
        # Apply ordering and pagination
        query = query.order_by(desc(Position.opened_at)).offset(offset).limit(limit)
        
        # Execute query
        result = await db.execute(query)
        positions = result.scalars().all()
        
        # Convert to response models
        position_responses = [
            PositionResponse(
                position_id=pos.position_id,
                symbol=pos.symbol,
                side=pos.side.value,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=pos.current_price,
                unrealized_pnl=pos.unrealized_pnl,
                status=pos.status.value,
                opened_at=pos.opened_at,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit
            )
            for pos in positions
        ]
        
        return position_responses
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get positions: {str(e)}"
        )


@router.get("/portfolio/trades", response_model=List[TradeResponse])
async def get_trades(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING/EXECUTED/FAILED/CANCELLED)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get trade history.
    
    Returns list of executed trades with optional filtering.
    """
    
    try:
        # Validate and sanitize input parameters
        validated_symbol = validate_symbol(symbol)
        validated_status = validate_status(
            status,
            [s.value for s in TradeStatus]
        )
        
        # Build query
        query = select(Trade)
        
        if validated_symbol:
            query = query.where(Trade.symbol == validated_symbol)
        
        if validated_status:
            query = query.where(Trade.status == validated_status)
        
        # Apply ordering and pagination
        query = query.order_by(desc(Trade.executed_at)).offset(offset).limit(limit)
        
        # Execute query
        result = await db.execute(query)
        trades = result.scalars().all()
        
        # Convert to response models
        trade_responses = [
            TradeResponse(
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                side=trade.side.value,
                quantity=trade.quantity,
                price=trade.price,
                status=trade.status.value,
                executed_at=trade.executed_at,
                reasoning_chain_id=trade.reasoning_chain_id
            )
            for trade in trades
        ]
        
        return trade_responses
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trades: {str(e)}"
        )


@router.get("/portfolio/performance")
async def get_performance(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get portfolio performance metrics.
    
    Returns performance statistics for the specified period.
    """
    
    try:
        performance = await portfolio_service.get_performance_metrics(db, days=days)
        
        if not performance:
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
        
        return performance
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance metrics: {str(e)}"
        )

