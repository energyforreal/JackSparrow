"""Tests for vector store factory selection."""

from __future__ import annotations

import pytest

from agent.memory.vector_store import VectorMemoryStore
from agent.memory.vector_store_factory import create_vector_store


@pytest.mark.asyncio
async def test_create_vector_store_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_VECTOR_STORE_BACKEND", "memory")

    from agent.core import config as config_module

    config_module.settings = config_module.Settings()

    store = await create_vector_store()
    assert isinstance(store, VectorMemoryStore)
    stats = await store.get_memory_stats()
    assert "total_contexts" in stats


@pytest.mark.asyncio
async def test_create_vector_store_qdrant_fallback(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_VECTOR_STORE_BACKEND", "qdrant")
    monkeypatch.setenv("QDRANT_URL", "http://invalid-host:6333")

    from agent.core import config as config_module

    config_module.settings = config_module.Settings()

    store = await create_vector_store()
    assert isinstance(store, VectorMemoryStore)
