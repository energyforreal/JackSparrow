"""
Redis connection and utilities.

Provides Redis client and queue management for agent communication.
"""

import json
from typing import Optional, Dict, Any, List
import redis.asyncio as aioredis
from redis.asyncio import Redis
from backend.core.config import settings

# Global Redis client
_redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    """Get or create Redis client."""
    global _redis_client
    
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    return _redis_client


async def close_redis():
    """Close Redis connection."""
    global _redis_client
    
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


async def redis_health_check() -> Dict[str, Any]:
    """Check Redis health."""
    try:
        client = await get_redis()
        await client.ping()
        return {"status": "up", "error": None}
    except Exception as e:
        return {"status": "down", "error": str(e)}


# Queue operations
async def enqueue_command(command: Dict[str, Any], queue_name: Optional[str] = None) -> bool:
    """Enqueue command to agent command queue."""
    try:
        client = await get_redis()
        queue = queue_name or settings.agent_command_queue
        
        await client.lpush(queue, json.dumps(command))
        return True
    except Exception as e:
        print(f"Error enqueueing command: {e}")
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
        print(f"Error dequeueing response: {e}")
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
        print(f"Error getting response: {e}")
        return None


async def cache_response(request_id: str, response: Dict[str, Any], ttl: int = 3600):
    """Cache response with TTL."""
    try:
        client = await get_redis()
        key = f"response:{request_id}"
        
        await client.setex(key, ttl, json.dumps(response))
    except Exception as e:
        print(f"Error caching response: {e}")


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
        print(f"Error getting cache: {e}")
        return None


async def set_cache(key: str, value: Any, ttl: int = 60) -> bool:
    """Set value in cache with TTL."""
    try:
        client = await get_redis()
        await client.setex(key, ttl, json.dumps(value))
        return True
    except Exception as e:
        print(f"Error setting cache: {e}")
        return False


async def delete_cache(key: str) -> bool:
    """Delete key from cache."""
    try:
        client = await get_redis()
        await client.delete(key)
        return True
    except Exception as e:
        print(f"Error deleting cache: {e}")
        return False


async def get_cache_keys(pattern: str) -> List[str]:
    """Get cache keys matching pattern."""
    try:
        client = await get_redis()
        keys = await client.keys(pattern)
        return keys
    except Exception as e:
        print(f"Error getting cache keys: {e}")
        return []

