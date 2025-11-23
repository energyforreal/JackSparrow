"""
Redis connection and utilities for agent.

Provides Redis client and queue management for agent communication.
"""

import json
import asyncio
import time
from typing import Optional, Dict, Any, List
import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, TimeoutError
import structlog

from agent.core.config import settings

logger = structlog.get_logger()

# Global Redis client
_redis_client: Optional[Redis] = None
_redis_connection_failed: bool = False
_redis_optional: bool = True  # Agent can operate without Redis (event bus disabled)
_reconnection_attempts: int = 0
_last_reconnection_attempt: float = 0.0
_max_reconnection_attempts: int = 5
_base_backoff_seconds: float = 1.0


async def _check_redis_health(client: Redis) -> bool:
    """Check if Redis client is healthy by pinging it.
    
    Args:
        client: Redis client to check.
        
    Returns:
        True if client is healthy, False otherwise.
    """
    try:
        await client.ping()
        return True
    except Exception:
        return False


async def _reconnect_redis() -> Optional[Redis]:
    """Reconnect to Redis with exponential backoff.
    
    Returns:
        Redis client or None if connection failed.
    """
    global _redis_client, _redis_connection_failed, _reconnection_attempts, _last_reconnection_attempt
    
    # Calculate exponential backoff delay
    if _reconnection_attempts > 0:
        delay = _base_backoff_seconds * (2 ** (_reconnection_attempts - 1))
        # Cap max delay at 60 seconds
        delay = min(delay, 60.0)
        
        # Only wait if enough time has passed since last attempt
        time_since_last = time.time() - _last_reconnection_attempt
        if time_since_last < delay:
            await asyncio.sleep(delay - time_since_last)
    
    _last_reconnection_attempt = time.time()
    
    try:
        client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            retry_on_error=[ConnectionError, TimeoutError],
            retry_on_timeout=True,
        )
        
        # Verify connection with ping
        if await _check_redis_health(client):
            _redis_client = client
            _redis_connection_failed = False
            _reconnection_attempts = 0
            logger.info(
                "agent_redis_reconnected",
                attempts=_reconnection_attempts
            )
            return client
        else:
            # Ping failed, close and retry
            await client.close()
            raise ConnectionError("Redis ping failed")
            
    except Exception as e:
        _reconnection_attempts += 1
        
        if _reconnection_attempts < _max_reconnection_attempts:
            logger.warning(
                "agent_redis_reconnection_failed",
                attempts=_reconnection_attempts,
                max_attempts=_max_reconnection_attempts,
                error=str(e),
                exc_info=True,
            )
            # Retry with exponential backoff
            return await _reconnect_redis()
        else:
            logger.warning(
                "agent_redis_reconnection_exhausted",
                attempts=_reconnection_attempts,
                redis_url=settings.redis_url,
                error=str(e),
                message="Agent will continue without Redis event bus",
                exc_info=True,
            )
            _redis_connection_failed = True
            return None


async def get_redis() -> Optional[Redis]:
    """Get or create Redis client with error handling and graceful degradation.
    
    Returns:
        Redis client or None if unavailable. Agent can continue without Redis.
    """
    global _redis_client, _redis_connection_failed, _reconnection_attempts
    
    # If we have a cached client, check its health
    if _redis_client is not None:
        if await _check_redis_health(_redis_client):
            return _redis_client
        else:
            # Client is stale, close it and reconnect
            logger.warning("agent_redis_client_unhealthy")
            try:
                await _redis_client.close()
            except Exception:
                pass
            _redis_client = None
            _reconnection_attempts = 0
    
    # Create new connection or reconnect
    if _redis_connection_failed and _reconnection_attempts >= _max_reconnection_attempts:
        # Reset attempts after some time to allow retry
        if time.time() - _last_reconnection_attempt > 300:  # 5 minutes
            _reconnection_attempts = 0
            _redis_connection_failed = False
    
    try:
        client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            retry_on_error=[ConnectionError, TimeoutError],
            retry_on_timeout=True,
        )
        
        # Verify connection with ping
        if await _check_redis_health(client):
            _redis_client = client
            _redis_connection_failed = False
            _reconnection_attempts = 0
            logger.info("agent_redis_connected")
            return client
        else:
            await client.close()
            raise ConnectionError("Redis ping failed")
            
    except Exception as e:
        if not _redis_connection_failed:
            logger.warning(
                "agent_redis_connection_failed",
                redis_url=settings.redis_url,
                error=str(e),
                message="Agent will continue without Redis event bus",
                exc_info=True,
            )
        
        # Attempt reconnection with exponential backoff
        return await _reconnect_redis()


async def close_redis():
    """Close Redis connection."""
    global _redis_client, _redis_connection_failed, _reconnection_attempts
    
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception as e:
            logger.warning(
                "agent_redis_close_error",
                error=str(e)
            )
        _redis_client = None
    _redis_connection_failed = False
    _reconnection_attempts = 0


async def get_cache(key: str) -> Optional[Any]:
    """Get value from cache."""
    try:
        client = await get_redis()
        value = await client.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        logger.error(
            "agent_redis_get_cache_failed",
            key=key,
            error=str(e),
            exc_info=True
        )
        return None


async def set_cache(key: str, value: Any, ttl: int = 60) -> bool:
    """Set value in cache with TTL."""
    try:
        client = await get_redis()
        await client.setex(key, ttl, json.dumps(value))
        return True
    except Exception as e:
        logger.error(
            "agent_redis_set_cache_failed",
            key=key,
            ttl=ttl,
            error=str(e),
            exc_info=True
        )
        return False

