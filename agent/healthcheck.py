"""Container healthcheck utility for the agent."""

import asyncio
import socket
import structlog
from typing import Optional

from agent.core.config import settings
from agent.core.redis_config import get_redis, close_redis

# Initialize logger for healthcheck
logger = structlog.get_logger()


def _check_port(host: str, port: int, service: str) -> bool:
    """Return True if a TCP port is accepting connections."""
    try:
        # 0.0.0.0 is a bind address; for connectivity checks use loopback.
        check_host = host
        if check_host in {"0.0.0.0", "::"}:
            check_host = "127.0.0.1"

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            result = sock.connect_ex((check_host, port))
        if result != 0:
            logger.warning(
                "agent_healthcheck_port_unreachable",
                service="agent",
                component=service,
                host=host,
                port=port,
            )
            return False
        return True
    except Exception as exc:  # pragma: no cover - defensive healthcheck
        logger.error(
            "agent_healthcheck_port_check_failed",
            service="agent",
            component=service,
            host=host,
            port=port,
            error=str(exc),
            exc_info=True,
        )
        return False


async def _check_websocket_port(host: str, port: int) -> bool:
    """Check WebSocket port with a real handshake (protocol-safe).

    This avoids the `websockets.server: connection rejected (400 Bad Request)` noise
    caused by raw TCP probes to a WebSocket endpoint.
    """
    # 0.0.0.0 is not connectable; use loopback for the healthcheck probe.
    probe_host = host
    if probe_host in {"0.0.0.0", "::"}:
        probe_host = "127.0.0.1"

    try:
        import websockets  # type: ignore
    except Exception:
        # If websockets isn't available in the healthcheck environment, skip WS probing
        # (we still enforce Redis + feature-server checks).
        logger.warning(
            "agent_healthcheck_websockets_missing",
            service="agent",
            host=probe_host,
            port=port,
        )
        return True

    try:
        async with websockets.connect(
            f"ws://{probe_host}:{port}",
            open_timeout=2.0,
            close_timeout=1.0,
        ):
            # Handshake succeeded; connection closed on context exit.
            return True
    except Exception as exc:
        # Keep logs for debugging healthcheck failures.
        logger.warning(
            "agent_healthcheck_websocket_probe_failed",
            service="agent",
            host=probe_host,
            port=port,
            error=str(exc),
        )
        return False


async def _check_websocket_any_port(host: str, port: int) -> bool:
    """Check for a WebSocket handshake on the configured port or common alternates.

    The agent's WebSocket server may auto-select an alternate port (e.g. 8002 -> 8003)
    when the default port is occupied (often by the feature server).
    """
    # Prefer configured port, then scan a small range to match websocket_server.py.
    candidate_ports = [port] + list(range(port + 1, port + 9))  # up to +8

    for candidate_port in candidate_ports:
        if await _check_websocket_port(host, candidate_port):
            return True
    return False


async def _run_check() -> int:
    """Verify critical agent dependencies are reachable."""
    try:
        client = await get_redis()
        if client is None:
            logger.warning(
                "agent_healthcheck_failed",
                service="agent",
                reason="Redis unavailable",
            )
            return 2

        pong = await client.ping()
        if not pong:
            logger.warning(
                "agent_healthcheck_failed",
                service="agent",
                reason="Redis ping failed",
            )
            return 1

        # Verify that HTTP feature bridge and WebSocket server are accepting connections.
        feature_ok = _check_port(
            settings.feature_server_host,
            settings.feature_server_port,
            service="feature_server_api",
        )
        # Also verify the agent command WebSocket is reachable; backend depends
        # on `agent: condition: service_healthy` before it starts issuing commands.
        #
        # Use protocol-safe WebSocket handshake probing to avoid false positives.
        ws_ok = await _check_websocket_any_port("127.0.0.1", settings.agent_websocket_port)

        if not feature_ok or not ws_ok:
            # Treat missing ports as a hard failure so Docker keeps waiting.
            return 2

        logger.debug("agent_healthcheck_passed", service="agent")
        return 0
    except Exception as exc:  # pragma: no cover - defensive healthcheck
        logger.error(
            "agent_healthcheck_failed",
            service="agent",
            error=str(exc),
            exc_info=True,
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

