"""The Delta ticker socket must have a single reader."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent.data.delta_client import DeltaExchangeWebSocketClient


class _OneShotSocket:
    def __init__(self) -> None:
        self.calls = 0
        self.released = asyncio.Event()

    async def recv(self) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps({"type": "ping"})
        await self.released.wait()
        return json.dumps({"type": "ping"})


class _ConflictSocket:
    async def recv(self) -> str:
        raise RuntimeError(
            "cannot call recv while another coroutine "
            "is already waiting for the next message"
        )


def _client() -> DeltaExchangeWebSocketClient:
    return DeltaExchangeWebSocketClient("k", "s", base_url="wss://example.test")


@pytest.mark.asyncio
async def test_message_loop_does_not_read_a_replaced_socket() -> None:
    client = _client()
    first = _OneShotSocket()
    client.websocket = first
    client.connected = True

    task = asyncio.create_task(client._message_loop())
    for _ in range(50):
        if first.calls >= 1:
            break
        await asyncio.sleep(0.01)

    second = _OneShotSocket()
    client.websocket = second
    first.released.set()
    await asyncio.wait_for(task, timeout=1)
    assert second.calls == 0


@pytest.mark.asyncio
async def test_message_loop_stops_when_recv_is_already_in_progress() -> None:
    client = _client()
    client.websocket = _ConflictSocket()
    client.connected = True
    reasons: list[str] = []
    client.on_connection_lost = reasons.append

    async def _no_reconnect() -> None:
        return None

    client._reconnect = _no_reconnect  # type: ignore[method-assign]
    await client._message_loop()
    await asyncio.sleep(0)
    assert client.connected is False
    assert reasons == ["recv_conflict"]
