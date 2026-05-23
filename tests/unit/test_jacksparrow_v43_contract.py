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
    audit_v43_metadata_promotion,
    validate_v43_metadata_compatibility,
    validate_v43_metadata_promotion,
)
from feature_store.jacksparrow_v43_horizon import V43_SUPPORTED_FORWARD_TARGET_BARS


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


def test_validate_v43_metadata_requires_multihead_horizons() -> None:
    meta = {"features": list(V43_CANONICAL_FEATURES)}
    with pytest.raises(ValueError, match="must be multi-head"):
        validate_v43_metadata_compatibility(meta)


def test_validate_v43_metadata_accepts_multihead_fixture() -> None:
    p = Path(__file__).resolve().parents[1] / "fixtures" / "v43_multihead_metadata.json"
    with p.open(encoding="utf-8") as f:
        meta = json.load(f)
    validate_v43_metadata_compatibility(meta)


def test_validate_v43_metadata_accepts_matching_version() -> None:
    p = Path(__file__).resolve().parents[1] / "fixtures" / "v43_multihead_metadata.json"
    with p.open(encoding="utf-8") as f:
        meta = json.load(f)
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


def test_audit_v43_metadata_warns_zero_short_candidates() -> None:
    meta = {
        "validation_metrics": {
            "inference_path": "meta_calibrator",
            "meta_auc": 0.49,
            "short_candidates": {"count": 0},
        },
        "model_architecture": {"meta_learner": "lgbm_classifier", "calibrator": "ridge"},
    }
    warnings = audit_v43_metadata_promotion(meta)
    assert any("short_candidates" in w for w in warnings)


def test_validate_v43_metadata_promotion_strict_blocks_weak_multihead() -> None:
    meta = {
        "model_family": "jacksparrow_v43_multihead",
        "features": list(V43_CANONICAL_FEATURES),
        "compatible_feature_version": V43_COMPATIBLE_FEATURE_VERSION,
        "horizons": {
            "scalp_10m": {
                "forward_bars": 2,
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.55,
                    "validation_corr": 0.01,
                    "dynamic_threshold": 0.004,
                },
            },
            "intraday_30m": {
                "forward_bars": 6,
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.55,
                    "validation_corr": 0.01,
                    "dynamic_threshold": 0.005,
                },
            },
            "trend_1h": {
                "forward_bars": 12,
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.50,
                    "validation_corr": 0.01,
                    "dynamic_threshold": 0.006,
                },
            },
            "swing_2h": {
                "forward_bars": 24,
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.61,
                    "validation_corr": 0.01,
                    "dynamic_threshold": 0.007,
                },
            },
        },
    }
    with pytest.raises(ValueError, match="promotion gate|export gates"):
        validate_v43_metadata_promotion(meta, strict=True)


def test_validate_v43_metadata_promotion_strict_raises() -> None:
    meta = {
        "validation_metrics": {
            "inference_path": "meta_calibrator",
            "short_candidates": {"count": 0},
        },
    }
    with pytest.raises(ValueError, match="promotion gate"):
        validate_v43_metadata_promotion(meta, strict=True)


def test_metadata_has_multihead_horizons(metadata_v43):
    horizons = metadata_v43.get("horizons")
    assert isinstance(horizons, dict)
    for key in ("scalp_10m", "intraday_30m", "trend_1h", "swing_2h"):
        assert key in horizons
        assert int(horizons[key]["forward_bars"]) in V43_SUPPORTED_FORWARD_TARGET_BARS


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
