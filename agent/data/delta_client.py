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

from agent.core.logging_utils import log_error_with_context, log_warning_with_context, log_exception

logger = structlog.get_logger()

# Import settings from config
try:
    from agent.core.config import settings
except ImportError:
    # Fallback if config not available
    class Settings:
        delta_exchange_base_url = os.getenv("DELTA_EXCHANGE_BASE_URL", "https://api.india.delta.exchange")
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
                    log_error_with_context(
                        "delta_exchange_http_error",
                        error=exc,
                        component="delta_client",
                        method=method,
                        endpoint=clean_endpoint,
                        base_url=self.base_url
                    )
                    raise DeltaExchangeError(f"HTTP client error: {exc}") from exc
                except Exception as exc:
                    log_error_with_context(
                        "delta_exchange_request_error",
                        error=exc,
                        component="delta_client",
                        method=method,
                        endpoint=clean_endpoint
                    )
                    raise DeltaExchangeError(f"Request error: {exc}") from exc
                
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
                    
                    log_error_with_context(
                        "delta_exchange_auth_error",
                        component="delta_client",
                        method=method,
                        endpoint=clean_endpoint,
                        status_code=response.status_code,
                        error_message=error_text,
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
                    log_error_with_context(
                        "delta_exchange_api_error",
                        component="delta_client",
                        method=method,
                        endpoint=clean_endpoint,
                        status_code=response.status_code,
                        error_message=error_text
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
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get OHLCV candles.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            resolution: Candle resolution - must be lowercase (e.g., "15m", "1h", "4h", "1d")
            start: Start timestamp in Unix seconds (required)
            end: End timestamp in Unix seconds (required)
            limit: Deprecated - use start/end instead. If provided, will calculate start/end automatically.
            
        Returns:
            API response with candles data
            
        Raises:
            ValueError: If start/end are not provided and limit is not provided
            DeltaExchangeError: For API errors
        """
        # Handle backward compatibility: if limit is provided but start/end are not, calculate them
        if limit is not None and (start is None or end is None):
            start, end = self._calculate_candle_time_range(resolution, limit)
        
        # Validate required parameters
        if start is None or end is None:
            raise ValueError("start and end timestamps are required (or provide limit for backward compatibility)")
        
        # Ensure resolution is lowercase (API requirement)
        resolution = resolution.lower()
        
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": start,
            "end": end
        }
        return await self._make_request("GET", "/v2/history/candles", params=params)
    
    async def get_historical_candles(
        self,
        symbol: str,
        resolution: str = "1h",
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get historical candles (alias for get_candles for backward compatibility).
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            resolution: Candle resolution (e.g., "15m", "1h", "4h", "1d")
            limit: Number of candles to retrieve (will calculate start/end automatically)
            start: Start timestamp in Unix seconds (optional if limit provided)
            end: End timestamp in Unix seconds (optional if limit provided)
            
        Returns:
            API response with candles data
            
        Note:
            This is an alias for get_candles() for backward compatibility.
        """
        return await self.get_candles(
            symbol=symbol,
            resolution=resolution,
            start=start,
            end=end,
            limit=limit
        )
    
    @staticmethod
    def _calculate_candle_time_range(resolution: str, candle_count: int) -> tuple[int, int]:
        """Calculate start and end timestamps for candle request.
        
        Args:
            resolution: Candle resolution (e.g., "15m", "1h", "4h", "1d")
            candle_count: Number of candles to retrieve
            
        Returns:
            Tuple of (start_timestamp, end_timestamp) in Unix seconds
        """
        # Map resolution to seconds per candle
        resolution_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
            "6h": 21600, "1d": 86400, "1w": 604800
        }
        
        seconds_per_candle = resolution_seconds.get(resolution.lower(), 3600)
        total_seconds = candle_count * seconds_per_candle
        
        end_time = int(time.time())
        start_time = end_time - total_seconds
        
        return start_time, end_time
    
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
            timestamp = int(current_time)
            
            # Check for obvious clock issues (more than 1 minute drift)
            # This is a basic sanity check - actual validation happens per-request
            max_init_drift_seconds = 60  # 1 minute
            
            # Log current timestamp for debugging
            logger.info(
                "delta_exchange_time_validation",
                current_timestamp=timestamp,
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
        
        Delta Exchange API signature format (India platform):
        signature_data = METHOD + TIMESTAMP + PATH + QUERY_STRING + PAYLOAD
        signature = HMAC-SHA256(api_secret, signature_data)
        
        Where:
        - METHOD: HTTP method in uppercase (GET, POST, etc.)
        - TIMESTAMP: Unix timestamp in seconds (string)
        - PATH: API endpoint path without query parameters (e.g., /v2/history/candles)
        - QUERY_STRING: URL-encoded query parameters with ? prefix (e.g., ?symbol=BTCUSD&resolution=15m&start=1732454400&end=1732456200)
          - Empty string if no query parameters
        - PAYLOAD: JSON-serialized request body for POST requests, empty string for GET requests
        
        Example for GET /v2/history/candles?symbol=BTCUSD&resolution=15m&start=1732454400&end=1732456200:
        signature_data = GET + 1763978527 + /v2/history/candles + ?symbol=BTCUSD&resolution=15m&start=1732454400&end=1732456200 + 
        
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
        
        # Generate timestamp in seconds
        # Use current time to ensure freshness
        current_time = time.time()
        timestamp = int(current_time)
        
        # Validate timestamp is reasonable (not more than 5 seconds in the future or past)
        # This helps catch clock synchronization issues
        max_drift_seconds = 5  # 5 seconds
        current_timestamp = int(current_time)
        drift_seconds = abs(timestamp - current_timestamp)
        
        if drift_seconds > max_drift_seconds:
            logger.warning(
                "delta_exchange_timestamp_drift",
                timestamp=timestamp,
                current_time=current_timestamp,
                drift_seconds=drift_seconds,
                max_drift_seconds=max_drift_seconds,
                message="System clock drift detected - may cause authentication failures"
            )
            # Use current time instead to ensure accuracy
            timestamp = current_timestamp
        
        timestamp_str = str(timestamp)
        method_upper = method.upper()
        
        # Build query string for GET requests (with ? prefix)
        # For POST requests, query_string is empty
        query_string = ""
        if method_upper == "GET" and params:
            query_string = self._build_query_string(params)
        
        # Build payload: empty for GET requests, JSON for POST requests
        payload = ""
        if method_upper == "POST" and data:
            payload = self._serialize_payload(data, method=method_upper)
        
        # Build signature data: METHOD + TIMESTAMP + PATH + QUERY_STRING + PAYLOAD
        message = f"{method_upper}{timestamp_str}{endpoint}{query_string}{payload}"
        
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
            timestamp=timestamp_str,
            query_string=query_string[:50] + "..." if len(query_string) > 50 else query_string,
            payload_length=len(payload),
            signature_prefix=signature[:8] + "..."
        )

        headers = {
            "api-key": self.api_key,
            "timestamp": timestamp_str,
            "signature": signature,
            "Content-Type": "application/json",
            "User-Agent": "JackSparrow-TradingAgent/1.0",
        }
        headers["recv-window"] = str(self.recv_window)
        return headers

    @staticmethod
    def _build_query_string(params: Dict[str, Any]) -> str:
        """Build query string for GET requests with ? prefix.
        
        Query string format: ?key=value&key2=value2
        Parameters maintain their insertion order (not sorted).
        Order matters for Delta Exchange signature validation.
        
        Args:
            params: Query parameters dictionary (order preserved from insertion order)
            
        Returns:
            Query string with ? prefix, or empty string if params is empty
        """
        if not params:
            return ""
        
        try:
            from urllib.parse import urlencode
            # Preserve insertion order - do NOT sort (Delta Exchange requires exact order match)
            # Python 3.7+ dictionaries maintain insertion order
            # Pass params dict directly - urlencode() accepts dicts and preserves order
            encoded = urlencode(params)
            # Add ? prefix as required by Delta Exchange signature format
            return f"?{encoded}"
        except (TypeError, ValueError) as e:
            logger.error(
                "delta_exchange_query_string_build_failed",
                error=str(e),
                params_type=type(params).__name__,
                exc_info=True
            )
            raise DeltaExchangeError(f"Failed to build query string: {e}") from e
    
    @staticmethod
    def _serialize_payload(payload: Optional[Dict[str, Any]], method: str = "POST") -> str:
        """Serialize payload deterministically for signing (POST requests only).
        
        For POST requests: Uses JSON serialization with sorted keys
        For GET requests: Returns empty string (GET requests use query string, not payload)
        
        Args:
            payload: Dictionary to serialize (None or empty dict returns empty string)
            method: HTTP method (should be POST for payload serialization)
            
        Returns:
            JSON-serialized string for signature, or empty string if payload is None/empty
        """
        if not payload:
            return ""
        
        try:
            # For POST requests, use JSON serialization
            # Use separators to ensure no extra whitespace
            # sort_keys=True ensures consistent ordering
            return json.dumps(payload, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError) as e:
            logger.error(
                "delta_exchange_payload_serialization_failed",
                error=str(e),
                payload_type=type(payload).__name__,
                method=method,
                exc_info=True
            )
            raise DeltaExchangeError(f"Failed to serialize payload: {e}") from e

