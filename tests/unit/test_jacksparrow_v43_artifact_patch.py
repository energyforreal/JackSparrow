"""Unit tests for JackSparrow v43 artifact threshold patch and regime merge."""

from __future__ import annotations

from agent.models.jack_sparrow_v43_node import (
    _apply_v43_threshold_patch,
    _merge_regime_models,
)


class _LgbmMock:
    def __init__(self) -> None:
        self.dynamic_threshold = 0.010957
        self.regime_thresholds = {"ranging": 0.05, "neutral": 0.05, "crisis": 0.05}


class _EnsMock:
    def __init__(self) -> None:
        self.lgbm_model = _LgbmMock()
        self.threshold = 0.05


def test_threshold_patch_replaces_floored_regime_thresholds():
    art = {"model": _EnsMock(), "metrics": {"cv_auc_mean": 0.7}}
    assert _apply_v43_threshold_patch(art) is True
    lgbm = art["model"].lgbm_model
    assert abs(float(lgbm.regime_thresholds["neutral"]) - 0.010957) < 1e-6
    assert abs(float(art["model"].threshold) - 0.010957) < 1e-6


def test_threshold_patch_idempotent_after_calibration():
    art = {"model": _EnsMock(), "metrics": {}}
    _apply_v43_threshold_patch(art)
    assert _apply_v43_threshold_patch(art) is False


def test_merge_regime_models_file_wins():
    artifact = {"regime_models": {"neutral": {"model": "a"}, "ranging": {"model": "b"}}}
    file_rm = {"neutral": {"model": "from_file"}}
    merged = _merge_regime_models(artifact, file_rm)
    assert merged["neutral"]["model"] == "from_file"
    assert merged["ranging"]["model"] == "b"


def test_get_signal_threshold_prefers_dynamic_when_regime_buggy():
    from agent.models.jacksparrow_v43_inference import get_signal_threshold

    class _BadLgbm:
        dynamic_threshold = 0.011

    class _Ens:
        lgbm_model = _BadLgbm()

    class _Active:
        regime_thresholds = {"neutral": 0.05}

    thr = get_signal_threshold("neutral", _Ens(), _Active(), floor=0.005)
    assert abs(thr - 0.011) < 1e-9
