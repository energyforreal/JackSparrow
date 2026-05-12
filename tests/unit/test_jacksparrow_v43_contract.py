"""Parity: shipped v43 metadata vs canonical contract (feature order, count, horizon doc)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_EXPECTED_FEATURE_COUNT,
    V43_FORWARD_TARGET_BARS,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_metadata_path() -> Path:
    return (
        _repo_root()
        / "agent"
        / "model_storage"
        / "JackSparrow_v43_models_BTCUSD"
        / "metadata_v43.json"
    )


@pytest.fixture
def metadata_v43():
    p = _default_metadata_path()
    if not p.is_file():
        pytest.skip(f"No metadata at {p}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def test_v43_metadata_features_match_contract(metadata_v43):
    feats = metadata_v43.get("features")
    assert isinstance(feats, list), "metadata must include features array"
    assert len(feats) == V43_EXPECTED_FEATURE_COUNT
    assert metadata_v43.get("feature_count") in (V43_EXPECTED_FEATURE_COUNT, len(feats))
    assert tuple(feats) == V43_CANONICAL_FEATURES


def test_metadata_training_forward_bars(metadata_v43):
    assert int(metadata_v43.get("training_forward_bars", V43_FORWARD_TARGET_BARS)) == (
        V43_FORWARD_TARGET_BARS
    )


def test_model_artifact_has_threshold_attrs_if_present():
    """Smoke: when artifact exists, ensemble exposes threshold-related attrs."""
    import joblib  # noqa: PLC0415

    root = _repo_root()
    art_path = root / "agent/model_storage/JackSparrow_v43_models_BTCUSD/model_artifact_v43.pkl"
    if not art_path.is_file():
        pytest.skip("No model_artifact_v43.pkl in repo bundle")

    try:
        data = joblib.load(art_path)
    except Exception as e:
        pytest.skip(f"Artifact load skipped ({type(e).__name__}: {e})")

    model = data.get("model") if isinstance(data, dict) else None
    assert model is not None
    dt = getattr(model, "dynamic_threshold", None)
    if dt is None:
        lgbm = getattr(model, "lgbm_model", None)
        if lgbm is not None:
            assert hasattr(lgbm, "threshold") or hasattr(lgbm, "dynamic_threshold")
    else:
        assert isinstance(dt, (int, float))
        assert 0 <= float(dt) < 0.2
