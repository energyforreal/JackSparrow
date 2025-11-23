"""
WebSocket connection manager.

Manages WebSocket connections and broadcasts real-time updates.
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set, Any
import json
import asyncio
import uuid
import time
import structlog

from backend.core.redis import get_redis
from backend.core.config import settings
from backend.services.time_service import time_service
import redis.asyncio as aioredis

logger = structlog.get_logger()


class WebSocketManager:
    """WebSocket connection manager."""
    
    def __init__(self):
        """Initialize WebSocket manager."""
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        self._redis_subscriber = None
        self._redis_task = None
        self._time_sync_task = None
        self._redis_publisher = None
        self._redis_channel = "websocket:broadcast"
        self._instance_id = str(uuid.uuid4())[:8]  # Unique instance identifier
    
    async def initialize(self):
        """Initialize Redis subscription for broadcasting."""
        try:
            # Check if Redis is available
            redis_check = await get_redis()
            if redis_check is None:
                logger.warning(
                    "websocket_manager_redis_unavailable",
                    message="Redis unavailable, WebSocket pub/sub disabled"
                )
                return
            
            # Create separate Redis connections for pub/sub (required by aioredis)
            # Publisher uses shared connection
            self._redis_publisher = await get_redis()
            
            # Create dedicated subscriber connection (pub/sub requires separate connection)
            self._redis_subscriber = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
            )
            
            # Verify subscriber connection
            await self._redis_subscriber.ping()
            
            # Start background task to listen for Redis messages
            self._redis_task = asyncio.create_task(self._redis_listener())
            
            # Start periodic time sync task
            self._time_sync_task = asyncio.create_task(self._time_sync_loop())
            
            logger.info(
                "websocket_manager_initialized",
                instance_id=self._instance_id,
                redis_channel=self._redis_channel
            )
        except Exception as e:
            logger.warning(
                "websocket_manager_init_warning",
                error=str(e),
                exc_info=True,
                message="WebSocket pub/sub disabled, using local broadcasting only"
            )
            # Clean up on failure
            if self._redis_subscriber:
                try:
                    await self._redis_subscriber.close()
                except Exception:
                    pass
                self._redis_subscriber = None
    
    async def cleanup(self):
        """Cleanup WebSocket manager."""
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        
        if self._time_sync_task:
            self._time_sync_task.cancel()
            try:
                await self._time_sync_task
            except asyncio.CancelledError:
                pass
        
        if self._redis_subscriber:
            try:
                await self._redis_subscriber.close()
            except Exception as e:
                logger.warning(
                    "websocket_manager_cleanup_error",
                    error=str(e)
                )
        
        self._redis_subscriber = None
        self._redis_publisher = None
        self._redis_task = None
        self._time_sync_task = None
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        logger.info(
            "websocket_connected",
            total_connections=len(self.active_connections)
        )
    
    async def disconnect(self, websocket: WebSocket):
        """Disconnect WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        logger.info(
            "websocket_disconnected",
            total_connections=len(self.active_connections)
        )
    
    async def subscribe(self, websocket: WebSocket, channels: List[str]):
        """Subscribe WebSocket to channels."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(channels)
            await self.send_personal_message(websocket, {
                "type": "subscribed",
                "channels": channels
            })
    
    async def unsubscribe(self, websocket: WebSocket, channels: List[str]):
        """Unsubscribe WebSocket from channels."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].difference_update(channels)
            await self.send_personal_message(websocket, {
                "type": "unsubscribed",
                "channels": channels
            })
    
    async def send_personal_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send message to specific WebSocket connection."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(
                "websocket_send_personal_message_failed",
                error=str(e),
                exc_info=True
            )
            await self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """Broadcast message to all connected clients (optionally filtered by channel)."""
        # Add server timestamp to message
        if "server_timestamp" not in message:
            time_info = time_service.get_time_info()
            message["server_timestamp"] = time_info["server_time"]
            message["server_timestamp_ms"] = time_info["timestamp_ms"]
        
        # Add metadata to message for Redis pub/sub
        broadcast_message = {
            "instance_id": self._instance_id,
            "channel": channel,
            "message": message,
            "timestamp": time.time()
        }
        
        # Publish to Redis for multi-instance broadcasting
        if self._redis_publisher:
            try:
                await self._redis_publisher.publish(
                    self._redis_channel,
                    json.dumps(broadcast_message)
                )
            except Exception as e:
                logger.warning(
                    "websocket_redis_publish_failed",
                    channel=channel,
                    error=str(e),
                    message="Falling back to local broadcast only"
                )
        
        # Also broadcast locally
        await self._broadcast_local(message, channel)
    
    async def _broadcast_local(self, message: Dict[str, Any], channel: str = None):
        """Broadcast message to local WebSocket connections only."""
        if not self.active_connections:
            return
        
        disconnected = []
        for websocket in self.active_connections:
            try:
                # If channel specified, only send to subscribed clients
                if channel and websocket in self.subscriptions:
                    if channel not in self.subscriptions[websocket]:
                        continue
                
                await websocket.send_json(message)
            except Exception as e:
                logger.error(
                    "websocket_broadcast_failed",
                    channel=channel,
                    error=str(e),
                    exc_info=True
                )
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)
    
    async def _redis_listener(self):
        """Background task to listen for Redis pub/sub messages."""
        if not self._redis_subscriber:
            return
        
        try:
            # Create pubsub object
            pubsub = self._redis_subscriber.pubsub()
            await pubsub.subscribe(self._redis_channel)
            
            logger.info(
                "websocket_redis_listener_started",
                channel=self._redis_channel
            )
            
            while True:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0
                    )
                    
                    if message and message.get("type") == "message":
                        try:
                            data = json.loads(message.get("data", "{}"))
                            instance_id = data.get("instance_id")
                            channel = data.get("channel")
                            message_data = data.get("message", {})
                            
                            # Skip messages from this instance (already broadcast locally)
                            if instance_id != self._instance_id:
                                # Broadcast to local connections
                                await self._broadcast_local(message_data, channel)
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning(
                                "websocket_redis_message_decode_error",
                                error=str(e)
                            )
                    
                except asyncio.TimeoutError:
                    # Timeout is expected, continue listening
                    continue
                except Exception as e:
                    logger.error(
                        "websocket_redis_listener_error",
                        error=str(e),
                        exc_info=True
                    )
                    # Wait before retrying
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            logger.info("websocket_redis_listener_cancelled")
            if self._redis_subscriber:
                try:
                    pubsub = self._redis_subscriber.pubsub()
                    await pubsub.unsubscribe(self._redis_channel)
                    await pubsub.close()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.error(
                "websocket_redis_listener_fatal_error",
                error=str(e),
                exc_info=True
            )
    
    async def handle_client(self, websocket: WebSocket):
        """Handle WebSocket client messages."""
        try:
            while True:
                # Receive message
                data = await websocket.receive_json()
                
                action = data.get("action")
                
                if action == "subscribe":
                    channels = data.get("channels", [])
                    await self.subscribe(websocket, channels)
                
                elif action == "unsubscribe":
                    channels = data.get("channels", [])
                    await self.unsubscribe(websocket, channels)
                
                elif action == "get_state":
                    # Send current state
                    await self.send_personal_message(websocket, {
                        "type": "state",
                        "data": {
                            "connections": len(self.active_connections),
                            "subscribed_channels": list(self.subscriptions.get(websocket, set()))
                        }
                    })
                
                else:
                    await self.send_personal_message(websocket, {
                        "type": "error",
                        "message": f"Unknown action: {action}"
                    })
        
        except WebSocketDisconnect:
            await self.disconnect(websocket)
        except Exception as e:
            logger.error(
                "websocket_client_handler_error",
                error=str(e),
                exc_info=True
            )
            await self.disconnect(websocket)
    
    async def _time_sync_loop(self):
        """Background task to send periodic time sync messages."""
        try:
            while True:
                await asyncio.sleep(30)  # Send every 30 seconds
                
                if not self.active_connections:
                    continue
                
                time_info = time_service.get_time_info()
                sync_message = {
                    "type": "time_sync",
                    "data": time_info
                }
                
                await self.broadcast(sync_message, channel="time_sync")
                
        except asyncio.CancelledError:
            logger.info("websocket_time_sync_loop_cancelled")
            raise
        except Exception as e:
            logger.error(
                "websocket_time_sync_loop_error",
                error=str(e),
                exc_info=True
            )


# Global WebSocket manager instance
websocket_manager = WebSocketManager()

