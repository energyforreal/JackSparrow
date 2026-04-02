"""
Rate limiting middleware.

Provides rate limiting for API endpoints using Redis.
"""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import structlog

from backend.core.redis import get_redis
from backend.core.config import settings

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Check rate limit before processing request."""
        
        # Skip rate limiting for health checks and docs
        if request.url.path in ["/api/v1/health", "/docs", "/openapi.json", "/"]:
            return await call_next(request)
        
        # Get client identifier (IP or user ID)
        client_id = request.client.host if request.client else "unknown"
        
        # Get user ID if authenticated
        user = getattr(request.state, "user", None)
        if user:
            client_id = user.get("user_id", client_id)
        
        # Get endpoint identifier
        endpoint = f"{request.method}:{request.url.path}"
        
        # Check rate limit
        allowed = await self._check_rate_limit(client_id, endpoint)
        
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(settings.rate_limit_window)},
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        remaining = await self._get_remaining_requests(client_id, endpoint)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + settings.rate_limit_window)
        
        return response
    
    async def _check_rate_limit(self, client_id: str, endpoint: str) -> bool:
        """Check if request is within rate limit."""
        
        try:
            redis = await get_redis()
            key = f"rate_limit:{client_id}:{endpoint}"
            
            # Get current count
            current = await redis.get(key)
            
            if current is None:
                # First request in window
                await redis.setex(key, settings.rate_limit_window, 1)
                return True
            
            current_count = int(current)
            
            if current_count >= settings.rate_limit_requests:
                return False
            
            # Increment count
            await redis.incr(key)
            return True
            
        except Exception as e:
            # If Redis fails, allow request (fail open)
            logger.warning(
                "rate_limit_check_failed",
                client_id=client_id,
                endpoint=endpoint,
                error=str(e),
                exc_info=True
            )
            return True
    
    async def _get_remaining_requests(self, client_id: str, endpoint: str) -> int:
        """Get remaining requests in current window."""
        
        try:
            redis = await get_redis()
            key = f"rate_limit:{client_id}:{endpoint}"
            
            current = await redis.get(key)
            if current is None:
                return settings.rate_limit_requests
            
            current_count = int(current)
            return max(0, settings.rate_limit_requests - current_count)
            
        except Exception:
            return settings.rate_limit_requests

