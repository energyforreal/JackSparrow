"""
Vector Memory Store - Store and retrieve similar decision contexts.

Uses vector embeddings to store historical decision contexts and retrieve
similar situations for enhanced reasoning and decision making.
"""

from typing import Dict, List, Any, Optional, Tuple
import asyncio
import numpy as np
from datetime import datetime, timedelta
import structlog
import json
import hashlib

from agent.data.feature_list import FEATURE_LIST, EXPECTED_FEATURE_COUNT
try:
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("sklearn not available - vector similarity will be limited")

logger = structlog.get_logger()


class DecisionContext:
    """Represents a decision context with features and outcome."""

    def __init__(self, context_id: str, symbol: str, timestamp: datetime,
                 features: Dict[str, float], market_context: Dict[str, Any],
                 decision: Dict[str, Any], outcome: Optional[Dict[str, Any]] = None):
        self.context_id = context_id
        self.symbol = symbol
        self.timestamp = timestamp
        self.features = features
        self.market_context = market_context
        self.decision = decision
        self.outcome = outcome
        self.embedding = None  # Will be computed later

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "context_id": self.context_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "features": self.features,
            "market_context": self.market_context,
            "decision": self.decision,
            "outcome": self.outcome,
            "embedding": self.embedding.tolist() if self.embedding is not None else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DecisionContext':
        """Create from dictionary."""
        context = cls(
            context_id=data["context_id"],
            symbol=data["symbol"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            features=data["features"],
            market_context=data["market_context"],
            decision=data["decision"],
            outcome=data["outcome"]
        )
        if data.get("embedding"):
            context.embedding = np.array(data["embedding"])
        return context

    def compute_embedding(self) -> np.ndarray:
        """Compute vector embedding from features and context."""
        # Create feature vector using canonical FEATURE_LIST order.
        # Missing features are filled with 0.0 to keep a fixed length.
        feature_values: List[float] = []
        for name in FEATURE_LIST:
            value = self.features.get(name, 0.0)
            try:
                feature_values.append(float(value))
            except (TypeError, ValueError):
                feature_values.append(0.0)

        # If extra ad-hoc features are present, ignore them so embeddings
        # remain aligned with the canonical schema.
        feature_vector = np.array(feature_values, dtype=np.float32)

        # Add market context factors
        context_factors = self._extract_context_factors()
        context_vector = np.array(context_factors, dtype=np.float32)

        # Combine features and context
        combined_vector = np.concatenate([feature_vector, context_vector])

        # Normalize the embedding
        norm = np.linalg.norm(combined_vector)
        if norm > 0:
            combined_vector = combined_vector / norm

        self.embedding = combined_vector
        return self.embedding

    def _extract_context_factors(self) -> List[float]:
        """Extract numerical factors from market context."""
        factors = []

        # Volatility (0-1 scale, higher = more volatile)
        volatility = self.market_context.get("volatility", 0.02)
        factors.append(min(1.0, volatility * 50))  # Normalize to 0-1

        # Market regime (encode as one-hot style)
        regime = self.market_context.get("market_regime", "neutral")
        regime_factors = [0.0, 0.0, 0.0]  # [bull, bear, neutral]
        if regime == "bull":
            regime_factors[0] = 1.0
        elif regime == "bear":
            regime_factors[1] = 1.0
        else:
            regime_factors[2] = 1.0
        factors.extend(regime_factors)

        # Trend strength (0-1 scale)
        trend_strength = self.market_context.get("trend_strength", 0.5)
        factors.append(max(0.0, min(1.0, trend_strength)))

        # Time of day factors (cyclical encoding)
        hour = self.timestamp.hour
        factors.append(np.sin(2 * np.pi * hour / 24))  # Sine component
        factors.append(np.cos(2 * np.pi * hour / 24))  # Cosine component

        # Pad to fixed length if needed
        while len(factors) < 10:  # Ensure minimum length
            factors.append(0.0)

        return factors[:10]  # Truncate if too long


class VectorMemoryStore:
    """
    Vector-based memory store for decision contexts.

    Stores decision contexts as vector embeddings and enables similarity search
    to find similar historical situations for enhanced decision making.
    """

    def __init__(self, max_memory_size: int = 10000, similarity_threshold: float = 0.8):
        self.contexts: List[DecisionContext] = []
        self.max_memory_size = max_memory_size
        self.similarity_threshold = similarity_threshold
        self._initialized = False

        if not SKLEARN_AVAILABLE:
            logger.warning("vector_store_sklearn_unavailable",
                         message="Scikit-learn not available - similarity search will be limited")

    async def initialize(self):
        """Initialize vector memory store."""
        self._initialized = True
        logger.info("vector_memory_store_initialized",
                   max_size=self.max_memory_size,
                   similarity_threshold=self.similarity_threshold)

    async def shutdown(self):
        """Shutdown vector memory store."""
        self._initialized = False
        logger.info("vector_memory_store_shutdown")

    async def store_decision_context(self, context: DecisionContext) -> bool:
        """
        Store a decision context in vector memory.

        Args:
            context: DecisionContext to store

        Returns:
            bool: True if stored successfully
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Compute embedding if not already computed
            if context.embedding is None:
                context.compute_embedding()

            # Store context
            self.contexts.append(context)

            # Maintain memory size limit (remove oldest)
            if len(self.contexts) > self.max_memory_size:
                removed = self.contexts.pop(0)
                logger.debug("vector_memory_context_evicted",
                           context_id=removed.context_id,
                           total_contexts=len(self.contexts))

            logger.debug("decision_context_stored",
                        context_id=context.context_id,
                        total_contexts=len(self.contexts))

            return True

        except Exception as e:
            logger.error("vector_memory_store_failed",
                        context_id=context.context_id,
                        error=str(e))
            return False

    async def find_similar_contexts(self, query_context: DecisionContext,
                                  limit: int = 5,
                                  min_similarity: Optional[float] = None) -> List[Tuple[DecisionContext, float]]:
        """
        Find similar decision contexts using vector similarity.

        Args:
            query_context: Context to find similar contexts for
            limit: Maximum number of similar contexts to return
            min_similarity: Minimum similarity threshold (overrides default)

        Returns:
            List of (context, similarity_score) tuples
        """
        if not self._initialized:
            await self.initialize()

        if not self.contexts:
            logger.debug("vector_memory_empty", message="No contexts stored yet")
            return []

        try:
            # Compute query embedding
            if query_context.embedding is None:
                query_context.compute_embedding()

            query_embedding = query_context.embedding.reshape(1, -1)

            # Calculate similarities with all stored contexts
            similarities = []

            for context in self.contexts:
                if context.embedding is not None:
                    context_embedding = context.embedding.reshape(1, -1)

                    # Skip contexts whose embedding dimension doesn't match the query.
                    # This can happen if older contexts were stored before FEATURE_LIST
                    # was standardized or after schema changes.
                    if context_embedding.shape[1] != query_embedding.shape[1]:
                        logger.warning(
                            "vector_memory_embedding_dim_mismatch",
                            query_context_id=query_context.context_id,
                            context_id=context.context_id,
                            query_dim=int(query_embedding.shape[1]),
                            context_dim=int(context_embedding.shape[1]),
                        )
                        continue

                    if SKLEARN_AVAILABLE:
                        similarity = cosine_similarity(query_embedding, context_embedding)[0][0]
                    else:
                        # Fallback: Euclidean distance (convert to similarity)
                        distance = np.linalg.norm(query_embedding - context_embedding)
                        similarity = max(0.0, 1.0 - distance)  # Convert distance to similarity

                    similarities.append((context, float(similarity)))

            # Filter by similarity threshold
            threshold = min_similarity if min_similarity is not None else self.similarity_threshold
            similarities = [(ctx, sim) for ctx, sim in similarities if sim >= threshold]

            # Sort by similarity (highest first) and limit results
            similarities.sort(key=lambda x: x[1], reverse=True)
            results = similarities[:limit]

            logger.debug("similar_contexts_found",
                        query_context_id=query_context.context_id,
                        results_found=len(results),
                        min_similarity=threshold)

            return results

        except Exception as e:
            logger.error("vector_memory_similarity_search_failed",
                        query_context_id=query_context.context_id,
                        error=str(e))
            return []

    async def get_context_by_id(self, context_id: str) -> Optional[DecisionContext]:
        """Retrieve a specific context by ID."""
        for context in self.contexts:
            if context.context_id == context_id:
                return context
        return None

    async def update_context_outcome(self, context_id: str, outcome: Dict[str, Any]) -> bool:
        """
        Update the outcome of a stored decision context.

        Args:
            context_id: ID of context to update
            outcome: Trade outcome information

        Returns:
            bool: True if updated successfully
        """
        context = await self.get_context_by_id(context_id)
        if context:
            context.outcome = outcome
            logger.debug("context_outcome_updated", context_id=context_id)
            return True

        logger.warning("context_not_found_for_update", context_id=context_id)
        return False

    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory store statistics."""
        if not self.contexts:
            return {"total_contexts": 0, "memory_usage": "empty"}

        # Calculate basic stats
        stats = {
            "total_contexts": len(self.contexts),
            "max_memory_size": self.max_memory_size,
            "memory_utilization": len(self.contexts) / self.max_memory_size,
            "similarity_threshold": self.similarity_threshold
        }

        # Symbol distribution
        symbols = {}
        for context in self.contexts:
            symbols[context.symbol] = symbols.get(context.symbol, 0) + 1
        stats["symbol_distribution"] = symbols

        # Time range
        if self.contexts:
            timestamps = [c.timestamp for c in self.contexts]
            stats["oldest_context"] = min(timestamps).isoformat()
            stats["newest_context"] = max(timestamps).isoformat()

        # Outcomes available
        outcomes_available = sum(1 for c in self.contexts if c.outcome is not None)
        stats["contexts_with_outcomes"] = outcomes_available
        stats["outcome_completion_rate"] = outcomes_available / len(self.contexts)

        return stats

    async def get_similar_decisions_with_outcomes(self, query_context: DecisionContext,
                                                limit: int = 5) -> List[Tuple[DecisionContext, float]]:
        """
        Find similar contexts that have known outcomes.

        Useful for learning from past decisions.
        """
        similar_contexts = await self.find_similar_contexts(query_context, limit=limit * 2)
        contexts_with_outcomes = [(ctx, sim) for ctx, sim in similar_contexts if ctx.outcome is not None]

        # Return top matches with outcomes
        return contexts_with_outcomes[:limit]

    async def analyze_decision_patterns(self, symbol: Optional[str] = None,
                                      days_back: int = 30) -> Dict[str, Any]:
        """
        Analyze decision patterns in stored memory.

        Args:
            symbol: Specific symbol to analyze (None for all)
            days_back: How many days of history to analyze

        Returns:
            Analysis of decision patterns and outcomes
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        # Filter contexts
        relevant_contexts = [
            ctx for ctx in self.contexts
            if ctx.timestamp >= cutoff_date and (symbol is None or ctx.symbol == symbol)
        ]

        if not relevant_contexts:
            return {"error": "No contexts found for analysis"}

        # Analyze decision distribution
        decisions = {}
        outcomes = {"profitable": 0, "unprofitable": 0, "unknown": 0}

        for context in relevant_contexts:
            decision = context.decision.get("signal", "UNKNOWN")
            decisions[decision] = decisions.get(decision, 0) + 1

            if context.outcome:
                pnl = context.outcome.get("pnl", 0)
                if pnl > 0:
                    outcomes["profitable"] += 1
                else:
                    outcomes["unprofitable"] += 1
            else:
                outcomes["unknown"] += 1

        # Calculate success rates by decision type
        success_by_decision = {}
        for decision_type in decisions.keys():
            decision_contexts = [ctx for ctx in relevant_contexts
                               if ctx.decision.get("signal") == decision_type]

            profitable = sum(1 for ctx in decision_contexts
                           if ctx.outcome and ctx.outcome.get("pnl", 0) > 0)

            total_with_outcome = sum(1 for ctx in decision_contexts if ctx.outcome)

            if total_with_outcome > 0:
                success_rate = profitable / total_with_outcome
            else:
                success_rate = 0.0

            success_by_decision[decision_type] = {
                "count": len(decision_contexts),
                "profitable": profitable,
                "success_rate": success_rate
            }

        return {
            "analysis_period_days": days_back,
            "symbol": symbol or "ALL",
            "total_contexts": len(relevant_contexts),
            "decision_distribution": decisions,
            "outcome_distribution": outcomes,
            "success_by_decision": success_by_decision,
            "overall_success_rate": outcomes["profitable"] / (outcomes["profitable"] + outcomes["unprofitable"])
                                   if (outcomes["profitable"] + outcomes["unprofitable"]) > 0 else 0.0
        }

    async def clear_memory(self, older_than_days: Optional[int] = None) -> int:
        """
        Clear old contexts from memory.

        Args:
            older_than_days: Clear contexts older than this many days (None to clear all)

        Returns:
            Number of contexts removed
        """
        if older_than_days is None:
            removed_count = len(self.contexts)
            self.contexts.clear()
        else:
            cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
            original_count = len(self.contexts)
            self.contexts = [ctx for ctx in self.contexts if ctx.timestamp >= cutoff_date]
            removed_count = original_count - len(self.contexts)

        logger.info("vector_memory_cleared",
                   removed_count=removed_count,
                   remaining_count=len(self.contexts))

        return removed_count

    async def get_health_status(self) -> Dict[str, Any]:
        """Get vector memory store health status."""
        stats = await self.get_memory_stats()

        health_status = "healthy"
        issues = []

        if len(self.contexts) == 0:
            health_status = "initializing"
            issues.append("No contexts stored yet")

        if len(self.contexts) < 10:
            issues.append("Low context count - similarity search may be limited")

        if not SKLEARN_AVAILABLE:
            health_status = "degraded"
            issues.append("Scikit-learn not available - using fallback similarity")

        memory_usage = len(self.contexts) / self.max_memory_size
        if memory_usage > 0.9:
            health_status = "warning"
            issues.append("Memory usage above 90%")

        return {
            "status": health_status,
            "issues": issues,
            "stats": stats,
            "initialized": self._initialized
        }