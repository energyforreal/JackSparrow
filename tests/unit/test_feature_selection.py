"""Unit tests for the train-block feature and label search."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from feature_store.transformer_btcusd.contract import (
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_REG_FIELDS,
    fusion_feature_cols_v14,
)
from scripts.colab.feature_selection import (
    LabelFeatureSpec,
    _mean_abs_vector,
    base_column_importance,
    build_selection_payload,
    combo_fingerprint,
    group_column_indices,
    label_gate_ok,
    score_label_feature_pair,
    select_top_columns,
    train_block_end,
    write_selection,
)


def test_train_block_end_matches_purged_train_cut() -> None:
    assert train_block_end(64751, 0.70) == int(64751 * 0.70)


def test_group_column_indices_follow_contract_order() -> None:
    names = fusion_feature_cols_v14()
    idx = group_column_indices(("context", "price"), names)
    assert [names[i] for i in idx] == ["ret_1", "hour_sin", "hour_cos", "dow_sin", "dow_cos"]


def test_select_top_columns_returns_v14_order() -> None:
    chosen = select_top_columns([0, 5, 10, 20], np.array([0.1, 0.9, 0.2, 0.8]), 2)
    assert chosen == [5, 20]


def test_label_gate_rejects_all_neutral() -> None:
    y = np.ones(80, dtype=np.int64)
    ret = np.zeros(80, dtype=np.float64)
    assert label_gate_ok(y, ret, 0.50) is False


def test_label_gate_accepts_separated_classes() -> None:
    y = np.array([0] * 40 + [1] * 40 + [2] * 40, dtype=np.int64)
    ret = np.array([-1.0] * 40 + [0.0] * 40 + [1.0] * 40, dtype=np.float64)
    assert label_gate_ok(y, ret, 0.50) is True


def test_score_pair_uses_predictive_column() -> None:
    names = list(fusion_feature_cols_v14())
    n = 360
    n_tf = 2
    n_feat = len(names)
    ret_idx = names.index("ret_1")
    ret = np.zeros((n, len(LABEL_V2_HORIZON_KEYS)), dtype=np.float64)
    cycle = np.resize(np.array([-1.0, 0.0, 1.0]), n)
    ret[:, 0] = cycle
    path = np.zeros((n, len(LABEL_V2_HORIZON_KEYS), len(LABEL_V2_REG_FIELDS)), dtype=np.float32)
    path[:, :, 0] = ret
    last = np.zeros((n, n_tf, n_feat), dtype=np.float32)
    last[:, :, ret_idx] = cycle.reshape(-1, 1)
    spec = LabelFeatureSpec(
        groups=("price",),
        keep_frac=1.0,
        thetas={str(key): 0.50 for key in LABEL_V2_HORIZON_KEYS},
        active_horizons=("h10m",),
        path_on=False,
    )
    scored = score_label_feature_pair(
        last,
        path,
        spec,
        feature_names=names,
        folds=2,
        embargo=1,
        seed=0,
    )
    assert scored["gate_passed"] is True
    assert scored["selected_cols"] == ["ret_1"]
    assert scored["balanced_acc"] > 0.9


def test_write_selection_roundtrip(tmp_path: Path) -> None:
    payload = build_selection_payload(
        {
            "selected_cols": ["ret_1", "rv_16"],
            "groups_kept": ["price", "volatility"],
            "thetas": {str(key): 0.50 for key in LABEL_V2_HORIZON_KEYS},
            "horizon_loss_weights": [1.0, 0.0, 0.0, 0.0],
            "path_loss_weights": {"dir": 1.0, "ret": 0.0},
            "balanced_acc": 0.41,
            "gate_passed": True,
            "experiment": "later_direction_only",
        },
        n_samples=100,
        train_end=70,
        n_trials=2,
        complete=True,
    )
    dest = tmp_path / "selection.json"
    write_selection(dest, payload)
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["selected_cols"] == ["ret_1", "rv_16"]
    assert loaded["complete"] is True
    assert loaded["train_end"] == 70
    assert "rv_96" in loaded["dropped_cols"]
    assert loaded["selection_fingerprint"] == combo_fingerprint(
        loaded["selected_cols"],
        loaded["label_v2_theta"],
        loaded["horizon_loss_weights"],
        loaded["path_loss_weights"],
    )


def test_injected_importance_limits_columns() -> None:
    names = list(fusion_feature_cols_v14())
    n = 360
    last = np.zeros((n, 1, len(names)), dtype=np.float32)
    ret = np.resize(np.array([-1.0, 0.0, 1.0]), n).astype(np.float64)
    path = np.zeros((n, len(LABEL_V2_HORIZON_KEYS), len(LABEL_V2_REG_FIELDS)), dtype=np.float32)
    path[:, 0, 0] = ret
    last[:, 0, names.index("ret_1")] = ret
    candidates = group_column_indices(("price", "volatility"), names)
    importance = np.zeros(len(candidates), dtype=np.float64)
    importance[0] = 1.0
    spec = LabelFeatureSpec(
        groups=("price", "volatility"),
        keep_frac=0.25,
        thetas={str(key): 0.50 for key in LABEL_V2_HORIZON_KEYS},
        active_horizons=("h10m",),
        path_on=False,
    )
    scored = score_label_feature_pair(
        last,
        path,
        spec,
        feature_names=names,
        folds=2,
        embargo=1,
        importance=importance,
        seed=0,
    )
    assert scored["selected_cols"] == ["ret_1"]


def test_empty_groups_score_zero() -> None:
    names = list(fusion_feature_cols_v14())
    last = np.zeros((40, 1, len(names)), dtype=np.float32)
    path = np.zeros((40, len(LABEL_V2_HORIZON_KEYS), len(LABEL_V2_REG_FIELDS)), dtype=np.float32)
    spec = LabelFeatureSpec(
        groups=(),
        keep_frac=1.0,
        thetas={str(key): 0.50 for key in LABEL_V2_HORIZON_KEYS},
        active_horizons=("h10m",),
        path_on=False,
    )
    scored = score_label_feature_pair(last, path, spec, feature_names=names, embargo=1)
    assert scored["objective"] == 0.0
    assert scored["gate_passed"] is False


def test_shap_class_axis_is_not_the_feature_axis() -> None:
    values = np.zeros((4, 6, 3), dtype=np.float64)
    values[:, 2, :] = 3.0
    flat = _mean_abs_vector(values, n_features=6)
    assert flat.shape == (6,)
    assert flat[2] == pytest.approx(3.0)
    assert flat[0] == pytest.approx(0.0)
    base = base_column_importance(np.tile(flat, 2), n_timeframes=2, n_columns=6)
    assert base.shape == (6,)
    assert base[2] == pytest.approx(3.0)


def test_train_block_end_rejects_tiny_samples() -> None:
    with pytest.raises(ValueError):
        train_block_end(10, 0.70)
