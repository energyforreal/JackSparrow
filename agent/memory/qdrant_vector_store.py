"""Qdrant-backed vector memory store with in-memory fallback cache."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import structlog

from agent.memory.vector_store import DecisionContext, VectorMemoryStore
from feature_store.feature_registry import EXPECTED_FEATURE_COUNT

logger = structlog.get_logger()

EMBEDDING_DIM = EXPECTED_FEATURE_COUNT + 10


class QdrantVectorStore(VectorMemoryStore):
    """Persist decision contexts in Qdrant; delegate search to local cache when offline."""

    def __init__(
        self,
        max_memory_size: int = 10000,
        similarity_threshold: float = 0.5,
        *,
        collection_name: str = "decision_contexts",
        url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        super().__init__(max_memory_size=max_memory_size, similarity_threshold=similarity_threshold)
        self.collection_name = collection_name
        self.url = url or "http://localhost:6333"
        self.api_key = api_key
        self._client: Any = None
        self._qdrant_available = False

    async def initialize(self) -> None:
        """Connect to Qdrant and ensure collection exists."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels

            self._client = QdrantClient(url=self.url, api_key=self.api_key)
            collections = self._client.get_collections().collections
            names = {c.name for c in collections}
            if self.collection_name not in names:
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=EMBEDDING_DIM,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
            self._qdrant_available = True
            await self._hydrate_cache_from_qdrant()
            logger.info(
                "qdrant_vector_store_initialized",
                collection=self.collection_name,
                url=self.url,
                cached_contexts=len(self.contexts),
            )
        except Exception as e:
            self._qdrant_available = False
            logger.warning(
                "qdrant_vector_store_init_failed_using_memory_only",
                error=str(e),
                exc_info=True,
            )
        await super().initialize()

    async def _hydrate_cache_from_qdrant(self) -> None:
        """Load recent points into in-memory cache for compatibility with base helpers."""
        if not self._client or not self._qdrant_available:
            return
        try:
            records, _ = self._client.scroll(
                collection_name=self.collection_name,
                limit=self.max_memory_size,
                with_payload=True,
                with_vectors=False,
            )
            loaded: List[DecisionContext] = []
            for point in records or []:
                payload = point.payload or {}
                if not isinstance(payload, dict) or "context_id" not in payload:
                    continue
                try:
                    loaded.append(DecisionContext.from_dict(payload))
                except Exception:
                    continue
            loaded.sort(key=lambda c: c.timestamp)
            self.contexts = loaded[-self.max_memory_size :]
        except Exception as e:
            logger.warning("qdrant_hydrate_cache_failed", error=str(e))

    def _point_id(self, context_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, context_id))

    async def store_decision_context(self, context: DecisionContext) -> bool:
        stored = await super().store_decision_context(context)
        if not stored or not self._qdrant_available or not self._client:
            return stored
        try:
            if context.embedding is None:
                context.compute_embedding()
            vector = context.embedding.tolist() if context.embedding is not None else []
            if len(vector) != EMBEDDING_DIM:
                logger.warning(
                    "qdrant_embedding_dim_mismatch",
                    expected=EMBEDDING_DIM,
                    actual=len(vector),
                    context_id=context.context_id,
                )
                return stored
            from qdrant_client.http import models as qmodels

            self._client.upsert(
                collection_name=self.collection_name,
                points=[
                    qmodels.PointStruct(
                        id=self._point_id(context.context_id),
                        vector=vector,
                        payload=context.to_dict(),
                    )
                ],
            )
        except Exception as e:
            logger.warning(
                "qdrant_store_failed_memory_retained",
                context_id=context.context_id,
                error=str(e),
            )
        return stored

    async def update_context_outcome(self, context_id: str, outcome: Dict[str, Any]) -> bool:
        updated = await super().update_context_outcome(context_id, outcome)
        if not updated or not self._qdrant_available or not self._client:
            return updated
        context = await self.get_context_by_id(context_id)
        if not context:
            return updated
        try:
            from qdrant_client.http import models as qmodels

            self._client.upsert(
                collection_name=self.collection_name,
                points=[
                    qmodels.PointStruct(
                        id=self._point_id(context.context_id),
                        vector=context.embedding.tolist() if context.embedding is not None else [],
                        payload=context.to_dict(),
                    )
                ],
            )
        except Exception as e:
            logger.warning("qdrant_outcome_update_failed", context_id=context_id, error=str(e))
        return updated

    async def find_similar_contexts(
        self,
        query_context: DecisionContext,
        limit: int = 5,
        min_similarity: Optional[float] = None,
    ) -> List[Tuple[DecisionContext, float]]:
        if self._qdrant_available and self._client:
            try:
                if query_context.embedding is None:
                    query_context.compute_embedding()
                vector = query_context.embedding.tolist()
                hits = self._client.search(
                    collection_name=self.collection_name,
                    query_vector=vector,
                    limit=limit,
                    score_threshold=min_similarity or self.similarity_threshold,
                )
                results: List[Tuple[DecisionContext, float]] = []
                for hit in hits or []:
                    payload = hit.payload or {}
                    if not isinstance(payload, dict):
                        continue
                    try:
                        ctx = DecisionContext.from_dict(payload)
                        results.append((ctx, float(hit.score or 0.0)))
                    except Exception:
                        continue
                if results:
                    return results
            except Exception as e:
                logger.warning("qdrant_search_failed_fallback_memory", error=str(e))
        return await super().find_similar_contexts(
            query_context, limit=limit, min_similarity=min_similarity
        )

    async def get_health_status(self) -> Dict[str, Any]:
        base = await super().get_health_status()
        base["backend"] = "qdrant" if self._qdrant_available else "memory_fallback"
        base["qdrant_collection"] = self.collection_name
        base["qdrant_url"] = self.url
        return base
