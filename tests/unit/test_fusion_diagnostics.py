"""Synthetic tests for v14 fusion diagnostics (no network, no GPU)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    FUSION_HORIZON_BARS_5M,
    LABEL_V2_HORIZON_BARS_5M,
    fusion_feature_cols_v14,
)
from feature_store.transformer_btcusd.mtf_labels_v2 import compute_fusion_path_targets
from scripts.colab.fusion_diagnostics import (
    audit_feature_truncation,
    audit_label_index,
    balanced_accuracy,
    class_intervals_disjoint,
    compare_row_values,
    decide_branch,
    embargoed_neighbor_probs,
    naive_baselines,
    recompute_horizon_return,
    simple_model_scores,
)


def _ohlcv(
    n: int = 80,
    *,
    close: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    atr: float = 10.0,
) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    if close is None:
        close = np.full(n, 100.0)
    if high is None:
        high = close + 0.1
    if low is None:
        low = close - 0.1
    return pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1.0,
            "atr": atr,
        }
    )


def test_recompute_return_matches_path_targets() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[16] = 106.0
    high = np.maximum(close, 100.0)
    high[11:17] = 106.0
    low = np.full(n, 100.0)
    df = _ohlcv(n, close=close, high=high, low=low, atr=10.0)
    labeled = compute_fusion_path_targets(df)
    close_a = labeled["close"].to_numpy(dtype=np.float64)
    atr = labeled["atr"].to_numpy(dtype=np.float64)
    k30 = int(FUSION_HORIZON_BARS_5M[0])
    stored = float(labeled.loc[10, "h30m_ret"])
    recomputed = recompute_horizon_return(close_a, atr, 10, k30)
    assert recomputed == pytest.approx(stored)
    assert recomputed == pytest.approx(0.6)
    k10 = int(LABEL_V2_HORIZON_BARS_5M[0])
    assert k10 == 2
    stored10 = float(labeled.loc[10, "h10m_ret"])
    recomputed10 = recompute_horizon_return(close_a, atr, 10, k10)
    assert recomputed10 == pytest.approx(stored10)
    assert "h2h_ret" not in labeled.columns
    audit = audit_label_index(labeled, sample_indices=[10, 20, 30])
    assert audit["ok"] is True
    assert audit["n_mismatches"] == 0


def test_class_intervals_disjoint_pass_and_fail() -> None:
    ret = np.array([-1.0, -0.6, 0.0, 0.4, 0.6, 1.2])
    good = np.array([0, 0, 1, 1, 2, 2])
    passed = class_intervals_disjoint(ret, good, theta=0.50)
    assert passed["ok"] is True
    swapped = np.array([2, 2, 1, 1, 0, 0])
    failed = class_intervals_disjoint(ret, swapped, theta=0.50)
    assert failed["ok"] is False
    assert failed["flags"]


def test_embargoed_neighbors_drop_adjacent_bar() -> None:
    n = 80
    x = np.zeros((n, 2), dtype=np.float64)
    y = np.zeros(n, dtype=np.int64)
    x[39] = np.array([1.0, 0.0])
    x[40] = np.array([1.0, 0.0])
    y[:] = 0
    y[39] = 2
    train = np.arange(0, 56)
    query = np.array([40])
    report = embargoed_neighbor_probs(
        x,
        y,
        train,
        query,
        horizon_bars=6,
        embargo_bars=24,
        n_neighbors=8,
        train_cap=80,
        query_cap=80,
        seed=0,
    )
    assert report["ok"] is True
    assert report["mean_probs"]["BEAR"] == pytest.approx(1.0)
    assert report["mean_probs"]["BULL"] == pytest.approx(0.0)


def test_always_bull_baseline_on_constant_labels() -> None:
    n = 60
    y = np.full(n, 2, dtype=np.int64)
    names = ("ret_1", "rsi_14")
    x = np.zeros((n, 2), dtype=np.float64)
    x[:, 0] = 0.2
    x[:, 1] = 60.0
    eval_idx = np.arange(n)
    report = naive_baselines(y, x, names, eval_idx, horizon_bars=6)
    assert report["ok"] is True
    assert report["baselines"]["always_bull"]["balanced_acc"] == pytest.approx(1.0)
    assert report["baselines"]["always_bear"]["balanced_acc"] == pytest.approx(0.0)
    assert report["baselines"]["always_neutral"]["balanced_acc"] == pytest.approx(0.0)
    n_keep = report["n"]
    assert n_keep == len(range(0, n, 6))


def test_truncation_flags_future_shift_and_accepts_causal() -> None:
    n = 40
    close = np.arange(n, dtype=np.float64) + 100.0
    frame = _ohlcv(n, close=close)

    def _with_cols(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["causal"] = out["close"]
        out["leaky"] = out["close"].shift(-1)
        return out

    causal = audit_feature_truncation(
        frame,
        sample_indices=[10, 15, 20],
        feature_fn=_with_cols,
        cols=("causal",),
    )
    assert causal["ok"] is True
    leaky = audit_feature_truncation(
        frame,
        sample_indices=[10, 15, 20],
        feature_fn=_with_cols,
        cols=("leaky",),
    )
    assert leaky["ok"] is False
    assert leaky["n_mismatches"] >= 1
    full = _with_cols(frame)
    prefix = _with_cols(frame.iloc[:11])
    bad = compare_row_values(full.iloc[10], prefix.iloc[-1], ("leaky",))
    good = compare_row_values(full.iloc[10], prefix.iloc[-1], ("causal",))
    assert bad == ["leaky"]
    assert good == []


def test_simple_models_beat_chance_when_linearly_separated() -> None:
    rng = np.random.default_rng(0)
    n = 400
    y = np.array([i % 3 for i in range(n)], dtype=np.int64)
    x = rng.normal(scale=0.05, size=(n, 2))
    x[y == 0, 0] -= 1.5
    x[y == 2, 0] += 1.5
    train = np.arange(0, 280)
    val = np.arange(304, 340)
    report = simple_model_scores(
        x,
        y,
        train_idx=train,
        val_idx=val,
        horizon_bars=6,
        n_dev=340,
        seed=0,
        folds=3,
        embargo_bars=24,
    )
    assert report["ok"] is True
    assert report["test_unused"] is True
    assert report["best_val_balanced_acc"] > 0.7
    chance = balanced_accuracy(y[val], np.full(len(val), 1))
    assert report["best_val_balanced_acc"] > chance + 0.2


def test_decide_branch_tokens() -> None:
    base = {
        "d1_index_audit": {"ok": True},
        "d2_intervals": {"ok": True},
        "d9_truncation": {"ok": True},
        "d5_knn": {
            "horizons": {
                "h10m": {"near_base_rate": True},
                "h15m": {"near_base_rate": True},
                "h30m": {"near_base_rate": True},
                "h1h": {"near_base_rate": True},
            }
        },
        "d6_baselines": {
            "horizons": {
                "h10m": {"best_balanced_acc": 0.33},
                "h15m": {"best_balanced_acc": 0.33},
                "h30m": {"best_balanced_acc": 0.33},
                "h1h": {"best_balanced_acc": 0.34},
            }
        },
        "d7_simple_models": {
            "horizons": {
                "h10m": {"best_val_balanced_acc": 0.34},
                "h15m": {"best_val_balanced_acc": 0.34},
                "h30m": {"best_val_balanced_acc": 0.34},
                "h1h": {"best_val_balanced_acc": 0.35},
            }
        },
    }
    assert decide_branch(base) == "stop_target_or_features"
    leak = dict(base)
    leak["d9_truncation"] = {"ok": False}
    assert decide_branch(leak) == "fix_leakage"
    lifted = {
        **base,
        "d5_knn": {
            "horizons": {
                "h10m": {"near_base_rate": False},
                "h15m": {"near_base_rate": False},
                "h30m": {"near_base_rate": False},
                "h1h": {"near_base_rate": False},
            }
        },
        "d7_simple_models": {
            "horizons": {
                "h10m": {"best_val_balanced_acc": 0.45},
                "h15m": {"best_val_balanced_acc": 0.44},
                "h30m": {"best_val_balanced_acc": 0.45},
                "h1h": {"best_val_balanced_acc": 0.46},
            }
        },
    }
    assert decide_branch(lifted) == "later_direction_only"


def test_v14_feature_count_stable() -> None:
    assert len(fusion_feature_cols_v14()) == 77


def test_diagnostics_notebook_has_no_training() -> None:
    from scripts.colab.build_fusion_diagnostics_notebook import (
        TRAIN_FORBIDDEN,
        build_notebook,
        validate_notebook,
    )

    notebook = build_notebook()
    validate_notebook(notebook)
    text = "\n".join("".join(c.get("source", [])) for c in notebook["cells"])
    for token in TRAIN_FORBIDDEN:
        assert token not in text
    assert "run_fusion_diagnostics" in text
    assert "## 03 Run diagnostics" in text
    assert "run_direction_predictability" in text
    assert "PREREGISTERED_READINGS" in text
    assert "run_path_regression" in text
    assert "fusion_model_from_config(" not in text
