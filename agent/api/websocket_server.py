"""Agent WebSocket server.

This module exposes a lightweight WebSocket server that the backend
can connect to in order to send commands (predict, execute_trade,
get_status, control, etc.) and receive responses in real time.

It is deliberately self‑contained so that it can be wired into the
agent startup without affecting the existing Redis command/response
path. Initially this is **optional** and can coexist with the Redis
queue implementation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Set, Callable, Awaitable

import structlog

try:  # websockets is a soft dependency for now
    import websockets
    from websockets.server import WebSocketServerProtocol
    from websockets.exceptions import ConnectionClosed
except Exception:  # pragma: no cover - import guarded for environments without websockets
    websockets = None  # type: ignore
    WebSocketServerProtocol = object  # type: ignore
    ConnectionClosed = Exception  # type: ignore

from agent.core.config import settings
from agent.core.logging_utils import log_error_with_context
from agent.core.intelligent_agent import IntelligentAgent

logger = structlog.get_logger()


@dataclass
class _ClientContext:
    """Per‑connection context for a backend client."""

    websocket: WebSocketServerProtocol
    remote: str
    
    def __hash__(self) -> int:
        """Make context hashable by using websocket object id."""
        return id(self.websocket)
    
    def __eq__(self, other: object) -> bool:
        """Compare contexts by websocket object identity."""
        if not isinstance(other, _ClientContext):
            return False
        return self.websocket is other.websocket


class AgentWebSocketServer:
    """WebSocket server that exposes the agent command interface.

    The server is intentionally thin: it simply translates JSON
    command messages into calls to the existing intelligent agent
    command processor and streams back JSON responses.
    """

    def __init__(
        self,
        agent: IntelligentAgent,
        host: str = "0.0.0.0",
        port: int = 8002,
    ) -> None:
        self._agent = agent
        self._host = host
        self._port = port
        self._server: Optional[websockets.server.Serve] = None  # type: ignore[assignment]
        self._clients: Set[_ClientContext] = set()
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start the WebSocket server if websockets is available."""

        if self._running:
            logger.warning(
                "agent_websocket_server_already_running",
                service="agent",
                host=self._host,
                port=self._port,
            )
            return

        if websockets is None:
            logger.warning(
                "agent_websocket_server_websockets_missing",
                service="agent",
                message=(
                    "websockets library not installed; agent WebSocket server "
                    "will not start. Install 'websockets' in agent/requirements.txt "
                    "to enable this feature."
                ),
            )
            return

        try:
            self._server = await websockets.serve(  # type: ignore[call-arg]
                self._handle_connection,
                self._host,
                self._port,
            )
            self._running = True

            logger.info(
                "agent_websocket_server_started",
                service="agent",
                host=self._host,
                port=self._port,
                url=f"ws://{self._host}:{self._port}",
            )
        except Exception as exc:  # pragma: no cover - startup failure path
            log_error_with_context(
                "agent_websocket_server_start_failed",
                error=exc,
                component="agent_websocket_server",
                host=self._host,
                port=self._port,
            )
            raise

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""

        if not self._running:
            return

        self._running = False

        # Close client connections
        for client in list(self._clients):
            try:
                await client.websocket.close()
            except Exception:  # pragma: no cover - best‑effort cleanup
                pass
        self._clients.clear()

        # Close server listener
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

        logger.info(
            "agent_websocket_server_stopped",
            service="agent",
            host=self._host,
            port=self._port,
        )

    # ------------------------------------------------------------------
    # Connection / message handling
    # ------------------------------------------------------------------
    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle an individual client connection."""
        
        # AGENT WS: Client connected logging
        logger.info("AGENT WS: Client connected")

        remote = "unknown"
        try:
            if getattr(websocket, "remote_address", None):
                host, port = websocket.remote_address  # type: ignore[misc]
                remote = f"{host}:{port}"
        except Exception:  # pragma: no cover - best effort only
            pass

        ctx = _ClientContext(websocket=websocket, remote=remote)
        self._clients.add(ctx)

        logger.info(
            "agent_websocket_client_connected",
            service="agent",
            remote=remote,
            path=path,
            total_connections=len(self._clients),
        )

        try:
            async for raw in websocket:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "agent_websocket_invalid_json",
                        service="agent",
                        remote=remote,
                        error=str(exc),
                    )
                    await self._send_error(ctx, None, "Invalid JSON payload")
                    continue

                await self._handle_message(ctx, payload)

        except ConnectionClosed:
            logger.info(
                "agent_websocket_client_disconnected",
                service="agent",
                remote=remote,
            )
        except Exception as exc:  # pragma: no cover - unexpected connection error
            logger.error("AGENT WS ERROR: %s", exc)
            logger.warning("AGENT WS: Forcing reconnect in 1s")
            await asyncio.sleep(1)
            log_error_with_context(
                "agent_websocket_connection_error",
                error=exc,
                component="agent_websocket_server",
                remote=remote,
            )
        finally:
            self._clients.discard(ctx)
            logger.info(
                "agent_websocket_connection_closed",
                service="agent",
                remote=remote,
                remaining_connections=len(self._clients),
            )

    async def _handle_message(self, ctx: _ClientContext, msg: Dict[str, Any]) -> None:
        """Route a decoded JSON message to the appropriate handler."""

        msg_type = msg.get("type")
        request_id = msg.get("request_id") or str(uuid.uuid4())

        if msg_type == "command":
            await self._handle_command(ctx, request_id, msg)
        elif msg_type == "ping":
            await self._send_pong(ctx, request_id)
        else:
            await self._send_error(ctx, request_id, f"Unknown message type: {msg_type}")

    async def _handle_command(self, ctx: _ClientContext, request_id: str, msg: Dict[str, Any]) -> None:
        """Handle a `command` message from the backend.

        The schema mirrors the Redis command structure so that the
        same internal handler (`_process_command`) can be reused.
        """

        command = msg.get("command")
        parameters = msg.get("parameters") or {}

        if not command:
            await self._send_error(ctx, request_id, "Missing command field")
            return

        logger.debug(
            "agent_websocket_command_received",
            service="agent",
            remote=ctx.remote,
            request_id=request_id,
            command=command,
        )

        # Reuse existing command processing logic on the agent
        try:
            internal_command = {
                "request_id": request_id,
                "command": command,
                "parameters": parameters,
                "timestamp": datetime.utcnow().isoformat(),
            }
            # `_process_command` already returns a response dict in the
            # same shape the backend expects from the Redis path.
            response = await self._agent._process_command(internal_command)  # type: ignore[attr-defined]
        except Exception as exc:
            log_error_with_context(
                "agent_websocket_command_error",
                error=exc,
                component="agent_websocket_server",
                request_id=request_id,
                command=command,
            )
            await self._send_error(ctx, request_id, f"Command failed: {exc}")
            return

        await self._send_response(ctx, request_id, response)

    # ------------------------------------------------------------------
    # Outgoing messages
    # ------------------------------------------------------------------
    async def _send_json(self, ctx: _ClientContext, payload: Dict[str, Any]) -> None:
        """Send JSON payload to a specific client, guarding errors."""

        try:
            await ctx.websocket.send(json.dumps(payload, default=str))
        except Exception as exc:  # pragma: no cover - best‑effort send path
            log_error_with_context(
                "agent_websocket_send_failed",
                error=exc,
                component="agent_websocket_server",
                remote=ctx.remote,
            )

    async def _send_response(self, ctx: _ClientContext, request_id: str, response: Dict[str, Any]) -> None:
        """Send a structured response back to the backend client."""

        message = {
            "type": "response",
            "request_id": request_id,
            "success": response.get("success", True),
            "data": response.get("data", response),
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._send_json(ctx, message)

    async def _send_error(self, ctx: _ClientContext, request_id: Optional[str], error_message: str) -> None:
        """Send an error frame back to the backend client."""

        message = {
            "type": "error",
            "request_id": request_id,
            "success": False,
            "error": error_message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._send_json(ctx, message)

    async def _send_pong(self, ctx: _ClientContext, request_id: Optional[str]) -> None:
        """Reply to a ping frame with pong and timestamp."""

        message = {
            "type": "pong",
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._send_json(ctx, message)

    # ------------------------------------------------------------------
    # Broadcast helper (optional – for future use)
    # ------------------------------------------------------------------
    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected backend clients."""

        if not self._clients:
            return

        payload = json.dumps(message, default=str)
        disconnected: Set[_ClientContext] = set()

        for ctx in self._clients:
            try:
                await ctx.websocket.send(payload)
            except Exception:  # pragma: no cover - best‑effort broadcast
                disconnected.add(ctx)

        for ctx in disconnected:
            self._clients.discard(ctx)


# ----------------------------------------------------------------------
# Global helper
# ----------------------------------------------------------------------

_server_instance: Optional[AgentWebSocketServer] = None


async def get_websocket_server(agent: IntelligentAgent) -> AgentWebSocketServer:
    """Get or lazily create the global `AgentWebSocketServer` instance.

    This helper allows the agent startup code to obtain and start the
    server without worrying about multiple instances.
    """

    global _server_instance

    if _server_instance is None:
        host = getattr(settings, "agent_websocket_host", "0.0.0.0")
        port = getattr(settings, "agent_websocket_port", 8002)
        _server_instance = AgentWebSocketServer(agent, host=host, port=port)

    return _server_instance
