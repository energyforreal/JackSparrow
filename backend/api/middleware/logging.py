"""
Request logging middleware.

Provides structured logging for all API requests.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import structlog

from backend.core.logging import log_error_with_context

logger = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    """Request logging middleware."""
    
    async def dispatch(self, request: Request, call_next: Callable):
        """Log request and response."""
        
        # Get request details
        request_id = getattr(request.state, "request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        
        # Start timer
        start_time = time.time()
        
        # Log request
        logger.info(
            "request_started",
            request_id=request_id,
            method=method,
            path=path,
            query_params=query_params,
            client_ip=client_ip
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate process time
            process_time = time.time() - start_time
            
            # Log response
            logger.info(
                "request_completed",
                request_id=request_id,
                method=method,
                path=path,
                status_code=response.status_code,
                process_time_ms=round(process_time * 1000, 2),
                client_ip=client_ip
            )
            
            return response
            
        except Exception as e:
            # Calculate process time
            process_time = time.time() - start_time
            
            # Log error with enhanced context
            log_error_with_context(
                "request_failed",
                error=e,
                component="logging_middleware",
                request_id=request_id,
                method=method,
                path=path,
                query_params=query_params,
                process_time_ms=round(process_time * 1000, 2),
                client_ip=client_ip,
            )
            
            # Re-raise exception
            raise

