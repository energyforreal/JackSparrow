"""Tests for fusion Gradient SHAP grouping and stub entry point."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest
import torch

from feature_store.transformer_btcusd.contract import FUSION_INPUT_RESOLUTIONS
from scripts.colab.mtf_fusion_model import MtfFusionTransformer
from scripts.colab.mtf_fusion_research import (
    StackedHorizonScorer,
    _shap_values_to_array,
    fusion_feature_groups,
    optuna_search,
    shap_grouped_stub,
)


def test_fusion_feature_groups_candle_chart_htf() -> None:
    cols = [
        "cdl_hammer",
        "body_ratio",
        "chp_double_top",
        "sr_at_support",
        "tl_trend_slope",
        "ema50_dist_pct",
        "rsi_14",
        "rv_16",
        "ret_1",
    ]
    groups = fusion_feature_groups(cols)
    assert "cdl_hammer" in groups["candle"]
    assert "body_ratio" in groups["candle"]
    assert "chp_double_top" in groups["chart"]
    assert "sr_at_support" in groups["chart"]
    assert "tl_trend_slope" in groups["chart"]
    assert "ema50_dist_pct" in groups["trend"]
    assert "rsi_14" in groups["trend"]
    assert "rv_16" in groups["vol"]
    assert "ret_1" in groups["other"]
    assert groups["htf_resample"] == []


def test_fusion_feature_groups_rejects_htf() -> None:
    with pytest.raises(RuntimeError, match="htf_"):
        fusion_feature_groups(["rsi_14", "htf_30m_rsi"])


def test_shap_disabled_lists_groups_without_explainer(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = {"n": 0}

    class Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            constructed["n"] += 1
            raise AssertionError("GradientExplainer must not run when disabled")

    fake = types.ModuleType("shap")
    fake.GradientExplainer = Boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)

    report = shap_grouped_stub(
        ["cdl_hammer", "rsi_14", "rv_16", "ret_1"],
        enabled=False,
    )
    assert report["enabled"] is False
    assert report["ok"] is False
    assert constructed["n"] == 0
    assert "cdl_hammer" in report["groups"]["candle"]
    assert report["horizons"] == {}


def test_shap_enabled_returns_nonneg_importances(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeExplainer:
        def __init__(self, model: object, data: object) -> None:
            self.model = model

        def shap_values(self, x: object, **kwargs: object) -> np.ndarray:
            if torch.is_tensor(x):
                shape = tuple(int(d) for d in x.shape)
            else:
                shape = tuple(np.asarray(x).shape)
            return np.ones(shape, dtype=np.float64)

    fake = types.ModuleType("shap")
    fake.GradientExplainer = FakeExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)

    n_feat = 4
    cols = ["cdl_hammer", "chp_bull_flag", "rsi_14", "rv_16"]
    window_len = 8
    n = 12
    model = MtfFusionTransformer(n_features=n_feat, max_len=window_len)
    windows = {
        res: np.random.randn(n, window_len, n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    report = shap_grouped_stub(
        cols,
        enabled=True,
        model=model,
        val_windows=windows,
        device=torch.device("cpu"),
        config={"shap_background": 4, "shap_explain_n": 6, "seed": 0},
    )
    assert report["enabled"] is True
    assert report["ok"] is True
    assert report["split"] == "val"
    assert set(report["groups"]["candle"]) == {"cdl_hammer"}
    for key, row in report["horizons"].items():
        assert row["ok"] is True, key
        feats = row["features"]
        assert list(feats.keys()) == cols
        assert all(float(v) >= 0.0 for v in feats.values())
        assert len(feats) == len(cols)
        assert "candle" in row["groups"]
        assert float(row["groups"]["candle"]) >= 0.0


def test_shap_values_squeeze_rank5_singleton() -> None:
    """Colab GradientExplainer returned (B, 1, n_tf, T, F); coerce to rank 4."""
    raw = np.ones((6, 1, 5, 8, 4), dtype=np.float64)
    arr = _shap_values_to_array(raw)
    assert arr.shape == (6, 5, 8, 4)


def test_shap_enabled_accepts_rank5_explainer(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeExplainer:
        def __init__(self, model: object, data: object) -> None:
            self.model = model

        def shap_values(self, x: object, **kwargs: object) -> np.ndarray:
            if torch.is_tensor(x):
                b, n_tf, t, f = (int(d) for d in x.shape)
            else:
                b, n_tf, t, f = np.asarray(x).shape
            return np.ones((b, 1, n_tf, t, f), dtype=np.float64)

    fake = types.ModuleType("shap")
    fake.GradientExplainer = FakeExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)

    n_feat = 4
    cols = ["cdl_hammer", "chp_bull_flag", "rsi_14", "rv_16"]
    window_len = 8
    n = 12
    model = MtfFusionTransformer(n_features=n_feat, max_len=window_len)
    windows = {
        res: np.random.randn(n, window_len, n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    report = shap_grouped_stub(
        cols,
        enabled=True,
        model=model,
        val_windows=windows,
        device=torch.device("cpu"),
        config={"shap_background": 4, "shap_explain_n": 6, "seed": 0},
    )
    assert report["ok"] is True
    for row in report["horizons"].values():
        assert row["ok"] is True
        assert len(row["features"]) == len(cols)


def test_stacked_horizon_scorer_shape_batch_one() -> None:
    n_feat = 4
    model = MtfFusionTransformer(n_features=n_feat, max_len=8)
    scorer = StackedHorizonScorer(model, 0)
    stacked = torch.randn(3, len(FUSION_INPUT_RESOLUTIONS), 8, n_feat)
    out = scorer(stacked)
    assert tuple(out.shape) == (3, 1)


def test_shap_stub_swallows_explainer_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoomExplainer:
        def __init__(self, model: object, data: object) -> None:
            raise IndexError("too many indices for tensor of dimension 1")

        def shap_values(self, x: object, **kwargs: object) -> np.ndarray:
            raise AssertionError("should not run")

    fake = types.ModuleType("shap")
    fake.GradientExplainer = BoomExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", fake)

    n_feat = 4
    cols = ["cdl_hammer", "chp_bull_flag", "rsi_14", "rv_16"]
    windows = {
        res: np.random.randn(8, 8, n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    model = MtfFusionTransformer(n_features=n_feat, max_len=8)
    report = shap_grouped_stub(
        cols,
        enabled=True,
        model=model,
        val_windows=windows,
        device=torch.device("cpu"),
        config={"shap_background": 4, "shap_explain_n": 4, "seed": 0},
    )
    assert report["enabled"] is True
    assert report["ok"] is False
    head_reasons = " ".join(
        str(row.get("reason") or "") for row in report.get("horizons", {}).values()
    )
    assert "too many indices" in head_reasons
