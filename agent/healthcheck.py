"""Container healthcheck utility for the agent."""

import asyncio
import sys
import structlog

from agent.core.redis import get_redis, close_redis

# Initialize logger for healthcheck
logger = structlog.get_logger()


async def _run_check() -> int:
    """Verify critical agent dependencies are reachable."""
    try:
        client = await get_redis()
        if client is None:
            logger.warning(
                "agent_healthcheck_failed",
                service="agent",
                reason="Redis unavailable"
            )
            return 2
        pong = await client.ping()
        if not pong:
            logger.warning(
                "agent_healthcheck_failed",
                service="agent",
                reason="Redis ping failed"
            )
            return 1
        logger.debug("agent_healthcheck_passed", service="agent")
        return 0
    except Exception as exc:  # pragma: no cover - defensive healthcheck
        logger.error(
            "agent_healthcheck_failed",
            service="agent",
            error=str(exc),
            exc_info=True
        )
        return 2
    finally:
        await close_redis()


def main() -> None:
    """Entrypoint for container healthcheck."""
    exit_code = asyncio.run(_run_check())
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

