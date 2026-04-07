"""v15 feature list sanity (names stable for pipeline metadata)."""

from feature_store.feature_registry import (
    V15_FEATURES_5M,
    V15_FEATURES_15M,
    V15_FEATURES_BY_TF,
    V15_ALL_UNIQUE_FEATURES,
)


def test_v15_tf_lists_nonempty() -> None:
    assert len(V15_FEATURES_5M) == 20
    assert len(V15_FEATURES_15M) == 20
    assert set(V15_FEATURES_BY_TF.keys()) == {"5m", "15m"}


def test_v15_union_covers_both() -> None:
    assert len(V15_ALL_UNIQUE_FEATURES) >= 20
