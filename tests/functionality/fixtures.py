"""Shared test fixtures for functionality tests."""

import asyncio
import threading
import socket
import os
from typing import Optional, Dict, Any
from datetime import datetime
import aiohttp
import websockets

from tests.functionality.config import config
from tests.functionality.utils import ServiceHealthChecker


def find_free_port(start_port: int = 8001, max_attempts: int = 10) -> int:
    """
    Find a free port starting from start_port.
    
    Args:
        start_port: Starting port number
        max_attempts: Maximum number of ports to try
        
    Returns:
        First available port number
        
    Raises:
        RuntimeError: If no free port found
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Try to bind to the port
            result = s.connect_ex(('localhost', port))
            if result != 0:  # Port is not in use
                return port
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_attempts}")


def is_port_in_use(port: int) -> bool:
    """Check if a port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


class SharedResources:
    """Singleton for shared test resources."""
    
    _instance: Optional['SharedResources'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._agent: Optional[Any] = None
        self._backend_client: Optional[aiohttp.ClientSession] = None
        self._agent_websocket: Optional[Any] = None
        self._backend_websocket: Optional[Any] = None
        self._redis: Optional[Any] = None
        self._database: Optional[Any] = None
        self._initialized_at: Optional[datetime] = None
    
    async def get_agent(self):
        """Get or create shared agent instance."""
        if self._agent is None:
            try:
                from agent.core.intelligent_agent import IntelligentAgent
                
                # Check if default feature server port is in use and find alternative
                default_port = 8001
                if is_port_in_use(default_port):
                    free_port = find_free_port(default_port + 1, max_attempts=20)
                    os.environ['FEATURE_SERVER_PORT'] = str(free_port)
                    # Also update config if it's accessible
                    if hasattr(config, 'feature_server_port'):
                        config.feature_server_port = free_port
                
                self._agent = IntelligentAgent()
                await self._agent.initialize()
                self._initialized_at = datetime.utcnow()
            except Exception as e:
                raise RuntimeError(f"Failed to initialize agent: {e}")
        return self._agent
    
    async def get_backend_client(self) -> aiohttp.ClientSession:
        """Get or create shared backend HTTP client."""
        if self._backend_client is None or self._backend_client.closed:
            self._backend_client = aiohttp.ClientSession(base_url=config.backend_url)
        return self._backend_client
    
    async def get_agent_websocket(self):
        """Get or create agent WebSocket connection."""
        if self._agent_websocket is None:
            try:
                self._agent_websocket = await websockets.connect(config.agent_websocket_url)
            except Exception as e:
                raise RuntimeError(f"Failed to connect to agent WebSocket: {e}")
        return self._agent_websocket
    
    async def get_backend_websocket(self):
        """Get or create backend WebSocket connection."""
        if self._backend_websocket is None:
            try:
                self._backend_websocket = await websockets.connect(config.backend_websocket_url)
            except Exception as e:
                raise RuntimeError(f"Failed to connect to backend WebSocket: {e}")
        return self._backend_websocket
    
    async def get_redis(self):
        """Get or create shared Redis connection."""
        if self._redis is None:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(config.redis_url or "redis://localhost:6379")
                await self._redis.ping()
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Redis: {e}")
        return self._redis
    
    async def get_database(self):
        """Get or create shared database connection."""
        if self._database is None:
            try:
                from sqlalchemy import create_engine
                if config.database_url:
                    self._database = create_engine(config.database_url, pool_pre_ping=True)
                else:
                    raise RuntimeError("Database URL not configured")
            except Exception as e:
                raise RuntimeError(f"Failed to connect to database: {e}")
        return self._database
    
    async def cleanup(self):
        """Cleanup all shared resources."""
        if self._backend_client and not self._backend_client.closed:
            await self._backend_client.close()
        
        if self._agent_websocket:
            await self._agent_websocket.close()
        
        if self._backend_websocket:
            await self._backend_websocket.close()
        
        if self._redis:
            await self._redis.aclose()
        
        if self._agent:
            try:
                await self._agent.shutdown()
            except Exception:
                pass
        
        # Reset all references
        self._agent = None
        self._backend_client = None
        self._agent_websocket = None
        self._backend_websocket = None
        self._redis = None
        self._database = None
        self._initialized_at = None


# Global shared resources instance
_shared_resources = SharedResources()


async def get_shared_agent():
    """Get shared agent instance."""
    return await _shared_resources.get_agent()


async def get_shared_backend():
    """Get shared backend client."""
    return await _shared_resources.get_backend_client()


async def get_shared_agent_websocket():
    """Get shared agent WebSocket connection."""
    return await _shared_resources.get_agent_websocket()


async def get_shared_backend_websocket():
    """Get shared backend WebSocket connection."""
    return await _shared_resources.get_backend_websocket()


async def get_shared_redis():
    """Get shared Redis connection."""
    return await _shared_resources.get_redis()


async def get_shared_database():
    """Get shared database connection."""
    return await _shared_resources.get_database()


async def cleanup_shared_resources():
    """Cleanup all shared resources."""
    await _shared_resources.cleanup()


async def check_services_health() -> Dict[str, Any]:
    """Check health of all required services."""
    results = {}
    
    # Check backend
    backend_health = await ServiceHealthChecker.check_backend(config.backend_url)
    results["backend"] = backend_health
    
    # Check Redis
    if config.redis_url:
        redis_health = await ServiceHealthChecker.check_redis(config.redis_url)
        results["redis"] = redis_health
    
    # Check database
    if config.database_url:
        db_health = await ServiceHealthChecker.check_database(config.database_url)
        results["database"] = db_health
    
    return results

