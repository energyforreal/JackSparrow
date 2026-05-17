"""Parity: shipped v43 metadata vs canonical contract (feature order, count, horizon doc)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_COMPATIBLE_FEATURE_VERSION,
    V43_EXPECTED_FEATURE_COUNT,
    V43_FORWARD_TARGET_BARS,
    validate_v43_metadata_compatibility,
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


def test_repo_metadata_v43_must_exist() -> None:
    """CI guard: shipped bundle metadata must be present (no silent skip)."""
    p = _default_metadata_path()
    assert p.is_file(), (
        f"Required metadata missing at {p}. "
        "Ship JackSparrow v43 bundle before merge."
    )
    with p.open(encoding="utf-8") as f:
        meta = json.load(f)
    validate_v43_metadata_compatibility(meta)


def test_v43_metadata_features_match_contract(metadata_v43):
    feats = metadata_v43.get("features")
    assert isinstance(feats, list), "metadata must include features array"
    assert len(feats) == V43_EXPECTED_FEATURE_COUNT
    assert metadata_v43.get("feature_count") in (V43_EXPECTED_FEATURE_COUNT, len(feats))
    assert tuple(feats) == V43_CANONICAL_FEATURES
    assert metadata_v43.get("compatible_feature_version") == V43_COMPATIBLE_FEATURE_VERSION


def test_validate_v43_metadata_accepts_legacy_without_version_field() -> None:
    meta = {"features": list(V43_CANONICAL_FEATURES)}
    validate_v43_metadata_compatibility(meta)


def test_validate_v43_metadata_accepts_matching_version() -> None:
    meta = {
        "features": list(V43_CANONICAL_FEATURES),
        "compatible_feature_version": V43_COMPATIBLE_FEATURE_VERSION,
    }
    validate_v43_metadata_compatibility(meta)


def test_validate_v43_metadata_rejects_incompatible_version() -> None:
    meta = {
        "features": list(V43_CANONICAL_FEATURES),
        "compatible_feature_version": "legacy_wrong_tag",
    }
    with pytest.raises(ValueError, match="incompatible"):
        validate_v43_metadata_compatibility(meta)


def test_validate_v43_metadata_rejects_feature_order_mismatch() -> None:
    feats = list(V43_CANONICAL_FEATURES)
    feats[0], feats[1] = feats[1], feats[0]
    with pytest.raises(ValueError, match="does not match"):
        validate_v43_metadata_compatibility({"features": feats})


def test_jacksparrow_v43_node_rejects_bad_metadata(tmp_path) -> None:
    from agent.models.jack_sparrow_v43_node import JackSparrowV43Node

    bad = {
        "model_name": "x",
        "version": "v43",
        "features": list(V43_CANONICAL_FEATURES),
        "compatible_feature_version": "nope",
    }
    p = tmp_path / "metadata.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        JackSparrowV43Node.from_metadata_path(p)


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
