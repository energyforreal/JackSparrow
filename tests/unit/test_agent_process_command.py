"""Unit tests for IntelligentAgent Redis command dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.intelligent_agent import IntelligentAgent


@pytest.fixture
def agent_with_registry():
    agent = IntelligentAgent.__new__(IntelligentAgent)
    agent.model_registry = MagicMock()
    agent.model_registry.register_pending_models.return_value = {
        "registered": ["model_a"],
        "not_found": [],
    }
    agent.model_registry.list_pending_models.return_value = []
    agent._send_response = AsyncMock()
    return agent


@pytest.mark.asyncio
async def test_process_command_register_models(agent_with_registry):
    await agent_with_registry._process_command(
        {
            "request_id": "req-1",
            "command": "register_models",
            "parameters": {"models": ["model_a", "model_b"]},
        }
    )
    agent_with_registry.model_registry.register_pending_models.assert_called_once_with(
        ["model_a", "model_b"]
    )
    agent_with_registry._send_response.assert_called_once()
    request_id, payload = agent_with_registry._send_response.call_args[0]
    assert request_id == "req-1"
    assert payload["registered"] == ["model_a"]


@pytest.mark.asyncio
async def test_process_command_unknown_does_not_call_register_models(agent_with_registry):
    await agent_with_registry._process_command(
        {
            "request_id": "req-2",
            "command": "unknown_cmd",
            "parameters": {},
        }
    )
    agent_with_registry.model_registry.register_pending_models.assert_not_called()
    _, payload = agent_with_registry._send_response.call_args[0]
    assert payload.get("success") is True
