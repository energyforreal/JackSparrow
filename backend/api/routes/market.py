"""
Market data endpoints.

Provides market data from Delta Exchange.

**Authentication**: These endpoints are intentionally public (no authentication required).
Market data endpoints provide read-only access to public market information and are
typically accessed by frontend applications without authentication. This follows common
practices for public market data APIs.

If authentication is required in the future, add `dependencies=[Depends(require_auth)]`
to the router initialization below.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List

from backend.api.models.requests import MarketDataRequest
from backend.api.models.responses import MarketDataResponse
from backend.services.market_service import market_service

# Intentionally public - no authentication required for market data
router = APIRouter()


@router.get("/market/data", response_model=MarketDataResponse)
async def get_market_data(
    symbol: str = Query(..., description="Trading symbol"),
    interval: str = Query("1h", description="Time interval"),
    limit: int = Query(100, ge=1, le=1000, description="Number of candles")
):
    """
    Get market data (OHLCV candles).
    
    Returns historical candle data for the specified symbol and interval.
    """
    
    try:
        market_data = await market_service.get_market_data(
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        
        if not market_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Market data not found for symbol {symbol}"
            )
        
        return MarketDataResponse(**market_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market data: {str(e)}"
        )


@router.get("/market/ticker")
async def get_ticker(
    symbol: str = Query(..., description="Trading symbol")
):
    """
    Get current ticker information.
    
    Returns latest price and 24h statistics.
    """
    
    try:
        ticker = await market_service.get_ticker(symbol)
        
        if not ticker:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticker not found for symbol {symbol}"
            )
        
        return ticker
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ticker: {str(e)}"
        )


@router.get("/market/orderbook")
async def get_orderbook(
    symbol: str = Query(..., description="Trading symbol"),
    depth: int = Query(20, ge=1, le=100, description="Order book depth")
):
    """
    Get order book.
    
    Returns current order book with bids and asks.
    """
    
    try:
        orderbook = await market_service.get_orderbook(symbol, depth=depth)
        
        if not orderbook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order book not found for symbol {symbol}"
            )
        
        return orderbook
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get order book: {str(e)}"
        )

