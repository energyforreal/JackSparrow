"""
Health Poller Service.

Periodically polls agent health for internal use. Health and agent-state broadcasts
are consolidated in the unified WebSocket manager (single schema, single publisher).
"""

import asyncio
from typing import Optional
import structlog

logger = structlog.get_logger()


class HealthPoller:
    """Service that periodically polls agent health (no direct broadcast).

    Unified WebSocket manager is the single publisher for health and agent state
    via _health_sync_loop and _agent_state_sync_loop using check_overall_health
    and agent_service.get_current_state(). This poller can be used for metrics
    or triggering other logic without duplicating broadcast payloads.
    """

    def __init__(self, poll_interval: int = 30):
        """Initialize health poller.

        Args:
            poll_interval: Polling interval in seconds (default: 30)
        """
        self.poll_interval = poll_interval
        self.running = False
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the health polling loop (no broadcast)."""
        if self.running:
            logger.warning("health_poller_already_running", message="Health poller is already running")
            return
        self.running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "health_poller_started",
            service="backend",
            poll_interval=self.poll_interval,
            message="Periodic health polling started (broadcasts via unified manager only)",
        )

    async def stop(self) -> None:
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

    async def _poll_loop(self) -> None:
        """Main polling loop (no broadcast; unified manager owns health/agent_state)."""
        from backend.services.agent_service import agent_service
        from backend.services.model_service import model_service
        from backend.core.redis import set_model_health_heartbeat
        from backend.core.config import settings

        while self.running:
            try:
                await agent_service.get_agent_status()
            except Exception as e:
                logger.debug(
                    "health_poller_poll_error",
                    service="backend",
                    error=str(e),
                    message="Poll cycle failed, continuing",
                )
            try:
                health = await model_service.get_health()
                ttl = getattr(settings, "model_health_ttl", 30)
                if ttl > 0 and health:
                    await set_model_health_heartbeat(
                        {
                            "status": health.get("status", "down"),
                            "latency_ms": health.get("latency_ms"),
                            "details": health.get("details") or {},
                        },
                        ttl=ttl,
                    )
            except Exception as e:
                logger.debug(
                    "health_poller_model_serving_error",
                    service="backend",
                    error=str(e),
                )
            await asyncio.sleep(self.poll_interval)


# Global health poller instance
health_poller = HealthPoller()