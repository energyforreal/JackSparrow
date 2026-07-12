"""Unit tests for outbound agent WebSocket teardown on send failure."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("API_KEY", "test-api-key")

from backend.services import agent_service as agent_service_mod
from backend.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_send_command_tears_down_on_clean_close_and_falls_back_to_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closed socket (1000) must teardown + reconnect, then use Redis."""
    service = AgentService()
    service.use_websocket = True
    service._websocket_connected = True
    closed_ws = MagicMock()
    closed_ws.send = AsyncMock(
        side_effect=Exception("received 1000 (OK); then sent 1000 (OK)")
    )
    service._websocket = closed_ws

    teardown = AsyncMock()
    reconnect = AsyncMock()
    monkeypatch.setattr(service, "_teardown_websocket", teardown)
    monkeypatch.setattr(service, "_schedule_reconnect", reconnect)

    enqueue = AsyncMock(return_value=True)
    wait = AsyncMock(return_value={"ok": True, "command": "get_status"})
    monkeypatch.setattr(agent_service_mod, "enqueue_command", enqueue)
    monkeypatch.setattr(service, "_wait_for_response", wait)
    monkeypatch.setattr(
        agent_service_mod.settings, "agent_redis_fallback_when_ws_connected", True
    )

    result = await service._send_command("get_status", timeout=5)

    assert result == {"ok": True, "command": "get_status"}
    teardown.assert_awaited_once()
    reconnect.assert_awaited_once()
    enqueue.assert_awaited_once()
    assert service._pending_responses == {}


@pytest.mark.asyncio
async def test_heartbeat_teardown_and_reconnect_on_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat failure must clear the socket and schedule reconnect."""
    service = AgentService()
    service.use_websocket = True
    service._websocket_connected = True
    closed_ws = MagicMock()
    closed_ws.send = AsyncMock(side_effect=Exception("received 1000 (OK)"))
    service._websocket = closed_ws

    teardown = AsyncMock()
    reconnect = AsyncMock()
    monkeypatch.setattr(service, "_teardown_websocket", teardown)
    monkeypatch.setattr(service, "_schedule_reconnect", reconnect)

    await service.heartbeat()

    teardown.assert_awaited_once()
    reconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_receive_loop_teardown_on_connection_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receive-loop ConnectionClosed must null the socket via teardown."""
    service = AgentService()
    service.use_websocket = True
    service._websocket_connected = True

    class _ClosedIter:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise agent_service_mod.ConnectionClosed(None, None)

    service._websocket = _ClosedIter()

    teardown = AsyncMock()
    reconnect = AsyncMock()
    monkeypatch.setattr(service, "_teardown_websocket", teardown)
    monkeypatch.setattr(service, "_schedule_reconnect", reconnect)

    await service._websocket_receive_loop()

    teardown.assert_awaited_once()
    reconnect.assert_awaited_once()
