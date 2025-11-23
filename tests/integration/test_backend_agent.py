"""Integration tests for backend-agent communication."""

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from contextlib import suppress
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

# Provide minimal config so backend/agent settings can initialize during tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("API_KEY", "test-api-key")

from backend.services.agent_service import AgentService
from agent.core.intelligent_agent import IntelligentAgent

class FakeRedis:
    """Minimal async Redis stub for integration tests."""

    def __init__(self):
        self._kv = {}
        self._expiry = {}
        self._lists = defaultdict(deque)

    async def lpush(self, key: str, value: str):
        self._lists[key].appendleft(value)

    async def brpop(self, key: str, timeout: int = 0):
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            queue = self._lists[key]
            if queue:
                return key, queue.pop()
            if deadline is not None and time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.01)

    async def setex(self, key: str, ttl: int, value: str):
        self._kv[key] = value
        self._expiry[key] = time.monotonic() + ttl

    async def get(self, key: str):
        expires_at = self._expiry.get(key)
        if expires_at is not None and time.monotonic() > expires_at:
            self._kv.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._kv.get(key)

    async def delete(self, key: str):
        self._kv.pop(key, None)
        self._expiry.pop(key, None)

    async def close(self):
        return True

    async def ping(self):
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    """Provide a shared FakeRedis instance for backend and agent modules."""

    redis = FakeRedis()

    async def _get_backend(required: bool = False):
        return redis

    async def _get_agent():
        return redis

    # Backend patches
    monkeypatch.setattr("backend.core.redis._redis_client", redis)
    monkeypatch.setattr("backend.core.redis._redis_connection_failed", False)
    monkeypatch.setattr("backend.core.redis.get_redis", _get_backend)

    # Agent patches
    monkeypatch.setattr("agent.core.redis._redis_client", redis)
    monkeypatch.setattr("agent.core.redis.get_redis", _get_agent)

    return redis


@pytest_asyncio.fixture
async def running_agent(fake_redis, monkeypatch):
    """Spin up a lightweight IntelligentAgent command handler."""

    agent = IntelligentAgent()
    agent.running = True

    # Avoid hitting the full event infrastructure during tests
    monkeypatch.setattr(
        "agent.core.intelligent_agent.event_bus.publish",
        AsyncMock(return_value=True),
    )

    def _predict_side_effect(params):
        return {
            "success": True,
            "data": {"signal": "BUY", "confidence": 0.9, "context": params},
        }

    def _control_side_effect(params):
        return {
            "success": True,
            "data": {"state": "OBSERVING", "action": params.get("action")},
        }

    monkeypatch.setattr(agent, "_handle_predict", AsyncMock(side_effect=_predict_side_effect))
    monkeypatch.setattr(agent, "_handle_control", AsyncMock(side_effect=_control_side_effect))
    monkeypatch.setattr(agent, "_handle_execute_trade", AsyncMock(return_value={"success": True}))
    monkeypatch.setattr(agent, "_handle_get_status", AsyncMock(return_value={"success": True}))

    original_send_response = agent._send_response
    sent_responses = []

    async def _wrapped_send_response(request_id: str, payload: dict, ttl: int = 120):
        sent_responses.append((request_id, payload))
        await original_send_response(request_id, payload, ttl)

    agent._test_responses = sent_responses
    monkeypatch.setattr(agent, "_send_response", _wrapped_send_response)

    task = asyncio.create_task(agent._command_handler())
    yield agent

    agent.running = False
    # Unblock brpop quickly
    await fake_redis.lpush(agent.command_queue, json.dumps({"command": "noop"}))
    await asyncio.sleep(0.05)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class TestBackendAgentIntegration:
    """Tests for backend-agent integration."""

    @pytest.mark.asyncio
    async def test_prediction_round_trip(self, fake_redis, running_agent):
        """Ensure predictions travel through Redis queues and return a response."""

        agent = running_agent
        service = AgentService()
        result = await service.get_prediction(symbol="BTCUSD", context={"foo": "bar"})

        assert result is not None, f"Redis keys={list(fake_redis._kv.keys())}, responses={agent._test_responses}"
        assert result["success"] is True
        assert result["data"]["signal"] == "BUY"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_control_command_round_trip(self, fake_redis, running_agent):
        """Ensure control commands receive responses through the same channel."""

        agent = running_agent
        service = AgentService()
        response = await service.control_agent(action="start", parameters={})

        assert response is not None, f"Redis keys={list(fake_redis._kv.keys())}, responses={agent._test_responses}"
        assert response["success"] is True
        assert response["data"]["state"] == "OBSERVING"
        assert response["data"]["action"] == "start"

