"""Agent WebSocket client.

This module provides a WebSocket client that connects to the backend
to send agent events directly, bypassing Redis Streams for lower latency.

It runs alongside the Redis Stream publisher, sending events to both
channels for redundancy and performance.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional
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

from agent.core.config import settings
from agent.core.logging_utils import log_error_with_context

logger = structlog.get_logger()


class AgentWebSocketClient:
    """WebSocket client for sending agent events to backend."""

    def __init__(self, url: str) -> None:
        """Initialize WebSocket client.

        Args:
            url: Backend WebSocket URL (e.g., ws://localhost:8000/ws/agent)
        """
        self.url = url
        self._websocket: Optional[WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    async def start(self) -> None:
        """Start WebSocket client and begin connection attempts."""

        if self._running:
            logger.warning(
                "agent_websocket_client_already_running",
                service="agent",
                url=self.url,
            )
            return

        if websockets is None:
            logger.warning(
                "agent_websocket_client_websockets_missing",
                service="agent",
                message=(
                    "websockets library not installed; agent WebSocket client "
                    "will not start. Events will only be sent via Redis Streams."
                ),
            )
            return

        self._running = True
        self._reconnect_task = asyncio.create_task(self._connect_loop())

        logger.info(
            "agent_websocket_client_started",
            service="agent",
            url=self.url,
        )

    async def stop(self) -> None:
        """Stop WebSocket client and close connection."""

        self._running = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

        self._connected = False

        logger.info(
            "agent_websocket_client_stopped",
            service="agent",
            url=self.url,
        )

    async def _connect_loop(self) -> None:
        """Main connection loop with automatic reconnection."""

        while self._running:
            try:
                await self._connect()
                # If connection succeeds, wait for it to close
                await self._wait_for_close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_error_with_context(
                    "agent_websocket_client_connection_error",
                    error=exc,
                    component="agent_websocket_client",
                    url=self.url,
                )

            if not self._running:
                break

            # Exponential backoff before reconnecting
            delay = min(self._reconnect_delay, self._max_reconnect_delay)
            logger.info(
                "agent_websocket_client_reconnecting",
                service="agent",
                url=self.url,
                delay=delay,
            )
            await asyncio.sleep(delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def _connect(self) -> None:
        """Establish WebSocket connection to backend."""

        try:
            self._websocket = await websockets.connect(  # type: ignore[call-arg]
                self.url,
                ping_interval=30,
                ping_timeout=10,
            )
            self._connected = True
            self._reconnect_delay = 1.0  # Reset delay on successful connection

            logger.info(
                "agent_websocket_client_connected",
                service="agent",
                url=self.url,
            )

            # Start listening for messages (e.g., pings, acknowledgments)
            asyncio.create_task(self._receive_loop())

        except Exception as exc:
            self._connected = False
            if self._websocket:
                try:
                    await self._websocket.close()
                except Exception:
                    pass
                self._websocket = None
            raise exc

    async def _receive_loop(self) -> None:
        """Receive messages from backend (e.g., pings, acknowledgments)."""

        if not self._websocket:
            return

        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "ping":
                        await self._send_pong()
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON
                except Exception:
                    pass  # Ignore other receive errors

        except ConnectionClosed:
            self._connected = False
            logger.info(
                "agent_websocket_client_disconnected",
                service="agent",
                url=self.url,
            )
        except Exception as exc:
            log_error_with_context(
                "agent_websocket_client_receive_error",
                error=exc,
                component="agent_websocket_client",
                url=self.url,
            )
            self._connected = False

    async def _wait_for_close(self) -> None:
        """Wait for connection to close."""

        if self._websocket:
            try:
                await self._websocket.wait_closed()
            except Exception:
                pass

    async def _send_pong(self) -> None:
        """Send pong response to backend ping."""

        message = {
            "type": "pong",
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.send_event(message)

    async def send_event(self, event: Dict[str, Any]) -> bool:
        """Send event to backend via WebSocket.

        Args:
            event: Event dictionary to send

        Returns:
            True if sent successfully, False otherwise
        """

        if not self._connected or not self._websocket:
            return False

        try:
            payload = json.dumps(event, default=str)
            await self._websocket.send(payload)
            return True
        except Exception as exc:
            log_error_with_context(
                "agent_websocket_client_send_failed",
                error=exc,
                component="agent_websocket_client",
                url=self.url,
            )
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""

        return self._connected and self._websocket is not None


# Global client instance
_client_instance: Optional[AgentWebSocketClient] = None


async def get_websocket_client() -> Optional[AgentWebSocketClient]:
    """Get or create WebSocket client instance.

    Returns:
        AgentWebSocketClient instance, or None if websockets not available
    """

    global _client_instance

    if websockets is None:
        return None

    if _client_instance is None:
        url = getattr(settings, "backend_websocket_url", "ws://localhost:8000/ws/agent")
        _client_instance = AgentWebSocketClient(url)

    return _client_instance
