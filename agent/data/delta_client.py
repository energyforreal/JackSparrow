"""
Delta Exchange API client.

Provides client for Delta Exchange API with circuit breaker pattern.
"""

import os
import json
import time
import hmac
import hashlib
from typing import Dict, Any, Optional, List, Callable, Set
from datetime import datetime, timezone
import httpx
import asyncio
import structlog
import websockets
from websockets.exceptions import ConnectionClosedError, WebSocketException

from agent.core.logging_utils import log_error_with_context, log_warning_with_context, log_exception

logger = structlog.get_logger()


class RateLimiter:
    """Token-bucket rate limiter for Delta API calls."""

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max(1, int(max_calls))
        self.window_seconds = max(0.01, float(window_seconds))
        self._timestamps: List[float] = []

    async def acquire(self) -> None:
        now = time.time()
        cutoff = now - self.window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_calls:
            sleep_s = self._timestamps[0] + self.window_seconds - now
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            now = time.time()
            cutoff = now - self.window_seconds
            self._timestamps = [t for t in self._timestamps if t > cutoff]
        self._timestamps.append(time.time())


# Public: 20 req/s; private: 10 req/s (conservative defaults)
_PUBLIC_RATE_LIMITER = RateLimiter(max_calls=20, window_seconds=1.0)
_PRIVATE_RATE_LIMITER = RateLimiter(max_calls=10, window_seconds=1.0)

# Import settings from config
try:
    from agent.core.config import settings
