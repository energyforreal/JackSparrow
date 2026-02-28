"""
Unified WebSocket Manager - Simplified Communication Layer.

Consolidates all WebSocket communication into a single channel with standardized
message formats and consistent serialization.
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Any, Optional
import json
import asyncio
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
import structlog

from backend.core.redis import get_redis
from backend.core.config import settings
from backend.services.time_service import time_service

logger = structlog.get_logger()


class UnifiedMessage:
    """Standardized message format for all WebSocket communications."""
    
    def __init__(
        self,
        type: str,
        payload: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        correlation_id: Optional[str] = None
    ):
        self.type = type
        self.payload = payload
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.correlation_id = correlation_id or str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with consistent serialization."""
        return {
            "type": self.type,
            "payload": self._serialize_payload(self.payload),
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "server_time_ms": int(self.timestamp.timestamp() * 1000)
        }
    
    def _serialize_payload(self, payload: Any) -> Any:
        """Recursively serialize payload with consistent type handling."""
        if isinstance(payload, dict):
            return {k: self._serialize_payload(v) for k, v in payload.items()}
        elif isinstance(payload, list):
            return [self._serialize_payload(item) for item in payload]
        elif isinstance(payload, Decimal):
            # Consistent Decimal handling: always convert to float
            return float(payload)
        elif isinstance(payload, (datetime, date)):
            return payload.isoformat()
        else:
            return payload


class UnifiedWebSocketManager:
    """Simplified WebSocket manager with unified communication."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.connection_metadata: Dict[WebSocket, Dict[str, Any]] = {}
        self._instance_id = str(uuid.uuid4())[:8]
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_metadata[websocket] = {
            "connected_at": datetime.now(timezone.utc),
            "connection_id": str(uuid.uuid4())
        }
        
        logger.info(
            "unified_websocket_connected",
            connection_id=self.connection_metadata[websocket]["connection_id"],
            total_connections=len(self.active_connections)
        )
        
        # Send welcome message with current system state
        await self._send_welcome_message(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Disconnect WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            connection_id = self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            
            if websocket in self.connection_metadata:
                del self.connection_metadata[websocket]
            
            logger.info(
                "unified_websocket_disconnected",
                connection_id=connection_id,
                total_connections=len(self.active_connections)
            )
    
    async def send_message(self, websocket: WebSocket, message: UnifiedMessage):
        """Send message to specific WebSocket connection."""
        try:
            message_dict = message.to_dict()
            await websocket.send_json(message_dict)
            
            connection_id = self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            logger.debug(
                "unified_websocket_message_sent",
                connection_id=connection_id,
                message_type=message.type,
                correlation_id=message.correlation_id
            )
        except Exception as e:
            logger.error(
                "unified_websocket_send_error",
                error=str(e),
                connection_id=self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            )
            await self.disconnect(websocket)
    
    async def broadcast(self, message: UnifiedMessage):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            return
        
        message_dict = message.to_dict()
        disconnected = []
        sent_count = 0
        
        for websocket in self.active_connections:
            try:
                await websocket.send_json(message_dict)
                sent_count += 1
            except Exception as e:
                connection_id = self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
                logger.error(
                    "unified_websocket_broadcast_error",
                    error=str(e),
                    connection_id=connection_id
                )
                disconnected.append(websocket)
        
        logger.debug(
            "unified_websocket_broadcast_completed",
            message_type=message.type,
            correlation_id=message.correlation_id,
            sent_count=sent_count,
            total_connections=len(self.active_connections),
            failed_connections=len(disconnected)
        )
        
        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)
    
    async def handle_client(self, websocket: WebSocket):
        """Handle WebSocket client messages."""
        try:
            while True:
                data = await websocket.receive_json()
                action = data.get("action")
                
                if action == "get_state":
                    await self._send_system_state(websocket)
                elif action == "subscribe":
                    # No subscription needed - all clients receive all messages
                    await self.send_message(
                        websocket,
                        UnifiedMessage("subscription_confirmed", {"channels": ["all"]})
                    )
                else:
                    logger.warning(
                        "unified_websocket_unknown_action",
                        action=action,
                        connection_id=self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
                    )
                    
        except WebSocketDisconnect:
            await self.disconnect(websocket)
        except Exception as e:
            connection_id = self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            logger.error(
                "unified_websocket_client_handler_error",
                error=str(e),
                connection_id=connection_id
            )
            await self.disconnect(websocket)
    
    async def _send_welcome_message(self, websocket: WebSocket):
        """Send welcome message with current system state."""
        try:
            welcome_data = {
                "connection_id": self.connection_metadata[websocket]["connection_id"],
                "server_time": datetime.now(timezone.utc).isoformat(),
                "instance_id": self._instance_id,
                "message": "Connected to unified WebSocket"
            }
            
            welcome_message = UnifiedMessage("welcome", welcome_data)
            await self.send_message(websocket, welcome_message)
            
            # Send current system state
            await self._send_system_state(websocket)
            
        except Exception as e:
            logger.error(
                "unified_websocket_welcome_error",
                error=str(e),
                connection_id=self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            )
    
    async def _send_system_state(self, websocket: WebSocket):
        """Send current system state to client."""
        try:
            # Get system health
            from backend.api.routes.health import get_health_status
            health_data = await get_health_status()
            
            # Get agent state
            from backend.services.agent_service import agent_service
            agent_state = await agent_service.get_current_state()
            
            state_data = {
                "health": health_data,
                "agent_state": agent_state,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            state_message = UnifiedMessage("system_state", state_data)
            await self.send_message(websocket, state_message)
            
        except Exception as e:
            logger.error(
                "unified_websocket_state_error",
                error=str(e),
                connection_id=self.connection_metadata.get(websocket, {}).get("connection_id", "unknown")
            )


# Global unified WebSocket manager instance
unified_websocket_manager = UnifiedWebSocketManager()