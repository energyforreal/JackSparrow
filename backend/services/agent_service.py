"""
Agent service for communicating with the AI agent core.

Provides methods for interacting with the agent service via WebSocket (preferred)
or Redis queues (fallback).
"""

from typing import Optional, Dict, Any, List
import uuid
import asyncio
import time
import json
from datetime import datetime
import structlog

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    from websockets.exceptions import ConnectionClosed, WebSocketException
except Exception:
    websockets = None  # type: ignore
    WebSocketClientProtocol = object  # type: ignore
    ConnectionClosed = Exception  # type: ignore
    WebSocketException = Exception  # type: ignore

from backend.core.redis import enqueue_command, get_response
from backend.core.config import settings
from backend.core.logging import log_error_with_context

logger = structlog.get_logger()


class AgentService:
    """Service for communicating with agent."""
    
    def __init__(self):
        """Initialize agent service."""
        self.command_queue = settings.agent_command_queue
        self.websocket_url = settings.agent_websocket_url
        self.use_websocket = settings.use_agent_websocket
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._websocket_connected = False
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._initialization_attempted = False
        
        # Response mechanism uses Redis key-value store (response:{request_id})
        # Backend polls using get_response() which reads from key-value, not list queue
    
    async def _initialize_websocket(self):
        """Initialize WebSocket connection to agent."""
        if not websockets:
            return
        
        try:
            self._websocket = await websockets.connect(  # type: ignore[call-arg]
                self.websocket_url,
                ping_interval=30,
                ping_timeout=10,
            )
            self._websocket_connected = True
            
            logger.info(
                "agent_service_websocket_connected",
                service="backend",
                url=self.websocket_url
            )
            
            # Start receiving messages
            asyncio.create_task(self._websocket_receive_loop())
            
        except Exception as e:
            logger.warning(
                "agent_service_websocket_init_failed",
                service="backend",
                url=self.websocket_url,
                error=str(e),
                message="Falling back to Redis queue communication"
            )
            self._websocket_connected = False
    
    async def _websocket_receive_loop(self):
        """Receive messages from agent WebSocket."""
        if not self._websocket:
            return
        
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    request_id = data.get("request_id")
                    
                    if msg_type == "response" and request_id:
                        # Complete pending future
                        if request_id in self._pending_responses:
                            future = self._pending_responses.pop(request_id)
                            if not future.done():
                                future.set_result(data.get("data", data))
                    
                    elif msg_type == "error" and request_id:
                        # Complete with error
                        if request_id in self._pending_responses:
                            future = self._pending_responses.pop(request_id)
                            if not future.done():
                                future.set_exception(Exception(data.get("error", "Unknown error")))
                
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.warning(
                        "agent_service_websocket_receive_error",
                        service="backend",
                        error=str(e)
                    )
        
        except ConnectionClosed:
            self._websocket_connected = False
            logger.info(
                "agent_service_websocket_disconnected",
                service="backend"
            )
        except Exception as e:
            log_error_with_context(
                "agent_service_websocket_receive_fatal",
                error=e,
                component="agent_service",
                url=self.websocket_url
            )
            self._websocket_connected = False
    
    async def _send_command(
        self,
        command: str,
        parameters: Dict[str, Any] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Send command to agent and wait for response.
        
        Tries WebSocket first if available, falls back to Redis queue.
        """
        
        # Lazy initialization of WebSocket connection
        if self.use_websocket and websockets is not None and not self._initialization_attempted:
            self._initialization_attempted = True
            try:
                await self._initialize_websocket()
            except Exception as e:
                logger.debug(
                    "agent_service_websocket_lazy_init_failed",
                    service="backend",
                    error=str(e)
                )
        
        request_id = str(uuid.uuid4())
        
        # Try WebSocket first if available
        if self.use_websocket and self._websocket_connected and self._websocket:
            try:
                command_message = {
                    "type": "command",
                    "request_id": request_id,
                    "command": command,
                    "parameters": parameters or {},
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Create future for response
                future = asyncio.Future()
                self._pending_responses[request_id] = future
                
                # Send command
                await self._websocket.send(json.dumps(command_message, default=str))
                
                # Wait for response with timeout
                try:
                    response = await asyncio.wait_for(future, timeout=timeout)
                    return response
                except asyncio.TimeoutError:
                    self._pending_responses.pop(request_id, None)
                    logger.warning(
                        "agent_service_websocket_timeout",
                        service="backend",
                        request_id=request_id,
                        command=command,
                        timeout=timeout
                    )
                    # Fall through to Redis fallback
                except Exception as e:
                    self._pending_responses.pop(request_id, None)
                    logger.warning(
                        "agent_service_websocket_error",
                        service="backend",
                        request_id=request_id,
                        command=command,
                        error=str(e)
                    )
                    # Fall through to Redis fallback
            
            except Exception as e:
                logger.warning(
                    "agent_service_websocket_send_failed",
                    service="backend",
                    request_id=request_id,
                    command=command,
                    error=str(e),
                    message="Falling back to Redis queue"
                )
                # Fall through to Redis fallback
        
        # Fallback to Redis queue
        message = {
            "request_id": request_id,
            "command": command,
            "parameters": parameters or {},
            "timestamp": time.time()
        }
        
        # Send command via Redis
        success = await enqueue_command(message, self.command_queue)
        if not success:
            return None
        
        return await self._wait_for_response(request_id, timeout)
    
    async def get_prediction(
        self,
        symbol: str = "BTCUSD",
        context: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Get prediction from agent."""
        
        response = await self._send_command(
            "predict",
            parameters={
                "symbol": symbol,
                "context": context or {}
            },
            timeout=60  # Predictions may take longer
        )
        
        return response

    async def _wait_for_response(self, request_id: str, timeout: int) -> Optional[Dict[str, Any]]:
        """Poll Redis for the agent response until timeout."""
        deadline = time.time() + timeout
        poll_interval = 0.2
        while time.time() < deadline:
            response = await get_response(request_id)
            if response:
                return response
            await asyncio.sleep(poll_interval)
        return None
    
    async def execute_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Execute trade via agent."""
        
        response = await self._send_command(
            "execute_trade",
            parameters={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            },
            timeout=30
        )
        
        return response
    
    async def get_current_state(self) -> Optional[Dict[str, Any]]:
        """Get current agent state (lightweight, for periodic updates).
        
        Returns:
            Dict with state, timestamp, and reason, or None if unavailable
        """
        try:
            # Use get_agent_status which queries via Redis or WebSocket
            # This is the most reliable method as it uses existing command infrastructure
            status = await self.get_agent_status()
            if status:
                return {
                    "state": status.get("state", "UNKNOWN"),
                    "timestamp": status.get("last_update", datetime.utcnow()),
                    "reason": status.get("message", "")
                }
            
            return None
        except Exception as e:
            logger.debug(
                "get_current_state_error",
                error=str(e),
                message="Failed to get current agent state"
            )
            return None
    
    async def get_agent_status(self) -> Optional[Dict[str, Any]]:
        """Get agent status."""
        
        start_time = time.time()
        response = await self._send_command(
            "get_status",
            parameters={},
            timeout=5
        )
        latency_ms = (time.time() - start_time) * 1000
        
        now = datetime.utcnow()
        
        if not response:
            return {
                "available": False,
                "state": "UNKNOWN",
                "last_update": now,
                "active_symbols": [],
                "model_count": 0,
                "health_status": "unavailable",
                "message": "Agent service unavailable",
                "latency_ms": round(latency_ms, 2)
            }
        
        data = response.get("data", {})
        health = data.get("health", {})
        detailed_health = data.get("detailed_health", {})
        
        # Extract model registry info from health or detailed_health
        model_registry = health.get("model_registry", {})
        if not model_registry and detailed_health:
            model_nodes = detailed_health.get("model_nodes", {})
            model_registry = {
                "total_models": model_nodes.get("total_models", 0),
                "healthy_models": model_nodes.get("healthy_models", 0)
            }
        
        # Extract available flag from agent response (agent includes it in data)
        # If not present, assume True since we got a successful response
        available = data.get("available", True)
        
        # Build response with detailed health information
        status_response = {
            "available": available,  # Use agent's reported availability
            "state": data.get("state", "UNKNOWN"),
            "last_update": now,
            "active_symbols": data.get("active_symbols", []),
            "model_count": model_registry.get("total_models", 0),
            "health_status": health.get("overall_status", "unknown"),
            "message": data.get("message"),
            "latency_ms": round(latency_ms, 2)
        }
        
        # Add detailed health information if available
        if detailed_health:
            status_response.update({
                "feature_server": detailed_health.get("feature_server", {}),
                "model_nodes": detailed_health.get("model_nodes", {}),
                "delta_exchange": detailed_health.get("delta_exchange", {}),
                "reasoning_engine": detailed_health.get("reasoning_engine", {})
            })
        
        return status_response
    
    async def control_agent(
        self,
        action: str,
        parameters: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Control agent (start, stop, pause, resume, restart)."""
        
        response = await self._send_command(
            "control",
            parameters={
                "action": action,
                "parameters": parameters or {}
            },
            timeout=10
        )
        
        return response


# Global agent service instance
agent_service = AgentService()

