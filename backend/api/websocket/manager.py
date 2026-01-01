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
from datetime import datetime, date, timezone
from decimal import Decimal
import structlog

from backend.core.redis import get_redis
from backend.core.config import settings
from backend.services.time_service import time_service
import redis.asyncio as aioredis

logger = structlog.get_logger()


def _json_default_encoder(obj: Any):
    """JSON encoder for WebSocket payloads.
    
    Ensures all messages are safe for json.dumps / send_json by converting:
    - datetime/date → ISO 8601 strings
    - Decimal → float
    - all other unsupported types → string representation
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _sanitize_for_json(value: Any) -> Any:
    """Recursively convert complex types to JSON-serializable primitives."""
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, (datetime, date, Decimal)):
        return _json_default_encoder(value)
    # Let json handle primitives (str, int, float, bool, None) and other simple types
    return value


class WebSocketManager:
    """WebSocket connection manager."""
    
    def __init__(self):
        """Initialize WebSocket manager."""
        self.active_connections: List[WebSocket] = []
        self.agent_connections: List[WebSocket] = []  # Separate pool for agent connections
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        self._redis_subscriber = None
        self._redis_task = None
        self._time_sync_task = None
        self._health_sync_task = None
        self._agent_state_sync_task = None
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
            
            # Start periodic health update task
            self._health_sync_task = asyncio.create_task(self._health_sync_loop())
            
            # Start periodic agent state update task
            self._agent_state_sync_task = asyncio.create_task(self._agent_state_sync_loop())
            
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
        
        if self._health_sync_task:
            self._health_sync_task.cancel()
            try:
                await self._health_sync_task
            except asyncio.CancelledError:
                pass
        
        if self._agent_state_sync_task:
            self._agent_state_sync_task.cancel()
            try:
                await self._agent_state_sync_task
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
        self._health_sync_task = None
        self._agent_state_sync_task = None
    
    async def connect(self, websocket: WebSocket, is_agent: bool = False):
        """Accept new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            is_agent: If True, add to agent_connections pool instead of active_connections
        """
        await websocket.accept()
        if is_agent:
            self.agent_connections.append(websocket)
            logger.info(
                "websocket_agent_connected",
                total_agent_connections=len(self.agent_connections),
                total_frontend_connections=len(self.active_connections)
            )
        else:
            self.active_connections.append(websocket)
            self.subscriptions[websocket] = set()
            logger.info(
                "websocket_connected",
                total_connections=len(self.active_connections)
            )
            
            # Send initial agent state immediately
            try:
                from backend.services.agent_service import agent_service
                current_state = await agent_service.get_current_state()
                if current_state:
                    state_data = {
                        "state": current_state.get("state", "UNKNOWN"),
                        "timestamp": current_state.get("timestamp", datetime.now(timezone.utc)).isoformat() if isinstance(current_state.get("timestamp"), datetime) else current_state.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        "reason": current_state.get("reason", "")
                    }
                    await self.send_personal_message(websocket, {
                        "type": "agent_state",
                        "data": state_data
                    })
                    logger.debug(
                        "websocket_initial_agent_state_sent",
                        state=state_data.get("state")
                    )
            except Exception as e:
                logger.debug(
                    "websocket_initial_agent_state_send_failed",
                    error=str(e),
                    message="Failed to send initial agent state, will be sent on next sync"
                )
    
    async def disconnect(self, websocket: WebSocket, is_agent: bool = False):
        """Disconnect WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            is_agent: If True, remove from agent_connections pool
        """
        if is_agent:
            if websocket in self.agent_connections:
                self.agent_connections.remove(websocket)
            logger.info(
                "websocket_agent_disconnected",
                total_agent_connections=len(self.agent_connections),
                total_frontend_connections=len(self.active_connections)
            )
        else:
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
            logger.info(
                "websocket_subscribed",
                service="backend",
                channels=channels,
                total_subscriptions=len(self.subscriptions[websocket]),
                total_connections=len(self.active_connections)
            )
            await self.send_personal_message(websocket, {
                "type": "subscribed",
                "channels": channels
            })
        else:
            logger.warning(
                "websocket_subscribe_failed",
                service="backend",
                channels=channels,
                message="WebSocket not in subscriptions dictionary"
            )
    
    async def unsubscribe(self, websocket: WebSocket, channels: List[str]):
        """Unsubscribe WebSocket from channels."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].difference_update(channels)
            logger.info(
                "websocket_unsubscribed",
                service="backend",
                channels=channels,
                remaining_subscriptions=len(self.subscriptions[websocket]),
                total_connections=len(self.active_connections)
            )
            await self.send_personal_message(websocket, {
                "type": "unsubscribed",
                "channels": channels
            })
        else:
            logger.warning(
                "websocket_unsubscribe_failed",
                service="backend",
                channels=channels,
                message="WebSocket not in subscriptions dictionary"
            )
    
    async def send_personal_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send message to specific WebSocket connection."""
        try:
            safe_message = _sanitize_for_json(message)
            await websocket.send_json(safe_message)
        except Exception as e:
            logger.error(
                "websocket_send_personal_message_failed",
                error=str(e),
                exc_info=True
            )
            await self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """Broadcast message to all connected clients (optionally filtered by channel)."""
        # WS MANAGER: Validate message is not None
        if message is None:
            logger.warning("WS MANAGER: Ignoring empty broadcast")
            return
        
        # Add server timestamp to message
        if "server_timestamp" not in message:
            time_info = time_service.get_time_info()
            message["server_timestamp"] = time_info["server_time"]
            message["server_timestamp_ms"] = time_info["timestamp_ms"]
        
        # Sanitize message for JSON serialization (for both Redis and direct WebSocket)
        safe_message = _sanitize_for_json(message)
        
        # Add metadata to message for Redis pub/sub
        broadcast_message = {
            "instance_id": self._instance_id,
            "channel": channel,
            "message": safe_message,
            "timestamp": time.time()
        }
        
        # Publish to Redis for multi-instance broadcasting
        if self._redis_publisher:
            try:
                await self._redis_publisher.publish(
                    self._redis_channel,
                    json.dumps(broadcast_message, default=_json_default_encoder)
                )
            except Exception as e:
                logger.warning(
                    "websocket_redis_publish_failed",
                    channel=channel,
                    error=str(e),
                    message="Falling back to local broadcast only"
                )
        
        # Also broadcast locally
        await self._broadcast_local(safe_message, channel)
    
    async def _broadcast_local(self, message: Dict[str, Any], channel: str = None):
        """Broadcast message to local WebSocket connections only."""
        if not self.active_connections:
            return
        
        disconnected = []
        sent_count = 0
        filtered_count = 0
        
        for websocket in self.active_connections:
            try:
                # If channel specified AND client has subscriptions, filter by channel
                # Otherwise, send to all clients (for backward compatibility and default behavior)
                if channel and websocket in self.subscriptions and self.subscriptions[websocket]:
                    if channel not in self.subscriptions[websocket]:
                        filtered_count += 1
                        continue
                
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.error(
                    "websocket_broadcast_failed",
                    channel=channel,
                    error=str(e),
                    exc_info=True
                )
                disconnected.append(websocket)
        
        # Log broadcast statistics at DEBUG level
        logger.debug(
            "websocket_broadcast_local",
            service="backend",
            channel=channel,
            message_type=message.get("type"),
            sent_count=sent_count,
            filtered_count=filtered_count,
            total_connections=len(self.active_connections),
            disconnected_count=len(disconnected)
        )
        
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
                    # Send current WebSocket connection state
                    await self.send_personal_message(websocket, {
                        "type": "state",
                        "data": {
                            "connections": len(self.active_connections),
                            "subscribed_channels": list(self.subscriptions.get(websocket, set()))
                        }
                    })
                
                elif action == "get_agent_state":
                    # Send current agent state on demand
                    try:
                        from backend.services.agent_service import agent_service
                        current_state = await agent_service.get_current_state()
                        if current_state:
                            state_data = {
                                "state": current_state.get("state", "UNKNOWN"),
                                "timestamp": current_state.get("timestamp", datetime.now(timezone.utc)).isoformat() if isinstance(current_state.get("timestamp"), datetime) else current_state.get("timestamp", datetime.now(timezone.utc).isoformat()),
                                "reason": current_state.get("reason", "")
                            }
                            await self.send_personal_message(websocket, {
                                "type": "agent_state",
                                "data": state_data
                            })
                        else:
                            await self.send_personal_message(websocket, {
                                "type": "agent_state",
                                "data": {
                                    "state": "UNKNOWN",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "reason": "Agent state unavailable"
                                }
                            })
                    except Exception as e:
                        logger.warning(
                            "websocket_get_agent_state_error",
                            error=str(e)
                        )
                        await self.send_personal_message(websocket, {
                            "type": "error",
                            "message": f"Failed to get agent state: {str(e)}"
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
    
    async def handle_agent_client(self, websocket: WebSocket):
        """Handle WebSocket messages from agent.
        
        Agent sends events directly via WebSocket, which we then broadcast
        to frontend clients. This bypasses Redis Streams for lower latency.
        """
        try:
            while True:
                # Receive message from agent
                data = await websocket.receive_json()
                
                msg_type = data.get("type")
                
                if msg_type == "agent_event":
                    # Agent is sending an event - route it to frontend clients
                    event_type = data.get("event_type")
                    payload = data.get("payload", {})
                    
                    logger.debug(
                        "websocket_agent_event_received",
                        event_type=event_type,
                        event_id=data.get("event_id")
                    )
                    
                    # Route event to appropriate handler (same as Redis Stream subscriber)
                    from backend.services.agent_event_subscriber import agent_event_subscriber
                    await agent_event_subscriber._handle_event(event_type, payload)
                    
                    # Also send pong/acknowledgment if needed
                    if data.get("request_ack"):
                        await self.send_personal_message(websocket, {
                            "type": "ack",
                            "event_id": data.get("event_id"),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                
                elif msg_type == "ping":
                    # Respond to agent ping
                    await self.send_personal_message(websocket, {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                
                else:
                    logger.warning(
                        "websocket_agent_unknown_message_type",
                        msg_type=msg_type
                    )
        
        except WebSocketDisconnect:
            await self.disconnect(websocket, is_agent=True)
        except Exception as e:
            logger.error(
                "websocket_agent_client_handler_error",
                error=str(e),
                exc_info=True
            )
            await self.disconnect(websocket, is_agent=True)
    
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
    
    async def _health_sync_loop(self):
        """Background task to send periodic health update messages."""
        try:
            while True:
                await asyncio.sleep(60)  # Send every 60 seconds
                
                if not self.active_connections:
                    continue
                
                try:
                    from backend.api.routes.health import (
                        check_database_health,
                        redis_health_check,
                        check_agent_health,
                        check_feature_server_health,
                        check_model_nodes_health,
                        check_delta_exchange_health,
                        check_reasoning_engine_health
                    )
                    from backend.core.database import AsyncSessionLocal
                    from backend.api.models.responses import HealthServiceStatus
                    from datetime import datetime
                    
                    async with AsyncSessionLocal() as db:
                        degradation_reasons = []
                        health_scores = []
                        
                        # Check database
                        db_health = await check_database_health(db)
                        if db_health.status == "up":
                            health_scores.append(0.05)
                        else:
                            degradation_reasons.append("Database is down")
                            health_scores.append(0.0)
                        
                        # Check Redis
                        redis_health_dict = await redis_health_check()
                        redis_health = HealthServiceStatus(**redis_health_dict)
                        if redis_health.status == "up":
                            health_scores.append(0.05)
                        else:
                            degradation_reasons.append("Redis is down")
                            health_scores.append(0.0)
                        
                        # Check agent
                        agent_health = await check_agent_health()
                        agent_weight = 0.15
                        if agent_health.status == "up":
                            health_scores.append(agent_weight)
                            agent_state = agent_health.details.get("state") if agent_health.details else None
                        else:
                            degradation_reasons.append("Agent service is down")
                            health_scores.append(0.0)
                            agent_state = None
                        
                        # Check feature server
                        feature_health = await check_feature_server_health()
                        feature_weight = 0.20
                        if feature_health.status == "up":
                            health_scores.append(feature_weight)
                        elif feature_health.status != "unknown":
                            degradation_reasons.append("Feature server is down")
                            health_scores.append(0.0)
                        else:
                            health_scores.append(0.0)
                        
                        # Check model nodes
                        model_health = await check_model_nodes_health()
                        model_weight = 0.25
                        if model_health.status == "up":
                            if model_health.details:
                                healthy_count = model_health.details.get("healthy_models", 0)
                                total_count = model_health.details.get("total_models", 1)
                                if healthy_count < 3 and total_count > 0:
                                    degradation_reasons.append(f"Only {healthy_count}/{total_count} models are healthy")
                                health_scores.append(model_weight * (healthy_count / max(total_count, 1)))
                            else:
                                health_scores.append(model_weight)
                        elif model_health.status != "unknown":
                            degradation_reasons.append("No model nodes are healthy")
                            health_scores.append(0.0)
                        else:
                            health_scores.append(0.0)
                        
                        # Check Delta Exchange
                        delta_health = await check_delta_exchange_health()
                        delta_weight = 0.15
                        if delta_health.status == "up":
                            health_scores.append(delta_weight)
                        elif delta_health.status != "unknown":
                            degradation_reasons.append("Delta Exchange API is down")
                            health_scores.append(0.0)
                        else:
                            health_scores.append(0.0)
                        
                        # Check reasoning engine
                        reasoning_health = await check_reasoning_engine_health()
                        reasoning_weight = 0.15
                        if reasoning_health.status == "up":
                            health_scores.append(reasoning_weight)
                        elif reasoning_health.status != "unknown":
                            degradation_reasons.append("Reasoning engine is down")
                            health_scores.append(0.0)
                        else:
                            health_scores.append(0.0)
                        
                        # Calculate overall health score
                        health_score = sum(health_scores)
                        
                        # Determine status
                        if health_score >= 0.9:
                            status = "healthy"
                        elif health_score >= 0.6:
                            status = "degraded"
                        else:
                            status = "unhealthy"
                        
                        # Standardize health_score to 0-100 range for WebSocket (API returns 0.0-1.0)
                        health_score_percent = round(health_score * 100, 1)
                        
                        health_data = {
                            "status": status,
                            "health_score": health_score_percent,  # 0-100 range for WebSocket
                            "score": health_score_percent,  # Alias for backward compatibility
                            "services": {
                                "database": db_health.dict(),
                                "redis": redis_health.dict(),
                                "agent": agent_health.dict(),
                                "feature_server": feature_health.dict(),
                                "model_nodes": model_health.dict(),
                                "delta_exchange": delta_health.dict(),
                                "reasoning_engine": reasoning_health.dict()
                            },
                            "agent_state": agent_state,
                            "degradation_reasons": degradation_reasons,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                        
                        health_message = {
                            "type": "health_update",
                            "data": health_data
                        }
                        
                        await self.broadcast(health_message, channel="health")
                        
                except Exception as health_error:
                    logger.warning(
                        "websocket_health_sync_error",
                        error=str(health_error),
                        message="Failed to broadcast health update, will retry on next cycle"
                    )
                
        except asyncio.CancelledError:
            logger.info("websocket_health_sync_loop_cancelled")
            raise
        except Exception as e:
            logger.error(
                "websocket_health_sync_loop_error",
                error=str(e),
                exc_info=True
            )
    
    async def _agent_state_sync_loop(self):
        """Background task to send periodic agent state updates."""
        try:
            while True:
                await asyncio.sleep(30)  # Send every 30 seconds
                
                if not self.active_connections:
                    continue
                
                try:
                    from backend.services.agent_service import agent_service
                    current_state = await agent_service.get_current_state()
                    
                    if current_state:
                        state_data = {
                            "state": current_state.get("state", "UNKNOWN"),
                            "timestamp": current_state.get("timestamp", datetime.now(timezone.utc)).isoformat() if isinstance(current_state.get("timestamp"), datetime) else current_state.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "reason": current_state.get("reason", "")
                        }
                        
                        state_message = {
                            "type": "agent_state",
                            "data": state_data
                        }
                        
                        await self.broadcast(state_message, channel="agent_state")
                        
                        logger.debug(
                            "websocket_agent_state_sync_broadcast",
                            state=state_data.get("state"),
                            connections=len(self.active_connections)
                        )
                except Exception as e:
                    logger.warning(
                        "websocket_agent_state_sync_error",
                        error=str(e),
                        message="Failed to sync agent state, will retry on next cycle"
                    )
                
        except asyncio.CancelledError:
            logger.info("websocket_agent_state_sync_loop_cancelled")
            raise
        except Exception as e:
            logger.error(
                "websocket_agent_state_sync_loop_error",
                error=str(e),
                exc_info=True
            )


# Global WebSocket manager instance
websocket_manager = WebSocketManager()

