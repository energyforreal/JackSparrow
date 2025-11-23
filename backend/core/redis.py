"""
Redis connection and utilities.

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
from backend.core.config import settings

logger = structlog.get_logger()

# Global Redis client
_redis_client: Optional[Redis] = None
_redis_connection_failed: bool = False
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


async def _reconnect_redis(required: bool = False) -> Optional[Redis]:
    """Reconnect to Redis with exponential backoff.
    
    Args:
        required: When True, raise if Redis is unavailable.
        
    Returns:
        Redis client or None if connection failed and not required.
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
                "redis_reconnected",
                service="backend",
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
                "redis_reconnection_failed",
                service="backend",
                attempts=_reconnection_attempts,
                max_attempts=_max_reconnection_attempts,
                error=str(e),
                exc_info=True,
            )
            # Retry with exponential backoff
            return await _reconnect_redis(required)
        else:
            logger.error(
                "redis_reconnection_exhausted",
                service="backend",
                attempts=_reconnection_attempts,
                redis_url=settings.redis_url,
                error=str(e),
                exc_info=True,
            )
            _redis_connection_failed = True
            if required or settings.redis_required:
                raise
            return None


async def get_redis(required: bool = False) -> Optional[Redis]:
    """Get or create Redis client with health checking and reconnection.

    Args:
        required: When True, raise if Redis is unavailable.
        
    Returns:
        Redis client or None if unavailable and not required.
    """
    global _redis_client, _redis_connection_failed, _reconnection_attempts
    
    # If we have a cached client, check its health
    if _redis_client is not None:
        if await _check_redis_health(_redis_client):
            return _redis_client
        else:
            # Client is stale, close it and reconnect
            logger.warning(
                "redis_client_unhealthy",
                service="backend"
            )
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
            logger.info("redis_connected", service="backend")
            return client
        else:
            await client.close()
            raise ConnectionError("Redis ping failed")
            
    except Exception as e:
        if not _redis_connection_failed:
            logger.warning(
                "redis_connection_failed",
                service="backend",
                redis_url=settings.redis_url,
                error=str(e),
                exc_info=True,
            )
        
        # Attempt reconnection with exponential backoff
        return await _reconnect_redis(required)


async def close_redis():
    """Close Redis connection."""
    global _redis_client, _redis_connection_failed, _reconnection_attempts
    
    if _redis_client is not None:
        try:
            await _redis_client.close()
        except Exception as e:
            logger.warning(
                "redis_close_error",
                service="backend",
                error=str(e)
            )
        _redis_client = None
    _redis_connection_failed = False
    _reconnection_attempts = 0


async def redis_health_check() -> Dict[str, Any]:
    """Check Redis health."""
    try:
        client = await get_redis()
        if client is None:
            return {"status": "down", "error": "Redis unavailable"}
        await client.ping()
        return {"status": "up", "error": None}
    except Exception as e:
        return {"status": "down", "error": str(e)}


# Queue operations
async def enqueue_command(command: Dict[str, Any], queue_name: Optional[str] = None) -> bool:
    """Enqueue command to agent command queue."""
    try:
        client = await get_redis()
        if client is None:
            logger.warning(
                "redis_unavailable_for_queue",
                queue=queue_name or settings.agent_command_queue,
                service="backend"
            )
            return False
        
        queue = queue_name or settings.agent_command_queue
        await client.lpush(queue, json.dumps(command))
        return True
    except Exception as e:
        logger.error(
            "redis_enqueue_command_failed",
            queue=queue_name or settings.agent_command_queue,
            error=str(e),
            exc_info=True
        )
        return False


async def dequeue_response(timeout: int = 5, queue_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Dequeue response from agent response queue."""
    try:
        client = await get_redis()
        queue = queue_name or settings.agent_response_queue
        
        result = await client.brpop(queue, timeout=timeout)
        if result:
            _, message = result
            return json.loads(message)
        return None
    except Exception as e:
        logger.error(
            "redis_dequeue_response_failed",
            queue=queue_name or settings.agent_response_queue,
            timeout=timeout,
            error=str(e),
            exc_info=True
        )
        return None


async def get_response(request_id: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
    """Get response by request ID from cache."""
    try:
        client = await get_redis()
        key = f"response:{request_id}"
        
        result = await client.get(key)
        if result:
            return json.loads(result)
        return None
    except Exception as e:
        logger.error(
            "redis_get_response_failed",
            request_id=request_id,
            error=str(e),
            exc_info=True
        )
        return None


async def cache_response(request_id: str, response: Dict[str, Any], ttl: int = 3600):
    """Cache response with TTL."""
    try:
        client = await get_redis()
        key = f"response:{request_id}"
        
        await client.setex(key, ttl, json.dumps(response))
    except Exception as e:
        logger.error(
            "redis_cache_response_failed",
            request_id=request_id,
            ttl=ttl,
            error=str(e),
            exc_info=True
        )


# Cache operations
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
            "redis_get_cache_failed",
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
            "redis_set_cache_failed",
            key=key,
            ttl=ttl,
            error=str(e),
            exc_info=True
        )
        return False


async def delete_cache(key: str) -> bool:
    """Delete key from cache."""
    try:
        client = await get_redis()
        await client.delete(key)
        return True
    except Exception as e:
        logger.error(
            "redis_delete_cache_failed",
            key=key,
            error=str(e),
            exc_info=True
        )
        return False


async def get_cache_keys(pattern: str) -> List[str]:
    """Get cache keys matching pattern."""
    try:
        client = await get_redis()
        keys = await client.keys(pattern)
        return keys
    except Exception as e:
        logger.error(
            "redis_get_cache_keys_failed",
            pattern=pattern,
            error=str(e),
            exc_info=True
        )
        return []

