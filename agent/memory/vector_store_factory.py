"""Factory for vector memory backends (in-memory or Qdrant)."""

from __future__ import annotations

from typing import Any

import structlog

from agent.core.config import settings
from agent.memory.vector_store import VectorMemoryStore

logger = structlog.get_logger()


async def create_vector_store() -> Any:
    """Create configured vector memory store with safe fallback to in-memory."""
    backend = str(getattr(settings, "agent_vector_store_backend", "memory") or "memory").lower()
    max_size = int(getattr(settings, "agent_vector_store_max_size", 10000) or 10000)
    threshold = float(getattr(settings, "agent_vector_store_similarity_threshold", 0.5) or 0.5)

    if backend == "qdrant":
        try:
            from agent.memory.qdrant_vector_store import QdrantVectorStore

            store = QdrantVectorStore(
                max_memory_size=max_size,
                similarity_threshold=threshold,
                collection_name=str(
                    getattr(settings, "agent_vector_store_qdrant_collection", "decision_contexts_v43")
                    or "decision_contexts_v43"
                ),
                url=getattr(settings, "qdrant_url", None),
                api_key=getattr(settings, "qdrant_api_key", None),
            )
            await store.initialize()
            logger.info(
                "vector_store_backend_selected",
                backend="qdrant",
                collection=store.collection_name,
            )
            return store
        except Exception as e:
            logger.warning(
                "vector_store_qdrant_fallback_to_memory",
                error=str(e),
                exc_info=True,
            )

    store = VectorMemoryStore(max_memory_size=max_size, similarity_threshold=threshold)
    await store.initialize()
    logger.info("vector_store_backend_selected", backend="memory")
    return store
