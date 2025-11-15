"""
Delta Exchange API client.

Provides client for Delta Exchange API with circuit breaker pattern.
"""

import os
from typing import Dict, Any, Optional
from datetime import datetime
import httpx
import asyncio
import time

# Import settings from config
try:
    from agent.core.config import settings
except ImportError:
    # Fallback if config not available
    class Settings:
        delta_exchange_base_url = os.getenv("DELTA_EXCHANGE_BASE_URL", "https://api.delta.exchange")
        delta_exchange_api_key = os.getenv("DELTA_EXCHANGE_API_KEY", "")
        delta_exchange_api_secret = os.getenv("DELTA_EXCHANGE_API_SECRET", "")
    settings = Settings()


class CircuitBreakerState:
    """Circuit breaker states."""
    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Failing, block requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for Delta Exchange API."""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        """Initialize circuit breaker."""
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitBreakerState.CLOSED
        self.success_count = 0
    
    async def call(self, func, *args, **kwargs):
        """Call function with circuit breaker protection."""
        
        if self.state == CircuitBreakerState.OPEN:
            # Check if timeout has passed
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            
            # Success
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= 2:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
            
            raise


class DeltaExchangeClient:
    """Delta Exchange API client."""
    
    def __init__(self):
        """Initialize Delta Exchange client."""
        self.base_url = settings.delta_exchange_base_url
        self.api_key = settings.delta_exchange_api_key
        self.api_secret = settings.delta_exchange_api_secret
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        self.timeout = 30.0
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make API request with circuit breaker."""
        
        async def _request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {
                    "api-key": self.api_key,
                    "api-secret": self.api_secret
                }
                
                url = f"{self.base_url}{endpoint}"
                
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=data)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                response.raise_for_status()
                return response.json()
        
        return await self.circuit_breaker.call(_request)
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get ticker information."""
        return await self._make_request("GET", f"/v2/tickers/{symbol}")
    
    async def get_candles(
        self,
        symbol: str,
        resolution: str = "1h",
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get OHLCV candles."""
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "limit": limit
        }
        return await self._make_request("GET", "/v2/history/candles", params=params)
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """Get order book."""
        params = {
            "symbol": symbol,
            "depth": depth
        }
        return await self._make_request("GET", f"/v2/l2orderbook/{symbol}", params=params)
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Place order (paper trading)."""
        data = {
            "symbol": symbol,
            "side": side.lower(),
            "size": quantity,
            "type": order_type.lower()
        }
        
        if order_type == "LIMIT" and price:
            data["price"] = price
        
        return await self._make_request("POST", "/v2/orders", data=data)
    
    def get_circuit_breaker_state(self) -> Dict[str, Any]:
        """Get circuit breaker state."""
        return {
            "state": self.circuit_breaker.state,
            "failure_count": self.circuit_breaker.failure_count,
            "last_failure_time": self.circuit_breaker.last_failure_time
        }

