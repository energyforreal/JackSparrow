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
        self.cache_ttl = 60  # Cache for 60 seconds
    
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
                    # Cache result
                    await set_cache(cache_key, market_data, ttl=self.cache_ttl)
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
        try:
            agent_response = await agent_service._send_command(
                "get_ticker",
                parameters={"symbol": symbol},
                timeout=5
            )
            
            if agent_response and agent_response.get("success"):
                ticker = agent_response.get("data")
                if ticker:
                    # Cache result
                    await set_cache(cache_key, ticker, ttl=10)  # Shorter cache for ticker
                    return ticker
        except Exception as e:
            logger.error(
                "market_service_get_ticker_failed",
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
                    # Cache result
                    await set_cache(cache_key, orderbook, ttl=5)  # Short cache for orderbook
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

