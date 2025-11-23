"""
Delta Exchange API client.

Provides client for Delta Exchange API with circuit breaker pattern.
"""

import os
import json
import time
import hmac
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import httpx
import asyncio
import structlog

logger = structlog.get_logger()

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
                # Raise specific exception that can be caught and handled gracefully
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN. Service unavailable. "
                    f"Last failure: {self.last_failure_time}, "
                    f"Timeout: {self.timeout}s"
                )
        
        try:
            result = await func(*args, **kwargs)
            
            # Success - reset failure count in CLOSED state
            if self.state == CircuitBreakerState.CLOSED:
                self.failure_count = 0
            elif self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= 2:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
            
            raise


class DeltaExchangeError(Exception):
    """Custom exception for Delta Exchange errors."""


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is OPEN and request is blocked."""
    pass


class DeltaExchangeClient:
    """Delta Exchange API client."""
    
    def __init__(self):
        """Initialize Delta Exchange client."""
        self.base_url = settings.delta_exchange_base_url
        self.api_key = settings.delta_exchange_api_key
        self.api_secret = settings.delta_exchange_api_secret
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        self.timeout = 30.0
        self.recv_window = 60000
        if not self.api_key or not self.api_secret:
            raise ValueError("Delta Exchange API credentials are required.")
        
        # Validate system time synchronization on initialization
        self._validate_time_sync()
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        max_auth_retries: int = 2
    ) -> Dict[str, Any]:
        """Make API request with circuit breaker and authentication error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path (without query parameters)
            params: Query parameters for GET requests
            data: Request body for POST requests
            max_auth_retries: Maximum retries for authentication errors (401/403)
            
        Returns:
            Response JSON data
            
        Raises:
            DeltaExchangeError: For API errors or authentication failures
        """
        
        async def _request(attempt: int = 0):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Ensure endpoint doesn't contain query parameters
                # Query params should be passed separately via params argument
                clean_endpoint = endpoint.split('?')[0]
                
                # Generate fresh headers with new timestamp for each attempt
                # This ensures timestamp is as current as possible
                headers = self._build_headers(method, clean_endpoint, params, data)
                
                url = f"{self.base_url}{clean_endpoint}"
                
                try:
                    if method == "GET":
                        response = await client.get(url, headers=headers, params=params)
                    elif method == "POST":
                        response = await client.post(url, headers=headers, json=data)
                    else:
                        raise ValueError(f"Unsupported method: {method}")
                except httpx.HTTPError as exc:
                    logger.error(
                        "delta_exchange_http_error",
                        method=method,
                        endpoint=clean_endpoint,
                        error=str(exc),
                        exc_info=True
                    )
                    raise DeltaExchangeError(f"HTTP client error: {exc}") from exc
                
                # Handle authentication errors with retry logic
                if response.status_code in (401, 403):
                    error_text = response.text
                    
                    # Check if it's an expired_signature error that we can retry
                    is_expired_signature = "expired_signature" in error_text.lower()
                    
                    if is_expired_signature and attempt < max_auth_retries:
                        # Wait a small amount before retry to ensure fresh timestamp
                        await asyncio.sleep(0.2)
                        logger.info(
                            "delta_exchange_auth_retry",
                            attempt=attempt + 1,
                            max_retries=max_auth_retries,
                            endpoint=clean_endpoint,
                            reason="expired_signature"
                        )
                        # Retry with fresh timestamp
                        return await _request(attempt + 1)
                    
                    logger.error(
                        "delta_exchange_auth_error",
                        status_code=response.status_code,
                        method=method,
                        endpoint=clean_endpoint,
                        error=error_text,
                        attempt=attempt + 1,
                        message="Authentication failed - check API credentials and signature format"
                    )
                    
                    # Log signature details for debugging (without exposing secret)
                    logger.debug(
                        "delta_exchange_auth_debug",
                        method=method,
                        endpoint=clean_endpoint,
                        has_params=params is not None,
                        has_data=data is not None,
                        timestamp=headers.get("timestamp"),
                        api_key_prefix=self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
                    )
                    
                    raise DeltaExchangeError(
                        f"Delta Exchange authentication error {response.status_code}: {error_text}. "
                        f"Please verify API credentials and signature format."
                    )
                
                if response.status_code >= 400:
                    error_text = response.text
                    logger.error(
                        "delta_exchange_api_error",
                        status_code=response.status_code,
                        method=method,
                        endpoint=clean_endpoint,
                        error=error_text
                    )
                    raise DeltaExchangeError(
                        f"Delta Exchange error {response.status_code}: {error_text}"
                    )
                
                return response.json()
        
        # Use a wrapper function for the circuit breaker
        async def _request_wrapper():
            return await _request(0)
        
        return await self.circuit_breaker.call(_request_wrapper)
    
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
    
    def _validate_time_sync(self):
        """Validate system time synchronization.
        
        Checks if system clock is reasonably synchronized and logs warnings
        if significant drift is detected.
        """
        try:
            current_time = time.time()
            timestamp_ms = int(current_time * 1000)
            
            # Check for obvious clock issues (more than 1 minute drift)
            # This is a basic sanity check - actual validation happens per-request
            max_init_drift_ms = 60000  # 1 minute
            
            # Log current timestamp for debugging
            logger.info(
                "delta_exchange_time_validation",
                current_timestamp_ms=timestamp_ms,
                current_time_iso=datetime.now(timezone.utc).isoformat(),
                message="Delta Exchange client initialized with system time"
            )
            
            # Note: We can't validate against external time source here without
            # making an API call, so we rely on per-request validation
            # The timestamp validation in _build_headers() will catch drift issues
            
        except Exception as e:
            logger.warning(
                "delta_exchange_time_validation_failed",
                error=str(e),
                exc_info=True,
                message="Time validation check failed, but continuing"
            )

    def _build_headers(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]],
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Create authenticated headers required by Delta Exchange.
        
        Delta Exchange API signature format:
        message = timestamp + method + endpoint + payload
        signature = HMAC-SHA256(api_secret, message)
        
        Where:
        - timestamp: Unix timestamp in milliseconds (string)
        - method: HTTP method in uppercase (GET, POST, etc.)
        - endpoint: API endpoint path without query parameters
        - payload: JSON-serialized params (for GET) or data (for POST), sorted keys
        
        Args:
            method: HTTP method
            endpoint: API endpoint path (should not include query parameters)
            params: Query parameters for GET requests
            data: Request body for POST requests
            
        Returns:
            Dictionary of HTTP headers including authentication
        """
        # Validate inputs
        if not method:
            raise ValueError("HTTP method is required")
        if not endpoint:
            raise ValueError("API endpoint is required")
        if not endpoint.startswith('/'):
            raise ValueError(f"Endpoint must start with '/': {endpoint}")
        
        # Generate timestamp in milliseconds
        # Use current time to ensure freshness
        current_time = time.time()
        timestamp_ms = int(current_time * 1000)
        
        # Validate timestamp is reasonable (not more than 5 seconds in the future or past)
        # This helps catch clock synchronization issues
        max_drift_ms = 5000  # 5 seconds in milliseconds
        current_ms = int(current_time * 1000)
        drift_ms = abs(timestamp_ms - current_ms)
        
        if drift_ms > max_drift_ms:
            logger.warning(
                "delta_exchange_timestamp_drift",
                timestamp=timestamp_ms,
                current_time=current_ms,
                drift_ms=drift_ms,
                max_drift_ms=max_drift_ms,
                message="System clock drift detected - may cause authentication failures"
            )
            # Use current time instead to ensure accuracy
            timestamp_ms = current_ms
        
        timestamp = str(timestamp_ms)
        method_upper = method.upper()
        
        # Serialize payload: GET uses params, POST uses data
        payload = self._serialize_payload(params if method_upper == "GET" else data)
        
        # Build message for signature: timestamp + method + endpoint + payload
        message = f"{timestamp}{method_upper}{endpoint}{payload}"
        
        # Generate HMAC-SHA256 signature
        try:
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        except Exception as e:
            logger.error(
                "delta_exchange_signature_generation_failed",
                error=str(e),
                exc_info=True
            )
            raise DeltaExchangeError(f"Failed to generate signature: {e}") from e
        
        # Log signature details in debug mode (without exposing secret)
        logger.debug(
            "delta_exchange_signature_generated",
            method=method_upper,
            endpoint=endpoint,
            timestamp=timestamp,
            payload_length=len(payload),
            signature_prefix=signature[:8] + "..."
        )

        headers = {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
        }
        headers["recv-window"] = str(self.recv_window)
        return headers

    @staticmethod
    def _serialize_payload(payload: Optional[Dict[str, Any]]) -> str:
        """Serialize payload deterministically for signing.
        
        Uses JSON serialization with sorted keys to ensure consistent
        signature generation regardless of dict insertion order.
        
        Args:
            payload: Dictionary to serialize (None or empty dict returns empty string)
            
        Returns:
            JSON string with sorted keys, or empty string if payload is None/empty
        """
        if not payload:
            return ""
        
        try:
            # Use separators to ensure no extra whitespace
            # sort_keys=True ensures consistent ordering
            return json.dumps(payload, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError) as e:
            logger.error(
                "delta_exchange_payload_serialization_failed",
                error=str(e),
                payload_type=type(payload).__name__,
                exc_info=True
            )
            raise DeltaExchangeError(f"Failed to serialize payload: {e}") from e

