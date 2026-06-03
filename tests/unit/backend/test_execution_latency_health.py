"""Tests for execution latency health reporting."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routes.health import check_execution_latency_metrics


@pytest.mark.asyncio
async def test_execution_latency_idle_shows_up():
    payload = {
        "risk_approved_to_fill_ms": {"count": 0, "p50": None, "p95": None, "max": None},
        "published_at": "2026-06-03T00:00:00+00:00",
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=json.dumps(payload))

    with patch("backend.api.routes.health.get_redis", AsyncMock(return_value=mock_client)):
        result = await check_execution_latency_metrics()

    assert result.status == "up"
    assert result.latency_ms is None
    assert "idle" in (result.details or {}).get("note", "").lower()


@pytest.mark.asyncio
async def test_execution_latency_with_samples_sets_p50():
    payload = {
        "risk_approved_to_fill_ms": {"count": 5, "p50": 42.0, "p95": 88.0, "max": 100.0},
        "published_at": "2026-06-03T00:00:00+00:00",
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=json.dumps(payload))

    with patch("backend.api.routes.health.get_redis", AsyncMock(return_value=mock_client)):
        result = await check_execution_latency_metrics()

    assert result.status == "up"
    assert result.latency_ms == 42.0


@pytest.mark.asyncio
async def test_execution_latency_missing_key_unknown():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)

    with patch("backend.api.routes.health.get_redis", AsyncMock(return_value=mock_client)):
        result = await check_execution_latency_metrics()

    assert result.status == "unknown"
