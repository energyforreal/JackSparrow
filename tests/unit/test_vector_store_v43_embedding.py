"""Vector memory embeddings must use V43 canonical feature order (dim 63)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from agent.memory.vector_store import DecisionContext, EXPECTED_FEATURE_COUNT
from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES


def test_v43_expected_feature_count() -> None:
    assert EXPECTED_FEATURE_COUNT == len(V43_CANONICAL_FEATURES) == 53


def test_compute_embedding_length_and_nonzero_mass() -> None:
    features = {name: float(i + 1) for i, name in enumerate(V43_CANONICAL_FEATURES)}
    ctx = DecisionContext(
        context_id="v43-embed-test",
        symbol="BTCUSD",
        timestamp=datetime.now(timezone.utc),
        features=features,
        market_context={"volatility": 0.02, "market_regime": "neutral"},
        decision={"signal": "BUY", "confidence": 0.7},
    )
    embedding = ctx.compute_embedding()
    assert embedding is not None
    assert len(embedding) == EXPECTED_FEATURE_COUNT + 10
    assert np.count_nonzero(embedding) > 10
    feature_slice = embedding[:EXPECTED_FEATURE_COUNT]
    assert np.count_nonzero(feature_slice) == EXPECTED_FEATURE_COUNT
