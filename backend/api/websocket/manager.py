"""
WebSocket connection manager.

Manages WebSocket connections and broadcasts real-time updates.
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set, Any
import json
import asyncio
import uuid

from backend.core.redis import get_redis


class WebSocketManager:
    """WebSocket connection manager."""
    
    def __init__(self):
        """Initialize WebSocket manager."""
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        self._redis_subscriber = None
        self._redis_task = None
    
    async def initialize(self):
        """Initialize Redis subscription for broadcasting."""
        try:
            redis = await get_redis()
            # Set up Redis subscription if needed
            # For now, we'll use direct broadcasting
            pass
        except Exception as e:
            print(f"WebSocket manager initialization warning: {e}")
    
    async def cleanup(self):
        """Cleanup WebSocket manager."""
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        print(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    async def disconnect(self, websocket: WebSocket):
        """Disconnect WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        print(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
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
            print(f"Error sending personal message: {e}")
            await self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """Broadcast message to all connected clients (optionally filtered by channel)."""
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
                print(f"Error broadcasting to client: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)
    
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
            print(f"WebSocket error: {e}")
            await self.disconnect(websocket)


# Global WebSocket manager instance
websocket_manager = WebSocketManager()

