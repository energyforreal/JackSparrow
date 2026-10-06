"""Unit tests for last-bar path-edge regression helpers."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import fusion_feature_cols_v14
from scripts.colab.path_regression import (
    PREREGISTERED_READINGS,
    classify_path_reading,
    path_target_pack,
    run_path_regression,
    sign_auc,
    signed_path_edge,
    spearman_safe,
)


def test_signed_path_edge_prefers_clean_long() -> None:
    edge = signed_path_edge(
        long_mfe=np.array([2.0]),
        long_mae=np.array([0.2]),
        short_mfe=np.array([0.5]),
        short_mae=np.array([0.4]),
    )
    assert edge[0] == pytest.approx(1.7)


def test_path_target_pack_from_frame() -> None:
    frame = pd.DataFrame(
        {
            "h10m_ret": [1.0, -1.0],
            "h10m_long_mfe": [2.0, 0.3],
            "h10m_long_mae": [0.2, 0.2],
            "h10m_short_mfe": [0.4, 2.0],
            "h10m_short_mae": [0.3, 0.1],
        }
    )
    pack = path_target_pack(frame, "h10m")
    assert pack["path_signed"][0] > 0.0
    assert pack["path_signed"][1] < 0.0


def test_sign_auc_on_aligned_scores() -> None:
    y = np.array([-2.0, -1.5, -1.2, -1.1, 1.1, 1.2, 1.5, 2.0, 0.0])
    pred = np.array([-1.0, -0.8, -0.6, -0.5, 0.5, 0.6, 0.8, 1.0, 0.1])
    auc = sign_auc(y, pred, min_abs=1.0)
    assert auc is not None
    assert auc > 0.9


def test_classify_path_reading_tokens() -> None:
    assert set(PREREGISTERED_READINGS) == {
        "no_path_signal",
        "vol_not_edge",
        "real_path_edge",
        "endpoint_still_dead",
    }
    assert (
        classify_path_reading(
            {
                "spearman_ci": [-0.05, 0.04],
                "sign_auc_path_ci": [0.47, 0.53],
                "sign_auc_ret_ci": [0.46, 0.54],
                "spearman": 0.01,
                "rv16_spearman": 0.00,
                "abs_vs_rv16_spearman_ci": [-0.02, 0.03],
            }
        )
        == "no_path_signal"
    )
    assert (
        classify_path_reading(
            {
                "spearman_ci": [-0.04, 0.05],
                "sign_auc_path_ci": [0.48, 0.52],
                "sign_auc_ret_ci": [0.47, 0.53],
                "spearman": 0.02,
                "rv16_spearman": 0.01,
                "abs_vs_rv16_spearman_ci": [0.20, 0.40],
            }
        )
        == "vol_not_edge"
    )
    assert (
        classify_path_reading(
            {
                "spearman_ci": [0.12, 0.30],
                "sign_auc_path_ci": [0.58, 0.70],
                "sign_auc_ret_ci": [0.56, 0.68],
                "spearman": 0.20,
                "rv16_spearman": 0.05,
            }
        )
        == "real_path_edge"
    )
    assert (
        classify_path_reading(
            {
                "spearman_ci": [0.12, 0.30],
                "sign_auc_path_ci": [0.58, 0.70],
                "sign_auc_ret_ci": [0.47, 0.53],
                "spearman": 0.20,
                "rv16_spearman": 0.05,
            }
        )
        == "endpoint_still_dead"
    )


def test_spearman_safe_none_on_tiny() -> None:
    assert spearman_safe(np.array([1.0]), np.array([2.0])) is None


def test_run_path_regression_does_not_train_transformer() -> None:
    src = inspect.getsource(run_path_regression)
    assert "MtfFusionTransformer" not in src
    assert "decide_branch" not in src
    rng = np.random.default_rng(0)
    names = list(fusion_feature_cols_v14())
    n = 220
    x = rng.normal(size=(n, len(names)))
    rv = np.linspace(-2.0, 2.0, n)
    x[:, names.index("rv_16")] = rv
    long_mfe = np.maximum(rv, 0.0) + 0.1
    long_mae = np.maximum(-rv, 0.0) * 0.2 + 0.05
    short_mfe = np.maximum(-rv, 0.0) + 0.1
    short_mae = np.maximum(rv, 0.0) * 0.2 + 0.05
    cols = {}
    for key in ("h10m", "h15m", "h30m", "h1h"):
        cols[f"{key}_ret"] = rv
        cols[f"{key}_long_mfe"] = long_mfe
        cols[f"{key}_long_mae"] = long_mae
        cols[f"{key}_short_mfe"] = short_mfe
        cols[f"{key}_short_mae"] = short_mae
    frame = pd.DataFrame(cols)
    report = run_path_regression(x, names, frame, seed=0, score_test=True)
    assert "preregistered_readings" in report
    first = report["horizons"]["h10m"]
    if first.get("val"):
        assert first["val"].get("reading") in PREREGISTERED_READINGS
    assert "branch" not in report
