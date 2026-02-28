"""
Health Poller Service.

Periodically polls agent health and broadcasts updates to WebSocket clients.
Ensures frontend stays updated even if individual events are missed.
"""

import asyncio
import time
from typing import Optional
from datetime import datetime, timezone
import structlog

from backend.services.agent_service import agent_service
from backend.api.websocket.manager import websocket_manager
from backend.core.logging import log_error_with_context

logger = structlog.get_logger()


class HealthPoller:
    """Service that periodically polls agent health and broadcasts updates."""

    def __init__(self, poll_interval: int = 30):
        """Initialize health poller.

        Args:
            poll_interval: Polling interval in seconds (default: 30)
        """
        self.poll_interval = poll_interval
        self.running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_health_broadcast = 0
        self._last_state_broadcast = 0

    async def start(self):
        """Start the health polling loop."""
        if self.running:
            logger.warning("health_poller_already_running", message="Health poller is already running")
            return

        self.running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "health_poller_started",
            service="backend",
            poll_interval=self.poll_interval,
            message="Periodic health polling started"
        )

    async def stop(self):
        """Stop the health polling loop."""
        if not self.running:
            return

        self.running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        logger.info("health_poller_stopped", service="backend")

    async def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                await self._poll_and_broadcast()
            except Exception as e:
                logger.error(
                    "health_poller_error",
                    service="backend",
                    error=str(e),
                    exc_info=True,
                    message="Error in health polling loop, continuing"
                )

            # Wait for next poll interval
            await asyncio.sleep(self.poll_interval)

    async def _poll_and_broadcast(self):
        """Poll agent health and broadcast updates."""
        try:
            # Get current agent status
            agent_status = await agent_service.get_agent_status()
            if not agent_status:
                logger.debug("health_poller_no_agent_status", message="No agent status available, skipping broadcast")
                return

            current_time = time.time()

            # Broadcast agent state if it's been more than poll_interval since last broadcast
            # or if this is the first broadcast
            if current_time - self._last_state_broadcast >= self.poll_interval or self._last_state_broadcast == 0:
                state = agent_status.get("state", "UNKNOWN")
                last_update = agent_status.get("last_update")

                # Format state data for frontend
                state_data = {
                    "state": state,
                    "last_update": last_update.isoformat() if isinstance(last_update, datetime) else last_update,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "periodic_poll"
                }

                # Broadcast via WebSocket
                await websocket_manager.broadcast(
                    {"type": "agent_state", "data": state_data},
                    channel="agent_state"
                )

                self._last_state_broadcast = current_time

                logger.debug(
                    "health_poller_state_broadcast",
                    service="backend",
                    state=state,
                    last_update=last_update
                )

            # Broadcast health update if it's been more than poll_interval since last broadcast
            if current_time - self._last_health_broadcast >= self.poll_interval or self._last_health_broadcast == 0:
                # Extract health data for broadcast
                health_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "overall_status": agent_status.get("health_status", "unknown"),
                    "services": {
                        "agent": {
                            "status": "up" if agent_status.get("available", False) else "down",
                            "latency_ms": agent_status.get("latency_ms"),
                            "details": agent_status
                        },
                        "feature_server": agent_status.get("feature_server", {}),
                        "model_nodes": agent_status.get("model_nodes", {}),
                        "delta_exchange": agent_status.get("delta_exchange", {}),
                        "reasoning_engine": agent_status.get("reasoning_engine", {})
                    },
                    "source": "periodic_poll"
                }

                # Broadcast via WebSocket
                await websocket_manager.broadcast(
                    {"type": "health_update", "data": health_data},
                    channel="health_update"
                )

                self._last_health_broadcast = current_time

                logger.debug(
                    "health_poller_health_broadcast",
                    service="backend",
                    overall_status=health_data.get("overall_status"),
                    services_count=len(health_data.get("services", {}))
                )

        except Exception as e:
            log_error_with_context(
                "Failed to poll and broadcast health data",
                error=e,
                component="health_poller",
            )


# Global health poller instance
health_poller = HealthPoller()