"""
Market data service.

Fetches and caches market data from Delta Exchange.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from agent.data.delta_client import DeltaExchangeClient
from agent.core.redis import get_cache, set_cache


class MarketDataService:
    """Market data service."""
    
    def __init__(self):
        """Initialize market data service."""
        self.delta_client = DeltaExchangeClient()
        self.cache_ttl = 60  # Cache for 60 seconds
        self.ticker_cache_ttl = 10  # Shorter cache for ticker
    
    async def initialize(self):
        """Initialize market data service."""
        pass
    
    async def shutdown(self):
        """Shutdown market data service."""
        pass
    
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
        
        try:
            # Map interval to Delta Exchange resolution
            resolution_map = {
                "15m": "15M",
                "1h": "1H",
                "4h": "4H",
                "1d": "1D"
            }
            resolution = resolution_map.get(interval, "1H")
            
            # Fetch from Delta Exchange
            response = await self.delta_client.get_candles(
                symbol=symbol,
                resolution=resolution,
                limit=limit
            )
            
            # Parse response
            candles = response.get("result", {}).get("candles", [])
            
            # Convert to standard format
            formatted_candles = []
            for candle in candles:
                formatted_candles.append({
                    "timestamp": candle.get("time"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": float(candle.get("volume", 0))
                })
            
            # Get latest ticker for current price
            ticker = await self.get_ticker(symbol)
            current_price = ticker.get("close") if ticker else None
            
            market_data = {
                "symbol": symbol,
                "interval": interval,
                "candles": formatted_candles,
                "current_price": current_price,
                "data_age_seconds": 0,  # Fresh data
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Cache result
            await set_cache(cache_key, market_data, ttl=self.cache_ttl)
            
            return market_data
            
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return None
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current ticker information."""
        
        # Check cache first
        cache_key = f"ticker:{symbol}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        try:
            # Fetch from Delta Exchange
            response = await self.delta_client.get_ticker(symbol)
            
            # Parse response
            ticker_data = response.get("result", {})
            
            ticker = {
                "symbol": symbol,
                "price": float(ticker_data.get("close", 0)),
                "open": float(ticker_data.get("open", 0)),
                "high": float(ticker_data.get("high", 0)),
                "low": float(ticker_data.get("low", 0)),
                "volume": float(ticker_data.get("volume", 0)),
                "change_24h": float(ticker_data.get("change_24h", 0)),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Cache result
            await set_cache(cache_key, ticker, ttl=self.ticker_cache_ttl)
            
            return ticker
            
        except Exception as e:
            print(f"Error fetching ticker: {e}")
            return None
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
        """Get order book."""
        
        try:
            # Fetch from Delta Exchange
            response = await self.delta_client.get_orderbook(symbol, depth=depth)
            
            # Parse response
            orderbook_data = response.get("result", {})
            
            return {
                "symbol": symbol,
                "bids": orderbook_data.get("buy", []),
                "asks": orderbook_data.get("sell", []),
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"Error fetching orderbook: {e}")
            return None
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        
        circuit_breaker_state = self.delta_client.get_circuit_breaker_state()
        
        return {
            "status": "up" if circuit_breaker_state["state"] != "OPEN" else "down",
            "circuit_breaker": circuit_breaker_state
        }

