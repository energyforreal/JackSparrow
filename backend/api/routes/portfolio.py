"""
Portfolio management endpoints.

Provides portfolio status, positions, and performance metrics.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List

from backend.core.database import get_db, Position, Trade
from backend.api.models.requests import PortfolioRequest
from backend.api.models.responses import PortfolioSummaryResponse, PositionResponse, TradeResponse, ErrorResponse
from backend.services.portfolio_service import portfolio_service

router = APIRouter()


@router.get("/portfolio/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary(
    db: Session = Depends(get_db)
):
    """
    Get portfolio summary.
    
    Returns total value, balance, positions, and PnL.
    """
    
    try:
        summary = await portfolio_service.get_portfolio_summary(db)
        
        if not summary:
            # Return empty portfolio if no data
            return PortfolioSummaryResponse(
                total_value=0,
                available_balance=0,
                open_positions=0,
                total_unrealized_pnl=0,
                total_realized_pnl=0,
                positions=[]
            )
        
        return PortfolioSummaryResponse(**summary)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get portfolio summary: {str(e)}"
        )


@router.get("/portfolio/positions", response_model=List[PositionResponse])
async def get_positions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    status: Optional[str] = Query(None, description="Filter by status (OPEN/CLOSED)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db)
):
    """
    Get positions list.
    
    Returns list of positions with optional filtering.
    """
    
    try:
        # Build query
        query = db.query(Position)
        
        if symbol:
            query = query.filter(Position.symbol == symbol)
        
        if status:
            query = query.filter(Position.status == status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        positions = query.order_by(desc(Position.opened_at)).offset(offset).limit(limit).all()
        
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
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db)
):
    """
    Get trade history.
    
    Returns list of executed trades with optional filtering.
    """
    
    try:
        # Build query
        query = db.query(Trade)
        
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        
        if status:
            query = query.filter(Trade.status == status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        trades = query.order_by(desc(Trade.executed_at)).offset(offset).limit(limit).all()
        
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
    db: Session = Depends(get_db)
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

