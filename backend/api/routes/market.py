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

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Query
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


@router.get("/market/ticker/{symbol}")
async def get_ticker_by_symbol(symbol: str):
    """
    Get current ticker information using path parameter.

    This is a convenience wrapper around the query-parameter-based
    `get_ticker` endpoint, for clients that call
    `/api/v1/market/ticker/{symbol}`.
    """
    return await get_ticker(symbol=symbol)


@router.get("/market/perpetual-stats")
async def get_perpetual_stats(symbol: str = Query("BTCUSD", description="Trading symbol")):
    """Get perpetual futures stats (price, basis, funding, open interest)."""
    try:
        ticker = await market_service.get_ticker(symbol)
        if not ticker:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticker not found for symbol {symbol}")

        # get_mark_price is expected to return similar object with close key else fallback
        mark_price_data = await market_service.get_ticker(symbol)  # using same ticker for now; can be changed
        mark_price = float(mark_price_data.get("price", ticker.get("price", 0)))

        return {
            "symbol": symbol,
            "last_price": float(ticker.get("price", 0)),
            "mark_price": mark_price,
            "basis_usd": round(mark_price - float(ticker.get("price", 0)), 2),
            "basis_pct": round((mark_price / max(float(ticker.get("price", 1)), 1e-9) - 1) * 100, 4),
            "funding_rate": float(ticker.get("funding_rate", 0.0)),
            "open_interest": float(ticker.get("open_interest", 0.0)),
            "next_funding_time": ticker.get("next_funding_time"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get perpetual stats: {str(e)}",
        )


@router.get("/market/funding-history")
async def get_funding_history(symbol: str = Query("BTCUSD", description="Trading symbol"), hours: int = Query(72, description="Lookback in hours")):
    """Get funding history for perpetual futures."""
    try:
        # New MarketService method to implement; if missing return 404
        if not hasattr(market_service, "get_funding_history"):
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Funding history is not supported by current market service implementation"
            )

        rates = await market_service.get_funding_history(symbol, hours)
        return {"symbol": symbol, "funding_history": rates}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get funding history: {str(e)}",
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

