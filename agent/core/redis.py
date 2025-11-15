"""
Redis connection and utilities for agent.

Provides Redis client and queue management for agent communication.
"""

import json
from typing import Optional, Dict, Any, List
import redis.asyncio as aioredis
from redis.asyncio import Redis

from agent.core.config import settings

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

