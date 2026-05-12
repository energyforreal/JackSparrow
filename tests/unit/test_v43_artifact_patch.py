"""Unit tests for v43 artifact threshold patch and regime merge helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from agent.models.jack_sparrow_v43_node import (
    _apply_v43_threshold_patch,
    _merge_regime_models,
)

def _fake_artifact_with_regime_thr(
    regime_vals: Dict[str, float], dynamic_thr: float
) -> Dict[str, Any]:
    lgbm = SimpleNamespace(
        regime_thresholds=dict(regime_vals),
        dynamic_threshold=dynamic_thr,
    )
    model = SimpleNamespace(lgbm_model=lgbm, threshold=0.05)
    return {"model": model, "metrics": {"f1": 0.5}}


def test_threshold_patch_rewrites_stale_regime_thresholds() -> None:
    art = _fake_artifact_with_regime_thr(
        {"neutral": 0.05, "ranging": 0.05}, dynamic_thr=0.011
    )
    assert _apply_v43_threshold_patch(art) is True
    lgbm = art["model"].lgbm_model
    assert all(abs(float(v) - 0.011) < 1e-9 for v in lgbm.regime_thresholds.values())
    assert abs(float(art["model"].threshold) - 0.011) < 1e-9
    rm = art.get("regime_models") or {}
    assert "ranging" in rm


def test_threshold_patch_noop_when_regimes_already_low() -> None:
    art = _fake_artifact_with_regime_thr({"neutral": 0.012}, dynamic_thr=0.011)
    assert _apply_v43_threshold_patch(art) is False


def test_merge_regime_models_file_wins_on_overlap() -> None:
    artifact = {"regime_models": {"neutral": "a", "ranging": "b"}}
    file_rm = {"ranging": "file", "crisis": "c"}
    merged = _merge_regime_models(artifact, file_rm)
    assert merged["neutral"] == "a"
    assert merged["ranging"] == "file"
    assert merged["crisis"] == "c"


def test_merge_regime_models_sidecar_none() -> None:
    artifact = {"regime_models": {"x": 1}}
    assert _merge_regime_models(artifact, None) == {"x": 1}
