"""Redis cache helpers when client is unavailable."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.core import redis_config as rc


@pytest.mark.asyncio
async def test_get_cache_returns_none_when_redis_unavailable() -> None:
    with patch.object(rc, "get_redis", AsyncMock(return_value=None)):
        assert await rc.get_cache("k") is None


@pytest.mark.asyncio
async def test_set_cache_returns_false_when_redis_unavailable() -> None:
    with patch.object(rc, "get_redis", AsyncMock(return_value=None)):
        assert await rc.set_cache("k", {"a": 1}) is False
