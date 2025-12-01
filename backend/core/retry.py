"""
Retry utilities with exponential backoff.

Provides retry decorators and functions for handling transient failures.
"""

import asyncio
import time
from typing import Callable, TypeVar, Optional, List, Type
from functools import wraps
import structlog

logger = structlog.get_logger()

T = TypeVar('T')


async def retry_with_backoff(
    func: Callable[..., T],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Optional[List[Type[Exception]]] = None,
    *args,
    **kwargs
) -> T:
    """Retry a function with exponential backoff.
    
    Args:
        func: Async function to retry
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff calculation
        retryable_exceptions: List of exception types to retry on (default: all exceptions)
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
        
    Returns:
        Result from func
        
    Raises:
        Last exception if all retries fail
    """
    if retryable_exceptions is None:
        retryable_exceptions = [Exception]
    
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            # Check if exception is retryable
            if not any(isinstance(e, exc_type) for exc_type in retryable_exceptions):
                raise
            
            # Don't retry on last attempt
            if attempt == max_attempts - 1:
                break
            
            # Calculate delay with exponential backoff
            delay = min(initial_delay * (exponential_base ** attempt), max_delay)
            
            logger.warning(
                "retry_attempt",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                delay=delay,
                error=str(e),
                error_type=type(e).__name__
            )
            
            await asyncio.sleep(delay)
    
    # All retries exhausted
    logger.error(
        "retry_exhausted",
        max_attempts=max_attempts,
        error=str(last_exception),
        error_type=type(last_exception).__name__ if last_exception else None
    )
    raise last_exception


def retry_with_backoff_decorator(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Optional[List[Type[Exception]]] = None
):
    """Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff calculation
        retryable_exceptions: List of exception types to retry on
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_backoff(
                func,
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                retryable_exceptions=retryable_exceptions,
                *args,
                **kwargs
            )
        return wrapper
    return decorator
