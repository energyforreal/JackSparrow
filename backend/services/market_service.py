"""
Market data service.

Fetches market data from Delta Exchange API or agent service.
"""

from typing import Optional, Dict, Any, List
import httpx
import asyncio
import structlog

from backend.core.config import settings
from backend.core.redis import get_cache, set_cache
from backend.services.agent_service import agent_service

logger = structlog.get_logger()


class MarketService:
    """Service for fetching market data."""
    
    def __init__(self):
        """Initialize market service."""
        self.base_url = settings.delta_exchange_base_url
        # Optimized cache TTLs based on data freshness requirements
        self.cache_ttl_ticker = 2  # Ticker: 1-2 seconds (very fresh)
        self.cache_ttl_candles = {  # Candles: based on interval
            "1m": 5,
            "3m": 5,
            "5m": 5,
            "15m": 10,
            "30m": 15,
            "1h": 30,
            "2h": 60,
            "4h": 120,
            "1d": 300
        }
        self.cache_ttl_orderbook = 1  # Orderbook: 1 second (very fresh)
    
    async def get_market_data(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> Optional[Dict[str, Any]]:
        """Get market data (OHLCV candles)."""
        
        # Check cache first
        cache_key = f"market_data:{symbol}:{interval}:{limit}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        # Try to get from agent service first
        try:
            agent_response = await agent_service._send_command(
                "get_market_data",
                parameters={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit
                },
                timeout=10
            )
            
            if agent_response and agent_response.get("success"):
                market_data = agent_response.get("data")
                if market_data:
                    # Cache with interval-based TTL
                    ttl = self.cache_ttl_candles.get(interval, 15)  # Default 15s for unknown intervals
                    await set_cache(cache_key, market_data, ttl=ttl)
                    return market_data
        except Exception as e:
            logger.error(
                "market_service_get_market_data_failed",
                symbol=symbol,
                interval=interval,
                limit=limit,
                error=str(e),
                exc_info=True
            )
        
        # Fallback: return None (will be handled by route)
        return None
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current ticker information."""
        
        # Check cache first
        cache_key = f"ticker:{symbol}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        # Try to get from agent service
        agent_available = False
        try:
            agent_response = await agent_service._send_command(
                "get_ticker",
                parameters={"symbol": symbol},
                timeout=5
            )
            
            if agent_response and agent_response.get("success"):
                ticker = agent_response.get("data")
                if ticker:
                    # Cache with optimized TTL for ticker
                    await set_cache(cache_key, ticker, ttl=self.cache_ttl_ticker)
                    return ticker
                agent_available = True
        except Exception as e:
            logger.warning(
                "market_service_get_ticker_agent_failed",
                symbol=symbol,
                error=str(e),
                message="Agent unavailable, falling back to Delta Exchange API"
            )
        
        # Fallback: fetch directly from Delta Exchange API
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.base_url}/v2/tickers/{symbol}"
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    result = data.get("result", {})
                    
                    # Format ticker data to match agent response format
                    ticker = {
                        "symbol": symbol,
                        "price": float(result.get("close", 0)),
                        "open": float(result.get("open", 0)),
                        "high": float(result.get("high", 0)),
                        "low": float(result.get("low", 0)),
                        "volume": float(result.get("volume", 0)),
                        "change_24h": float(result.get("change_24h", 0)),
                        "timestamp": result.get("timestamp") or result.get("close_time")
                    }
                    
                    # Cache the result
                    await set_cache(cache_key, ticker, ttl=self.cache_ttl_ticker)
                    
                    logger.info(
                        "market_service_get_ticker_fallback_success",
                        symbol=symbol,
                        source="delta_exchange_api",
                        agent_available=agent_available
                    )
                    
                    return ticker
                else:
                    logger.error(
                        "market_service_get_ticker_delta_api_error",
                        symbol=symbol,
                        status_code=response.status_code,
                        response_text=response.text[:200]
                    )
        except Exception as e:
            logger.error(
                "market_service_get_ticker_fallback_failed",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )
        
        return None
    
    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Get order book."""
        
        # Check cache first
        cache_key = f"orderbook:{symbol}:{depth}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        # Try to get from agent service
        try:
            agent_response = await agent_service._send_command(
                "get_orderbook",
                parameters={
                    "symbol": symbol,
                    "depth": depth
                },
                timeout=5
            )
            
            if agent_response and agent_response.get("success"):
                orderbook = agent_response.get("data")
                if orderbook:
                    # Cache with optimized TTL for orderbook
                    await set_cache(cache_key, orderbook, ttl=self.cache_ttl_orderbook)
                    return orderbook
        except Exception as e:
            logger.error(
                "market_service_get_orderbook_failed",
                symbol=symbol,
                depth=depth,
                error=str(e),
                exc_info=True
            )
        
        return None


# Global market service instance
market_service = MarketService()

