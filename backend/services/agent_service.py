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
from datetime import datetime, timezone
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
from backend.core.communication_logger import log_agent_command

logger = structlog.get_logger()


class AgentService:
    """Service for communicating with agent."""
    
    def __init__(self):
        """Initialize agent service."""
        self.command_queue = settings.agent_command_queue
        self.websocket_url = settings.agent_websocket_url
        # Prefer WebSocket command path when enabled; Redis remains fallback.
        self.use_websocket = settings.use_agent_websocket
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._websocket_connected = False
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._initialization_attempted = False
        # Prevent concurrent connect attempts and stale socket reuse.
        self._ws_init_lock: asyncio.Lock = asyncio.Lock()
        self._ws_close_lock: asyncio.Lock = asyncio.Lock()
        self._ws_receive_task: Optional[asyncio.Task] = None
        # WebSocket reconnect throttling to avoid tight retry loops.
        self._last_ws_attempt: float = 0.0
        self._ws_attempt_backoff_seconds: float = 5.0
        
        # Response mechanism uses Redis key-value store (response:{request_id})
        # Backend polls using get_response() which reads from key-value, not list queue

        # Small TTL cache to avoid bursty get_agent_status fan-out during health sync.
        self._agent_status_fetch_lock: asyncio.Lock = asyncio.Lock()
        self._agent_status_cache: Optional[Dict[str, Any]] = None
        self._agent_status_cache_updated_at: float = 0.0
        self._agent_status_cache_ttl_seconds: float = 2.0
    
    async def _initialize_websocket(self):
        """Initialize WebSocket connection to agent."""
        if not websockets:
            return

        async with self._ws_init_lock:
            # If already connected, don't create a second socket.
            if self._websocket_connected and self._websocket is not None:
                return
        
            try:
                # Use a more forgiving ping timeout: the agent may take longer to
                # compute command responses (health/status can be multi-step).
                self._websocket = await websockets.connect(  # type: ignore[call-arg]
                    self.websocket_url,
                    ping_interval=30,
                    ping_timeout=30,
                )
                self._websocket_connected = True
                
                logger.info(
                    "agent_service_websocket_connected",
                    service="backend",
                    url=self.websocket_url
                )
                
                # Start receiving messages (only once per socket instance).
                if self._ws_receive_task is None or self._ws_receive_task.done():
                    self._ws_receive_task = asyncio.create_task(self._websocket_receive_loop())
                
            except Exception as e:
                logger.warning(
                    "agent_service_websocket_init_failed",
                    service="backend",
                    url=self.websocket_url,
                    error=str(e),
                    message="Falling back to Redis queue communication"
                )
                self._websocket_connected = False
                await self._schedule_reconnect()

    async def _teardown_websocket(self) -> None:
        """Close the current agent WebSocket cleanly (best-effort)."""
        if self._websocket is None:
            self._websocket_connected = False
            return

        async with self._ws_close_lock:
            ws = self._websocket
            self._websocket = None
            self._websocket_connected = False
            try:
                # Ensure teardown never stalls command traffic; close handshake
                # can hang when the peer is wedged or ping/pong is broken.
                await asyncio.wait_for(ws.close(), timeout=3.0)
            except Exception:
                # Best-effort shutdown; receive loop will exit on its own.
                pass
            # The receive loop is best-effort; cancel to avoid holding stale refs.
            if self._ws_receive_task is not None and not self._ws_receive_task.done():
                self._ws_receive_task.cancel()
            self._ws_receive_task = None

    async def _schedule_reconnect(self, delay: float = 2.0) -> None:
        """Schedule a background WebSocket reconnect loop."""
        if not self.use_websocket:
            return

        if self._reconnect_task and not self._reconnect_task.done():
            return

        async def _reconnect_loop() -> None:
            await asyncio.sleep(delay)
            while True:
                try:
                    # Stop if WebSocket usage is disabled or we already connected.
                    if not self.use_websocket:
                        return
                    if self._websocket_connected and self._websocket is not None:
                        return
                    # Throttle attempts a bit.
                    now = time.time()
                    if now - self._last_ws_attempt < self._ws_attempt_backoff_seconds:
                        await asyncio.sleep(1.0)
                        continue
                    self._last_ws_attempt = now
                    await self._initialize_websocket()
                    if self._websocket_connected and self._websocket is not None:
                        return
                except asyncio.CancelledError:
                    return
                except Exception:
                    # Best-effort reconnect: swallow and retry.
                    pass
                await asyncio.sleep(5.0)

        self._reconnect_task = asyncio.create_task(_reconnect_loop())
    
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
            # Ensure any in-flight commands waiting on this socket fail fast.
            for request_id, future in list(self._pending_responses.items()):
                if not future.done():
                    future.set_exception(Exception("WebSocket disconnected"))
                self._pending_responses.pop(request_id, None)
            await self._schedule_reconnect()
        except Exception as e:
            log_error_with_context(
                "agent_service_websocket_receive_fatal",
                error=e,
                component="agent_service",
                url=self.websocket_url
            )
            self._websocket_connected = False
            await self._schedule_reconnect()
    
    async def _send_command(
        self,
        command: str,
        parameters: Dict[str, Any] = None,
        timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Send command to agent and wait for response.

        Tries WebSocket first if available, falls back to Redis queue.
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()

        # Log outbound command request
        log_agent_command(
            direction="outbound",
            command=command,
            correlation_id=request_id,
            payload=parameters
        )

        # BACKEND -> AGENT (outbound command WebSocket to agent — not the same as agent -> backend /ws/agent)
        logger.info(
            "outbound_agent_command_ws_send",
            command=command,
            message="Sending command to agent (preferred path: outbound WS to AGENT_WS_URL)",
        )

        outbound_ws_active = False

        # Attempt WebSocket initialization if disconnected.
        if self.use_websocket and websockets is not None:
            if not self._websocket_connected or self._websocket is None:
                now = time.time()
                if now - self._last_ws_attempt >= self._ws_attempt_backoff_seconds:
                    self._last_ws_attempt = now
                    try:
                        await self._initialize_websocket()
                    except Exception as e:
                        logger.debug(
                            "agent_service_websocket_lazy_init_failed",
                            service="backend",
                            error=str(e)
                        )
        
        # Try outbound WebSocket first if available
        logger.debug(
            "outbound_agent_command_ws_check",
            use_websocket=self.use_websocket,
            connected=self._websocket_connected,
            has_socket=self._websocket is not None,
        )
        if self.use_websocket and self._websocket_connected and self._websocket:
            outbound_ws_active = True
            logger.info(
                "outbound_agent_command_ws_attempt",
                command=command,
                message="Using outbound WebSocket to agent for command delivery",
            )
            try:
                command_message = {
                    "type": "command",
                    "request_id": request_id,
                    "command": command,
                    "parameters": parameters or {},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Create future for response
                future = asyncio.Future()
                self._pending_responses[request_id] = future
                
                # Send command
                await self._websocket.send(json.dumps(command_message, default=str))
                
                # Wait for response with timeout
                try:
                    response = await asyncio.wait_for(future, timeout=timeout)

                    # Log successful response
                    latency_ms = (time.time() - start_time) * 1000
                    log_agent_command(
                        direction="inbound",
                        command=command,
                        correlation_id=request_id,
                        payload=response,
                        latency_ms=latency_ms
                    )

                    return response
                except asyncio.TimeoutError:
                    self._pending_responses.pop(request_id, None)

                    # Log timeout error
                    latency_ms = (time.time() - start_time) * 1000
                    log_agent_command(
                        direction="inbound",
                        command=command,
                        correlation_id=request_id,
                        payload={"error": "timeout"},
                        latency_ms=latency_ms,
                        error="WebSocket timeout"
                    )

                    logger.warning(
                        "agent_service_websocket_timeout",
                        service="backend",
                        request_id=request_id,
                        command=command,
                        timeout=timeout
                    )
                    # Treat a timeout as an unhealthy socket and reconnect.
                    await self._teardown_websocket()
                    await self._schedule_reconnect()
                    # Fall through to Redis fallback
                except Exception as e:
                    self._pending_responses.pop(request_id, None)

                    # Log WebSocket error
                    latency_ms = (time.time() - start_time) * 1000
                    log_agent_command(
                        direction="inbound",
                        command=command,
                        correlation_id=request_id,
                        payload={"error": str(e)},
                        latency_ms=latency_ms,
                        error=str(e)
                    )

                    logger.warning(
                        "agent_service_websocket_error",
                        service="backend",
                        request_id=request_id,
                        command=command,
                        error=str(e)
                    )
                    # Treat errors as unhealthy socket and reconnect.
                    await self._teardown_websocket()
                    await self._schedule_reconnect()
                    # Fall through to Redis fallback
            
            except Exception as e:
                logger.error(
                    "outbound_agent_command_ws_send_exception",
                    error=str(e),
                    command=command,
                    message="Outbound WebSocket send failed; may fall back to Redis",
                )

        if (
            outbound_ws_active
            and not settings.agent_redis_fallback_when_ws_connected
        ):
            logger.warning(
                "agent_service_redis_fallback_disabled",
                command=command,
                message="Outbound WS was connected; skipping Redis enqueue (AGENT_REDIS_FALLBACK_WHEN_WS_CONNECTED=false)",
            )
            return None

        # Fallback to Redis queue (command transport)
        try:
            message = {
                "request_id": request_id,
                "command": command,
                "parameters": parameters or {},
                "timestamp": time.time()
            }
            
            logger.info(
                "redis_command_transport_enqueue",
                command=command,
                queue=self.command_queue,
            )
            success = await enqueue_command(message, self.command_queue)
            if not success:
                logger.error(
                    "redis_command_transport_enqueue_failed",
                    command=command,
                    queue=self.command_queue,
                )
                return None

            logger.info(
                "redis_command_transport_enqueued",
                command=command,
                message="Command sent via Redis (used when outbound WS unavailable or after WS failure)",
            )
            await asyncio.sleep(0.5)
            return await self._wait_for_response(request_id, timeout)
        except Exception as e:
            logger.error("redis_command_transport_failed", command=command, error=str(e))
            return None
    
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
        poll_interval = 0.1  # Faster polling
        poll_count = 0
        start_time = time.time()

        while time.time() < deadline:
            poll_count += 1
            response = await get_response(request_id)
            if response:
                # Log successful Redis response
                latency_ms = (time.time() - start_time) * 1000
                # Extract command from response if available, otherwise use generic
                command = response.get("command", "unknown")
                log_agent_command(
                    direction="inbound",
                    command=command,
                    correlation_id=request_id,
                    payload=response,
                    latency_ms=latency_ms
                )
                return response
            await asyncio.sleep(poll_interval)

        # Log timeout for Redis polling
        latency_ms = (time.time() - start_time) * 1000
        log_agent_command(
            direction="inbound",
            command="unknown",
            correlation_id=request_id,
            payload={"error": "Redis timeout"},
            latency_ms=latency_ms,
            error="Redis polling timeout"
        )

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
                    "timestamp": status.get("last_update", datetime.now(timezone.utc)),
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
    
    async def get_agent_status(self, timeout: float = 5) -> Optional[Dict[str, Any]]:
        """Get agent status.

        Args:
            timeout: Timeout in seconds for the command (default 5)
        """
        now_ts = time.time()
        if (
            self._agent_status_cache is not None
            and (now_ts - self._agent_status_cache_updated_at) <= self._agent_status_cache_ttl_seconds
        ):
            # Avoid bursty fan-out during health sync.
            return dict(self._agent_status_cache)

        async with self._agent_status_fetch_lock:
            # Re-check cache inside the lock (single-flight).
            now_ts = time.time()
            if (
                self._agent_status_cache is not None
                and (now_ts - self._agent_status_cache_updated_at) <= self._agent_status_cache_ttl_seconds
            ):
                return dict(self._agent_status_cache)

            start_time = time.time()
            response = await self._send_command(
                "get_status",
                parameters={},
                timeout=timeout,
            )
            latency_ms = (time.time() - start_time) * 1000
            now = datetime.now(timezone.utc)

            if not response:
                status_response = {
                    "available": True,
                    "state": "DEGRADED",
                    "last_update": now,
                    "active_symbols": [],
                    "model_count": 0,
                    "health_status": "timeout",
                    "message": "Agent did not respond to status command in time (timeout)",
                    "latency_ms": round(latency_ms, 2),
                }
                self._agent_status_cache = status_response
                self._agent_status_cache_updated_at = time.time()
                return dict(status_response)

            # response is already the extracted data from WebSocket response
            # (see _websocket_receive_loop: future.set_result(data.get("data", data)))
            data = response if isinstance(response, dict) else {}

            health = data.get("health", {})
            detailed_health = data.get("detailed_health", {})

            # Extract model registry info from health or detailed_health
            model_registry = health.get("model_registry", {})
            if not model_registry and detailed_health:
                model_nodes = detailed_health.get("model_nodes", {})
                model_registry = {
                    "total_models": model_nodes.get("total_models", 0),
                    "healthy_models": model_nodes.get("healthy_models", 0),
                }

            available = data.get("available", True)

            # Determine agent state - infer from available data if not explicitly provided
            agent_state = data.get("state", "UNKNOWN")
            if agent_state == "UNKNOWN" and available:
                active_symbols = data.get("active_symbols", [])
                model_count = model_registry.get("total_models", 0)
                if active_symbols:
                    agent_state = "OBSERVING"
                elif model_count > 0:
                    agent_state = "OBSERVING"
                else:
                    agent_state = "OBSERVING"

            status_response = {
                "available": available,
                "state": agent_state,
                "last_update": now,
                "active_symbols": data.get("active_symbols", []),
                "model_count": model_registry.get("total_models", 0),
                "health_status": health.get("overall_status", "unknown"),
                "message": data.get("message"),
                "latency_ms": round(latency_ms, 2),
            }

            # Add detailed health information if available
            if detailed_health:
                inferred_detailed_health = dict(detailed_health)

                # Infer feature server status
                if "feature_server" in inferred_detailed_health:
                    fs = inferred_detailed_health["feature_server"]
                    if isinstance(fs, dict) and fs.get("status") == "unknown":
                        feature_count = fs.get("feature_registry_count", 0)
                        if feature_count > 0:
                            fs = dict(fs)
                            fs["status"] = "up"
                            fs["note"] = (
                                f"Inferred healthy status from {feature_count} registered features"
                            )
                            inferred_detailed_health["feature_server"] = fs

                # Infer model nodes status
                if "model_nodes" in inferred_detailed_health:
                    mn = inferred_detailed_health["model_nodes"]
                    if isinstance(mn, dict) and mn.get("status") == "unknown":
                        healthy_count = mn.get("healthy_models", 0)
                        total_count = mn.get("total_models", 0)
                        if total_count > 0:
                            if healthy_count > 0:
                                status = "up"
                            elif healthy_count == 0 and total_count > 0:
                                status = "degraded"
                            else:
                                status = "unknown"

                            mn = dict(mn)
                            mn["status"] = status
                            if status == "degraded":
                                mn["note"] = (
                                    f"Models loaded ({total_count}) but healthy count is 0/{total_count}; "
                                    "run predictions to refresh health."
                                )
                            else:
                                mn["note"] = (
                                    f"Inferred status from {healthy_count}/{total_count} healthy models"
                                )
                            inferred_detailed_health["model_nodes"] = mn

                # Infer delta exchange status
                if "delta_exchange" in inferred_detailed_health:
                    de = inferred_detailed_health["delta_exchange"]
                    if isinstance(de, dict) and de.get("status") == "unknown":
                        circuit_breaker = de.get("circuit_breaker", {})
                        if isinstance(circuit_breaker, dict):
                            cb_state = circuit_breaker.get("state")
                            if cb_state == "CLOSED":
                                de = dict(de)
                                de["status"] = "up"
                                de["note"] = "Inferred healthy status from circuit breaker state"
                                inferred_detailed_health["delta_exchange"] = de
                            elif cb_state == "OPEN":
                                de = dict(de)
                                de["status"] = "down"
                                de["note"] = (
                                    "Circuit breaker is open - service temporarily unavailable"
                                )
                                inferred_detailed_health["delta_exchange"] = de

                # Infer reasoning engine status
                if "reasoning_engine" in inferred_detailed_health:
                    re = inferred_detailed_health["reasoning_engine"]
                    if isinstance(re, dict) and re.get("status") == "unknown":
                        vector_store_available = re.get("vector_store_available", None)
                        if vector_store_available is not None:
                            re = dict(re)
                            re["status"] = "up"
                            re["note"] = (
                                "Inferred healthy status from reasoning engine data availability"
                            )
                            inferred_detailed_health["reasoning_engine"] = re

                status_response.update(
                    {
                        "feature_server": inferred_detailed_health.get("feature_server", {}),
                        "model_nodes": inferred_detailed_health.get("model_nodes", {}),
                        "delta_exchange": inferred_detailed_health.get("delta_exchange", {}),
                        "reasoning_engine": inferred_detailed_health.get("reasoning_engine", {}),
                    }
                )
            else:
                if health and isinstance(health, dict):
                    mcp_components = health.get("mcp_orchestrator", {}).get("components", {})
                    status_response.update(
                        {
                            "feature_server": mcp_components.get("feature_server", {}),
                            "model_nodes": mcp_components.get("model_registry", {}),
                            "delta_exchange": {},
                            "reasoning_engine": mcp_components.get("reasoning_engine", {}),
                        }
                    )

            self._agent_status_cache = status_response
            self._agent_status_cache_updated_at = time.time()
            return dict(status_response)
    
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
    
    async def heartbeat(self):
        """Send heartbeat ping to agent via WebSocket."""
        try:
            if self.use_websocket and self._websocket_connected and self._websocket:
                await self._websocket.send(json.dumps({"type": "ping"}))
            else:
                logger.debug("HEARTBEAT: WebSocket not connected, skipping heartbeat")
        except Exception as e:
            logger.error("HEARTBEAT FAIL — triggering reconnect: %s", e)
            self._websocket_connected = False


# Global agent service instance
agent_service = AgentService()