except ImportError:
    # Fallback if config not available
    class Settings:
        delta_exchange_base_url = os.getenv(
            "DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org"
        )
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
        
        self._credentials_valid = not (
            self._is_placeholder_credential(self.api_key)
            or self._is_placeholder_credential(self.api_secret)
        )
        if not self._credentials_valid:
            # If credentials are placeholders (e.g. env defaults like `changeme`),
            # don't hammer the API with retries that will never recover.
            logger.warning(
                "delta_exchange_credentials_placeholder_detected",
                api_key_prefix=(self.api_key or "")[:6]
                + ("..." if len(self.api_key or "") > 6 else ""),
                message="Delta Exchange credentials appear to be placeholders; pausing auth-backed requests.",
                component="delta_client",
            )
            self.circuit_breaker.state = CircuitBreakerState.OPEN
            self.circuit_breaker.failure_count = self.circuit_breaker.failure_threshold
            self.circuit_breaker.last_failure_time = time.time()
        
        # Used to de-duplicate repeated transient error logs (timeouts, rate limits, etc.).
        self._transient_log_state: Dict[str, float] = {}
        self._auth_blocked_reason: Optional[str] = None
        self._auth_blocked_client_ip: Optional[str] = None
        
        # Validate system time synchronization on initialization
        self._validate_time_sync()
        # Delta signature timestamps are Unix seconds; offset = server - local (refreshed on auth errors).
        self._auth_timestamp_offset_seconds: int = 0

    @staticmethod
    def _is_public_market_endpoint(endpoint: str) -> bool:
        """Return True when Delta serves this GET path without API-key signing."""
        clean = (endpoint or "").split("?")[0]
        if clean == "/v2/history/candles":
            return True
        if clean.startswith("/v2/tickers/"):
            return True
        if clean.startswith("/v2/l2orderbook/"):
            return True
        if clean.startswith("/v2/products/"):
            return True
        return False

    @staticmethod
    def _extract_client_ip_from_error(error_text: str) -> Optional[str]:
        """Parse Delta auth error JSON for the rejected client IP."""
        try:
            payload = json.loads(error_text or "")
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        err = payload.get("error")
        if not isinstance(err, dict):
            return None
        ctx = err.get("context")
        if not isinstance(ctx, dict):
            return None
        ip = ctx.get("client_ip")
        return str(ip) if ip else None

    def _latch_auth_blocked(self, reason: str, *, client_ip: Optional[str] = None) -> None:
        """Pause signed private API calls until credentials/IP whitelist are fixed."""
        self._auth_blocked_reason = reason
        if client_ip:
            self._auth_blocked_client_ip = client_ip
        if self.circuit_breaker.state == CircuitBreakerState.OPEN:
            return
        self.circuit_breaker.state = CircuitBreakerState.OPEN
        self.circuit_breaker.failure_count = self.circuit_breaker.failure_threshold
        self.circuit_breaker.last_failure_time = time.time()
        logger.error(
            "delta_exchange_auth_blocked",
            reason=reason,
            client_ip=client_ip or self._auth_blocked_client_ip,
            component="delta_client",
            message=(
                "Delta Exchange private API paused. For ip_restriction, whitelist the "
                "reported client_ip on your Delta API key settings."
            ),
        )

    @staticmethod
    def _classify_delta_auth_error(error_text: str) -> str:
        """Coarse bucket for 401/403 bodies (logging and retry policy)."""
        t = (error_text or "").lower()
        if "expired_signature" in t:
            return "expired_signature"
        if "timestamp" in t and ("expired" in t or "invalid" in t):
            return "timestamp_skew"
        if "invalid_signature" in t or ("signature" in t and "invalid" in t):
            return "invalid_signature"
        if "permission" in t or "scope" in t:
            return "permission_scope"
        if "ip" in t and "not" in t:
            return "ip_restriction"
        return "unknown_auth"

    def _parse_server_unix_seconds(self, data: Dict[str, Any]) -> Optional[int]:
        """Extract server Unix seconds from common Delta JSON shapes."""
        if not isinstance(data, dict):
            return None
        r = data.get("result")
        candidates: List[Any] = []
        if isinstance(r, dict):
            for k in ("server_time", "time", "timestamp", "current_timestamp"):
                if r.get(k) is not None:
                    candidates.append(r.get(k))
        for k in ("server_time", "time", "timestamp"):
            if data.get(k) is not None:
                candidates.append(data.get(k))
        for v in candidates:
            try:
                iv = int(float(v))
                if iv > 1_000_000_000_000:
                    iv //= 1000
                return iv
            except (TypeError, ValueError):
                continue
        return None

    async def _refresh_auth_time_offset_unauthenticated(self) -> None:
        """Align local signature timestamp offset using a public time endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for path in ("/v2/public/time", "/v2/time"):
                    try:
                        r = await client.get(f"{self.base_url}{path}")
                        if r.status_code != 200:
                            continue
                        data = r.json()
                        ts = self._parse_server_unix_seconds(data)
                        if ts is None:
                            continue
                        local = int(time.time())
                        self._auth_timestamp_offset_seconds = int(ts) - local
                        logger.info(
                            "delta_exchange_auth_time_offset_refreshed",
                            server_ts=ts,
                            local_ts=local,
                            offset_seconds=self._auth_timestamp_offset_seconds,
                            path=path,
                            component="delta_client",
                        )
                        return
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(
                "delta_exchange_time_offset_refresh_failed",
                error=str(e),
                component="delta_client",
            )

    @staticmethod
    def _is_placeholder_credential(value: Optional[str]) -> bool:
        """Return True if the credential value looks like a placeholder/misconfiguration."""
        if value is None:
            return True
        v = value.strip().lower()
        if not v:
            return True
        placeholders = {
            "changeme",
            "change_me",
            "your_api_key",
            "your_api_secret",
            "dev-api-key",
            "dev-api-secret",
            "test",
            "placeholder",
        }
        return v in placeholders

    def _should_sample_log(self, key: str, interval_seconds: float) -> bool:
        """Return True if enough time has passed since the last log for `key`."""
        now = time.time()
        last = self._transient_log_state.get(key, 0.0)
        if (now - last) >= interval_seconds:
            self._transient_log_state[key] = now
            return True
        return False

    async def _make_public_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Unauthenticated GET for public market-data endpoints (no IP whitelist on key)."""
        if method.upper() != "GET":
            raise ValueError("Public Delta API helper supports GET only")
        clean_endpoint = endpoint.split("?")[0]
        if not self._is_public_market_endpoint(clean_endpoint):
            raise ValueError(f"Endpoint is not a public market path: {clean_endpoint}")

        url = f"{self.base_url}{clean_endpoint}"
        query_string = self._build_query_string(params) if params else ""
        await _PUBLIC_RATE_LIMITER.acquire()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                response = await client.get(f"{url}{query_string}")
        except httpx.HTTPError as exc:
            raise DeltaExchangeError(f"HTTP client error: {exc}") from exc

        if response.status_code >= 400:
            error_text = response.text
            raise DeltaExchangeError(
                f"Delta Exchange public API error {response.status_code}: {error_text}"
            )
        return response.json()
    
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
            await _PRIVATE_RATE_LIMITER.acquire()
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
                        # Build URL with an explicit query-string so the request encoding
                        # matches exactly what we used for signature generation.
                        query_string = self._build_query_string(params) if params else ""
                        response = await client.get(f"{url}{query_string}", headers=headers)
                    elif method in ("POST", "DELETE"):
                        # Body bytes must match the compact JSON used for signing.
                        body_str = (
                            self._serialize_payload(data, method=method.upper())
                            if data
                            else ""
                        )
                        body_bytes = body_str.encode("utf-8") if body_str else b""
                        if method == "POST":
                            response = await client.post(
                                url, headers=headers, content=body_bytes
                            )
                        else:
                            response = await client.request(
                                "DELETE", url, headers=headers, content=body_bytes
                            )
                    else:
                        raise ValueError(f"Unsupported method: {method}")
                except httpx.HTTPError as exc:
                    exc_name = type(exc).__name__
                    is_timeout = "Timeout" in exc_name or "timed out" in str(exc).lower()
                    sample_key = f"delta_exchange_http_error:{exc_name}:{clean_endpoint}"
                    if is_timeout and not self._should_sample_log(sample_key, interval_seconds=60):
                        # De-duplicate noisy timeout logs.
                        raise DeltaExchangeError(f"HTTP timeout error: {exc}") from exc

                    log_fn = log_warning_with_context if is_timeout else log_error_with_context
                    log_fn(
                        "delta_exchange_http_error",
                        error=exc,
                        component="delta_client",
                        method=method,
                        endpoint=clean_endpoint,
                        base_url=self.base_url,
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
                    auth_class = DeltaExchangeClient._classify_delta_auth_error(error_text)

                    # Check if it's an expired_signature error that we can retry
                    is_expired_signature = "expired_signature" in error_text.lower()

                    if (
                        auth_class in ("expired_signature", "timestamp_skew")
                        and attempt < max_auth_retries
                        and not is_expired_signature
                    ):
                        await self._refresh_auth_time_offset_unauthenticated()
                        await asyncio.sleep(max(0.05, 1.0 - (time.time() % 1.0)))
                        logger.info(
                            "delta_exchange_auth_retry",
                            attempt=attempt + 1,
                            max_retries=max_auth_retries,
                            endpoint=clean_endpoint,
                            reason="timestamp_skew_offset_refresh",
                            auth_error_class=auth_class,
                            component="delta_client",
                        )
                        return await _request(attempt + 1)

                    if is_expired_signature and attempt < max_auth_retries:
                        # Important: signatures use whole-second timestamps.
                        # If we retry within the same second, the signature stays identical
                        # and won't recover. Wait until at least the next second boundary.
                        timestamp_used_str = headers.get("timestamp") or ""
                        try:
                            timestamp_used = int(timestamp_used_str)
                        except Exception:
                            timestamp_used = int(time.time())
                        next_second = timestamp_used + 1
                        sleep_for = max(0.01, next_second - time.time())
                        await asyncio.sleep(sleep_for)
                        await self._refresh_auth_time_offset_unauthenticated()
                        logger.info(
                            "delta_exchange_auth_retry",
                            attempt=attempt + 1,
                            max_retries=max_auth_retries,
                            endpoint=clean_endpoint,
                            reason="expired_signature",
                            timestamp_used=timestamp_used,
                            sleep_seconds=round(sleep_for, 3),
                            local_time=int(time.time()),
                            auth_error_class=auth_class,
                        )
                        # Retry with fresh timestamp
                        return await _request(attempt + 1)
                    
                    sample_key = f"delta_exchange_auth_error:{response.status_code}:{clean_endpoint}"
                    should_log = self._should_sample_log(sample_key, interval_seconds=120)
                    if should_log:
                        log_warning_with_context(
                            "delta_exchange_auth_error",
                            component="delta_client",
                            method=method,
                            endpoint=clean_endpoint,
                            status_code=response.status_code,
                            error_message=error_text,
                            attempt=attempt + 1,
                            timestamp=headers.get("timestamp"),
                            local_time=int(time.time()),
                            auth_error_class=auth_class,
                            auth_timestamp_offset_seconds=self._auth_timestamp_offset_seconds,
                            message="Authentication failed - check API credentials, scopes, and clock sync",
                        )

                    if auth_class == "ip_restriction":
                        client_ip = self._extract_client_ip_from_error(error_text)
                        self._latch_auth_blocked("ip_restriction", client_ip=client_ip)
                        ip_hint = client_ip or self._auth_blocked_client_ip or "your host IP"
                        raise DeltaExchangeError(
                            f"Delta Exchange API key IP whitelist: add {ip_hint} to the key's "
                            f"allowed IPs in Delta Exchange settings. Raw: {error_text}"
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
                    transient_status = response.status_code in {429, 500, 502, 503, 504}
                    sample_key = f"delta_exchange_api_error:{response.status_code}:{clean_endpoint}"
                    should_log = self._should_sample_log(sample_key, interval_seconds=120) if transient_status else True
                    if should_log:
                        log_fn = log_warning_with_context if transient_status else log_error_with_context
                        log_fn(
                            "delta_exchange_api_error",
                            component="delta_client",
                            method=method,
                            endpoint=clean_endpoint,
                            status_code=response.status_code,
                            error_message=error_text,
                        )
                    raise DeltaExchangeError(
                        f"Delta Exchange error {response.status_code}: {error_text}"
                    )
                
                return response.json()
        
        # Use a wrapper function for the circuit breaker
        async def _request_wrapper():
            if not self._credentials_valid:
                # Short-circuit immediately on placeholder credentials.
                # Raise as CircuitBreakerOpenError so callers treat it as a pause
                # without hammering the API with repeated auth retries.
                raise CircuitBreakerOpenError(
                    "Delta Exchange credentials appear to be placeholders; request execution paused."
                )
            if self._auth_blocked_reason == "ip_restriction":
                ip_hint = self._auth_blocked_client_ip or "your host IP"
                raise CircuitBreakerOpenError(
                    f"Delta Exchange private API paused (IP whitelist): add {ip_hint} "
                    "to your API key allowed IPs in Delta Exchange settings."
                )
            return await _request(0)
        
        return await self.circuit_breaker.call(_request_wrapper)
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get ticker information."""
        return await self._make_public_request("GET", f"/v2/tickers/{symbol}")
    
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
            logger.warning(
                "delta_exchange_get_candles_limit_deprecated",
                resolution=resolution,
                limit=limit,
                message="Using deprecated `limit` argument; pass explicit start/end timestamps.",
            )
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
        return await self._make_public_request("GET", "/v2/history/candles", params=params)
    
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
        return await self._make_public_request("GET", f"/v2/l2orderbook/{symbol}", params=params)
    
    async def resolve_product_id(self, symbol: str) -> int:
        """Resolve Delta product_id for a symbol (product_specs cache, then settings)."""
        sym = (symbol or "").strip().upper() or "BTCUSD"
        try:
            from agent.core.product_specs import get_contract_specs

            specs = await get_contract_specs(sym)
            pid = int(specs.product_id)
            env_pid = int(getattr(settings, "product_id", 0) or 0)
            if env_pid > 0 and env_pid != pid:
                logger.warning(
                    "delta_product_id_env_mismatch",
                    symbol=sym,
                    env_product_id=env_pid,
                    resolved_product_id=pid,
                )
            return pid
        except Exception as exc:
            logger.warning(
                "delta_product_id_resolve_failed",
                symbol=sym,
                error=str(exc),
            )
            pid = int(getattr(settings, "product_id", 0) or 0)
            if pid <= 0:
                raise DeltaExchangeError(
                    f"Could not resolve product_id for {sym}; set PRODUCT_ID in environment"
                ) from exc
            return pid

    @staticmethod
    def _normalize_order_type(order_type: str) -> str:
        order_type_upper = (order_type or "MARKET").upper()
        if order_type_upper in ("MARKET", "MKT"):
            return "market_order"
        if order_type_upper == "LIMIT":
            return "limit_order"
        lowered = order_type.lower()
        if lowered == "market":
            return "market_order"
        if lowered == "limit":
            return "limit_order"
        return lowered

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        *,
        stop_price: Optional[float] = None,
        stop_order_type: Optional[str] = None,
        product_id: Optional[int] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        use_product_symbol_only: bool = False,
    ) -> Dict[str, Any]:
        """Place order on Delta Exchange (live/testnet)."""
        if quantity != int(quantity):
            raise DeltaExchangeError(
                "Order size must be a whole number (integer lots); fractional lots are not allowed"
            )
        lots = int(quantity)
        if lots < 1:
            raise DeltaExchangeError("Order size must be at least 1 lot")

        delta_order_type = self._normalize_order_type(order_type)
        pid = product_id
        if pid is None and not use_product_symbol_only:
            pid = await self.resolve_product_id(symbol)

        data: Dict[str, Any] = {
            "size": lots,
            "side": side.lower(),
            "order_type": delta_order_type,
        }
        if use_product_symbol_only or pid is None:
            sym = (symbol or "").strip().upper()
            if not sym:
                raise DeltaExchangeError("product_symbol is required when product_id is not set")
            data["product_symbol"] = sym
        else:
            data["product_id"] = int(pid)

        if reduce_only:
            data["reduce_only"] = "true"
        if client_order_id:
            data["client_order_id"] = str(client_order_id)[:32]
        if delta_order_type == "limit_order" and price is not None:
            data["limit_price"] = str(price)
        if stop_price is not None:
            data["stop_price"] = str(stop_price)
            data["stop_order_type"] = str(stop_order_type or "stop_loss_order")

        return await self._make_request("POST", "/v2/orders", data=data)

    async def place_bracket_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        *,
        bracket_stop_loss_price: Optional[float] = None,
        bracket_take_profit_price: Optional[float] = None,
        bracket_trail_amount: Optional[float] = None,
        product_id: Optional[int] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        use_product_symbol_only: bool = False,
    ) -> Dict[str, Any]:
        """Place entry order with atomic bracket SL/TP on Delta Exchange."""
        if quantity != int(quantity):
            raise DeltaExchangeError(
                "Order size must be a whole number (integer lots); fractional lots are not allowed"
            )
        lots = int(quantity)
        if lots < 1:
            raise DeltaExchangeError("Order size must be at least 1 lot")

        delta_order_type = self._normalize_order_type(order_type)
        pid = product_id
        if pid is None and not use_product_symbol_only:
            pid = await self.resolve_product_id(symbol)

        data: Dict[str, Any] = {
            "size": lots,
            "side": side.lower(),
            "order_type": delta_order_type,
        }
        if use_product_symbol_only or pid is None:
            sym = (symbol or "").strip().upper()
            if not sym:
                raise DeltaExchangeError("product_symbol is required when product_id is not set")
            data["product_symbol"] = sym
        else:
            data["product_id"] = int(pid)

        if reduce_only:
            data["reduce_only"] = "true"
        if client_order_id:
            data["client_order_id"] = str(client_order_id)[:32]
        if delta_order_type == "limit_order" and price is not None:
            data["limit_price"] = str(price)
        if bracket_stop_loss_price is not None:
            sl = str(bracket_stop_loss_price)
            data["bracket_stop_loss_price"] = sl
            data["bracket_stop_loss_limit_price"] = sl
        if bracket_take_profit_price is not None:
            tp = str(bracket_take_profit_price)
            data["bracket_take_profit_price"] = tp
            data["bracket_take_profit_limit_price"] = tp
        if bracket_trail_amount is not None:
            data["bracket_trail_amount"] = str(bracket_trail_amount)

        return await self._make_request("POST", "/v2/orders", data=data)

    async def get_fills(
        self,
        product_ids: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """GET /v2/fills — trade fill history for P&L reconciliation."""
        params: Dict[str, Any] = {"page_size": int(page_size)}
        if product_ids:
            params["product_ids"] = product_ids
        if start_time is not None:
            params["start_time"] = int(start_time)
        if end_time is not None:
            params["end_time"] = int(end_time)
        return await self._make_request("GET", "/v2/fills", params=params)

    async def get_orders(
        self,
        product_ids: Optional[str] = None,
        states: Optional[str] = None,
        contract_types: Optional[str] = None,
        order_types: Optional[str] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List active orders (GET /v2/orders)."""
        params: Dict[str, Any] = {}
        if product_ids:
            params["product_ids"] = product_ids
        if states:
            params["states"] = states
        if contract_types:
            params["contract_types"] = contract_types
        if order_types:
            params["order_types"] = order_types
        if page_size is not None:
            params["page_size"] = page_size
        return await self._make_request("GET", "/v2/orders", params=params or None)

    async def get_orders_history(
        self,
        product_ids: Optional[str] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Order history (GET /v2/orders/history)."""
        params: Dict[str, Any] = {}
        if product_ids:
            params["product_ids"] = product_ids
        if page_size is not None:
            params["page_size"] = page_size
        return await self._make_request("GET", "/v2/orders/history", params=params or None)

    async def cancel_order(
        self,
        order_id: int,
        *,
        product_id: Optional[int] = None,
        product_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel a specific open order (DELETE /v2/orders)."""
        if product_id is None and not product_symbol:
            raise DeltaExchangeError(
                "cancel_order requires product_id or product_symbol"
            )
        data: Dict[str, Any] = {"id": int(order_id)}
        if product_id is not None:
            data["product_id"] = int(product_id)
        else:
            data["product_symbol"] = product_symbol
        return await self._make_request("DELETE", "/v2/orders", data=data)

    async def cancel_all_orders(
        self,
        *,
        product_id: Optional[int] = None,
        product_symbol: Optional[str] = None,
        cancel_limit_orders: bool = True,
        cancel_stop_orders: bool = True,
    ) -> Dict[str, Any]:
        """Cancel all open orders for a product (DELETE /v2/orders/all)."""
        if product_id is None and not product_symbol:
            raise DeltaExchangeError(
                "cancel_all_orders requires product_id or product_symbol"
            )
        data: Dict[str, Any] = {
            "cancel_limit_orders": "true" if cancel_limit_orders else "false",
            "cancel_stop_orders": "true" if cancel_stop_orders else "false",
        }
        if product_id is not None:
            data["product_id"] = int(product_id)
        else:
            data["product_symbol"] = product_symbol
        return await self._make_request("DELETE", "/v2/orders/all", data=data)

    async def get_positions(
        self,
        product_id: Optional[int] = None,
        product_symbol: Optional[str] = None,
        underlying_asset_symbol: Optional[str] = None,
        *,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get real-time position (GET /v2/positions); prefers product_id when set."""
        params: Dict[str, Any] = {}
        if product_id is not None:
            params["product_id"] = int(product_id)
        elif product_symbol:
            params["product_symbol"] = product_symbol
        elif symbol:
            params["product_symbol"] = symbol
        if underlying_asset_symbol:
            params["underlying_asset_symbol"] = underlying_asset_symbol
        if not params:
            raise DeltaExchangeError(
                "get_positions requires product_id, product_symbol, or symbol"
            )
        return await self._make_request("GET", "/v2/positions", params=params)

    async def get_margined_positions(
        self,
        contract_types: Optional[str] = "perpetual_futures",
    ) -> Dict[str, Any]:
        """Get margined positions (GET /v2/positions/margined)."""
        params: Dict[str, Any] = {}
        if contract_types:
            params["contract_types"] = contract_types
        return await self._make_request(
            "GET", "/v2/positions/margined", params=params or None
        )

    async def get_assets(self) -> Dict[str, Any]:
        """Get exchange assets metadata."""
        return await self._make_request("GET", "/v2/assets")

    async def get_wallet_balances(self) -> Dict[str, Any]:
        """Get wallet balances (GET /v2/wallet/balances)."""
        return await self._make_request("GET", "/v2/wallet/balances")

    async def change_margin(self, product_symbol: str, margin: float) -> Dict[str, Any]:
        """Adjust isolated position margin."""
        data = {"product_symbol": product_symbol, "margin": margin}
        return await self._make_request("POST", "/v2/positions/change_margin", data=data)

    async def close_all_positions(
        self,
        *,
        close_all_portfolio: bool = True,
        close_all_isolated: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Emergency close all open positions (POST /v2/positions/close_all)."""
        data: Dict[str, Any] = {
            "close_all_portfolio": bool(close_all_portfolio),
            "close_all_isolated": bool(close_all_isolated),
        }
        if user_id is not None:
            data["user_id"] = int(user_id)
        return await self._make_request("POST", "/v2/positions/close_all", data=data)
    
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
        
        # Unix seconds for signing, adjusted by server-derived offset when refreshed.
        timestamp = int(time.time()) + int(getattr(self, "_auth_timestamp_offset_seconds", 0))
        timestamp_str = str(timestamp)
        method_upper = method.upper()
        
        # Build query string for GET requests (with ? prefix)
        # For POST requests, query_string is empty
        query_string = ""
        if method_upper == "GET" and params:
            query_string = self._build_query_string(params)
        
        # Build payload: empty for GET; compact JSON for POST/DELETE bodies
        payload = ""
        if method_upper in ("POST", "DELETE") and data:
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


class DeltaExchangeWebSocketClient:
    """WebSocket client for real-time Delta Exchange data streaming."""

    WS_AUTH_PATH = "/live"

    def __init__(self, api_key: str, api_secret: str, base_url: Optional[str] = None,
                 max_reconnect_attempts: int = 5, reconnect_delay: float = 5.0,
                 heartbeat_interval: float = 30.0,
                 on_connection_lost: Optional[Callable[[str], None]] = None):
        """Initialize WebSocket client.

        Args:
            api_key: Delta Exchange API key
            api_secret: Delta Exchange API secret
            base_url: WebSocket base URL (uses config default if None)
            max_reconnect_attempts: Maximum reconnection attempts
            reconnect_delay: Delay between reconnection attempts
            heartbeat_interval: Heartbeat interval in seconds
            on_connection_lost: Optional callback(reason) when the socket drops or is closed
        """
        # Import settings here to avoid circular imports
        from agent.core.config import settings

        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url or settings.websocket_url
        self._credentials_valid = not (
            DeltaExchangeClient._is_placeholder_credential(self.api_key)
            or DeltaExchangeClient._is_placeholder_credential(self.api_secret)
        )
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.subscribed_symbols: Set[str] = set()
        self.message_handlers: Dict[str, List[Callable]] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._message_task: Optional[asyncio.Task] = None
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.heartbeat_interval = heartbeat_interval
        self._last_heartbeat = time.time()
        self._circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        self.on_connection_lost = on_connection_lost
        self._manual_disconnect = False

    def _invoke_connection_lost(self, reason: str) -> None:
        if self.on_connection_lost:
            try:
                self.on_connection_lost(reason)
            except Exception as e:
                logger.warning(
                    "delta_websocket_connection_lost_callback_error",
                    error=str(e),
                    reason=reason,
                )

    def build_websocket_auth_payload(self) -> Dict[str, Any]:
        """Build Delta ``key-auth`` payload (GET + unix_seconds + /live)."""
        method = "GET"
        path = self.WS_AUTH_PATH
        timestamp = str(int(time.time()))
        signature_data = f"{method}{timestamp}{path}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "type": "key-auth",
            "payload": {
                "api-key": self.api_key,
                "signature": signature,
                "timestamp": timestamp,
            },
        }

    async def connect(self) -> None:
        """Establish WebSocket connection and send Delta key-auth message."""
        self._manual_disconnect = False
        try:
            if not self._credentials_valid:
                logger.warning(
                    "delta_websocket_credentials_placeholder_detected",
                    message="Skipping Delta Exchange WebSocket connect due to placeholder credentials.",
                    component="delta_websocket_client",
                )
                return

            logger.info("delta_websocket_connecting", url=self.base_url)

            await self._circuit_breaker.call(self._connect_websocket, self.base_url)

            auth_payload = self.build_websocket_auth_payload()
            await self.websocket.send(json.dumps(auth_payload))
            logger.info(
                "delta_websocket_key_auth_sent",
                auth_path=self.WS_AUTH_PATH,
            )

            self.connected = True
            logger.info("delta_websocket_connected")

            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._message_task = asyncio.create_task(self._message_loop())

            # Resubscribe to previously subscribed symbols
            if self.subscribed_symbols:
                await self._resubscribe_all()

        except Exception as e:
            logger.error("delta_websocket_connection_failed", error=str(e), exc_info=True)
            raise DeltaExchangeError(f"WebSocket connection failed: {e}") from e

    async def _connect_websocket(self, url: str) -> None:
        """Internal method to establish WebSocket connection."""
        # Use a slightly more tolerant ping configuration to reduce spurious
        # keepalive timeouts while still detecting real disconnects.
        self.websocket = await websockets.connect(
            url,
            ping_interval=30.0,  # Send ping every 30 seconds
            ping_timeout=30.0,   # Allow up to 30 seconds for pong
            close_timeout=5.0,
        )

    async def disconnect(self) -> None:
        """Close WebSocket connection and cleanup tasks."""
        self._manual_disconnect = True
        self.connected = False
        self._invoke_connection_lost("disconnect")

        # Cancel background tasks
        for task in [self._reconnect_task, self._heartbeat_task, self._message_task]:
            if task and not task.done():
                task.cancel()

        # Close WebSocket connection
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.warning("delta_websocket_close_error", error=str(e))
            finally:
                self.websocket = None

        logger.info("delta_websocket_disconnected")

    async def subscribe_ticker(self, symbols: List[str]) -> None:
        """Subscribe to v2/ticker channel for real-time ticker updates.

        Args:
            symbols: List of symbols to subscribe to (e.g., ['BTCUSD'])
        """
        if not self.connected or not self.websocket:
            raise DeltaExchangeError("WebSocket not connected")

        subscription_message = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": "v2/ticker",
                        "symbols": symbols
                    }
                ]
            }
        }

        try:
            await self.websocket.send(json.dumps(subscription_message))
            self.subscribed_symbols.update(symbols)

            logger.info(
                "delta_websocket_subscribed_ticker",
                symbols=symbols,
                channel="v2/ticker"
            )

        except Exception as e:
            logger.error(
                "delta_websocket_subscription_failed",
                error=str(e),
                symbols=symbols,
                channel="v2/ticker"
            )
            raise DeltaExchangeError(f"Subscription failed: {e}") from e

    async def unsubscribe_ticker(self, symbols: List[str]) -> None:
        """Unsubscribe from v2/ticker channel.

        Args:
            symbols: List of symbols to unsubscribe from
        """
        if not self.connected or not self.websocket:
            raise DeltaExchangeError("WebSocket not connected")

        unsubscription_message = {
            "type": "unsubscribe",
            "payload": {
                "channels": [
                    {
                        "name": "v2/ticker",
                        "symbols": symbols
                    }
                ]
            }
        }

        try:
            await self.websocket.send(json.dumps(unsubscription_message))
            self.subscribed_symbols.difference_update(symbols)

            logger.info(
                "delta_websocket_unsubscribed_ticker",
                symbols=symbols,
                channel="v2/ticker"
            )

        except Exception as e:
            logger.error(
                "delta_websocket_unsubscription_failed",
                error=str(e),
                symbols=symbols,
                channel="v2/ticker"
            )
            raise DeltaExchangeError(f"Unsubscription failed: {e}") from e

    def add_message_handler(self, message_type: str, handler: Callable) -> None:
        """Add a handler for specific message types.

        Args:
            message_type: Type of message to handle (e.g., 'ticker')
            handler: Async callable that takes message data
        """
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []
        self.message_handlers[message_type].append(handler)

    def remove_message_handler(self, message_type: str, handler: Callable) -> None:
        """Remove a message handler.

        Args:
            message_type: Type of message
            handler: Handler to remove
        """
        if message_type in self.message_handlers:
            try:
                self.message_handlers[message_type].remove(handler)
                if not self.message_handlers[message_type]:
                    del self.message_handlers[message_type]
            except ValueError:
                pass  # Handler not found

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all previously subscribed symbols after reconnection."""
        if self.subscribed_symbols:
            symbols_list = list(self.subscribed_symbols)
            await self.subscribe_ticker(symbols_list)
            logger.info("delta_websocket_resubscribed", symbols=symbols_list)

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat messages to keep connection alive."""
        try:
            while self.connected:
                await asyncio.sleep(self.heartbeat_interval)

                if self.websocket and self.connected:
                    try:
                        # Send a simple ping or heartbeat
                        heartbeat_msg = {"type": "ping"}
                        await self.websocket.send(json.dumps(heartbeat_msg))
                        self._last_heartbeat = time.time()

                        logger.debug("delta_websocket_heartbeat_sent")

                    except Exception as e:
                        logger.warning("delta_websocket_heartbeat_failed", error=str(e))
                        break

        except asyncio.CancelledError:
            logger.debug("delta_websocket_heartbeat_cancelled")
        except Exception as e:
            logger.error("delta_websocket_heartbeat_error", error=str(e), exc_info=True)

    async def _message_loop(self) -> None:
        """Main message processing loop."""
        try:
            while self.connected and self.websocket:
                try:
                    # Receive message with timeout
                    message_raw = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=60.0
                    )

                    # Parse JSON message
                    message = json.loads(message_raw)

                    # Process message
                    await self._process_message(message)

                except asyncio.TimeoutError:
                    # Timeout is normal, continue listening
                    continue
                except (ConnectionClosedError, WebSocketException) as e:
                    logger.warning("delta_websocket_connection_lost", error=str(e))
                    self.connected = False
                    if not self._manual_disconnect:
                        self._invoke_connection_lost("connection_closed")
                        asyncio.create_task(self._reconnect())
                    break
                except json.JSONDecodeError as e:
                    logger.warning("delta_websocket_invalid_json", error=str(e), raw_message=message_raw[:200])
                    continue
                except Exception as e:
                    logger.error("delta_websocket_message_error", error=str(e), exc_info=True)
                    continue

        except asyncio.CancelledError:
            logger.debug("delta_websocket_message_loop_cancelled")
        except Exception as e:
            logger.error("delta_websocket_message_loop_error", error=str(e), exc_info=True)

    async def _process_message(self, message: Dict[str, Any]) -> None:
        """Process incoming WebSocket message."""
        try:
            message_type = message.get("type", "unknown")

            if message_type in ("key-auth", "auth", "authenticated"):
                success = message.get("success")
                if success is False:
                    logger.error(
                        "delta_websocket_auth_rejected",
                        payload=message.get("payload") or message,
                    )
                else:
                    logger.info("delta_websocket_auth_confirmed", type=message_type)
                return

            # Handle subscription confirmations
            if message_type == "subscription":
                logger.info("delta_websocket_subscription_confirmed", payload=message.get("payload"))
                return

            # Handle ticker updates (both v2/ticker and ticker formats)
            if message_type in ("ticker", "v2/ticker"):
                symbol = message.get("symbol")
                if symbol and "ticker" in self.message_handlers:
                    # Call all registered handlers
                    for handler in self.message_handlers["ticker"]:
                        try:
                            await handler(message)
                        except Exception as e:
                            logger.error(
                                "delta_websocket_handler_error",
                                error=str(e),
                                symbol=symbol,
                                handler=handler.__name__,
                                exc_info=True
                            )

            # Handle other message types
            elif message_type in self.message_handlers:
                for handler in self.message_handlers[message_type]:
                    try:
                        await handler(message)
                    except Exception as e:
                        logger.error(
                            "delta_websocket_handler_error",
                            error=str(e),
                            message_type=message_type,
                            handler=handler.__name__,
                            exc_info=True
                        )

            # Log unknown message types for debugging
            else:
                logger.debug("delta_websocket_unknown_message_type", message_type=message_type, message=message)

        except Exception as e:
            logger.error("delta_websocket_message_processing_error", error=str(e), message=message, exc_info=True)

    async def _reconnect(self) -> None:
        """Handle reconnection logic."""
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Reconnection already in progress

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnection loop with exponential backoff."""
        for attempt in range(self.max_reconnect_attempts):
            try:
                logger.info(
                    "delta_websocket_reconnecting",
                    attempt=attempt + 1,
                    max_attempts=self.max_reconnect_attempts
                )

                await asyncio.sleep(self.reconnect_delay * (2 ** attempt))  # Exponential backoff

                await self.connect()
                logger.info("delta_websocket_reconnected")
                return

            except Exception as e:
                logger.warning(
                    "delta_websocket_reconnect_failed",
                    attempt=attempt + 1,
                    error=str(e)
                )

                if attempt == self.max_reconnect_attempts - 1:
                    logger.error(
                        "delta_websocket_max_reconnect_attempts_reached",
                        max_attempts=self.max_reconnect_attempts
                    )
                    # Could emit an event or callback here for application-level handling
                    break

