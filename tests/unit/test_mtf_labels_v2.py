"""Tests for Label V2 path targets (research-only; live v11 ignore_index unchanged)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_CARDINALITY,
    FUSION_DIRECTION_NAMES,
    LABEL_V2_COLS,
    LABEL_V2_DIRECTION_NAMES,
    LABEL_V2_THETA_GRID,
    LABEL_V2_TP_SL_AMBIGUOUS,
    LABEL_V2_TP_SL_NEITHER,
    LABEL_V2_TP_SL_SL_FIRST,
    LABEL_V2_TP_SL_TP_FIRST,
    MAX_FUSION_HORIZON_BARS,
)
from feature_store.transformer_btcusd.mtf_labels import (
    fusion_future_leak_cols,
    three_class_to_train_label,
    trim_fusion_label_tail,
)
from feature_store.transformer_btcusd.mtf_labels_v2 import (
    compute_fusion_path_targets,
    direction_from_return,
    fusion_label_v2_matrices,
    label_v2_future_leak_cols,
    state_persistence,
    summarize_label_v2,
    tp_sl_from_path,
    valid_label_v2_mask,
)


def _frame(
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


def test_live_v11_cardinality_unchanged() -> None:
    assert FUSION_DIRECTION_CARDINALITY == 2
    assert FUSION_DIRECTION_NAMES == {0: "BEAR", 1: "BULL"}
    assert three_class_to_train_label(1) == -1
    assert LABEL_V2_DIRECTION_NAMES[1] == "NEUTRAL"


def test_direction_bins_include_atr_cliff() -> None:
    assert direction_from_return(0.49, 0.50) == 1
    assert direction_from_return(0.51, 0.50) == 2
    assert direction_from_return(-0.49, 0.50) == 1
    assert direction_from_return(-0.51, 0.50) == 0
    assert direction_from_return(0.25, 0.25) == 2
    assert direction_from_return(0.24, 0.25) == 1
    for theta in LABEL_V2_THETA_GRID:
        assert direction_from_return(float(theta), float(theta)) == 2
        assert direction_from_return(-float(theta), float(theta)) == 0


def test_endpoint_rally_return_and_mfe() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[16] = 106.0
    high = np.maximum(close, 100.0)
    high[11:17] = 106.0
    low = np.full(n, 100.0)
    df = _frame(n, close=close, high=high, low=low, atr=10.0)
    labeled = compute_fusion_path_targets(df)
    ret = float(labeled.loc[10, "h30m_ret"])
    mfe = float(labeled.loc[10, "h30m_mfe"])
    mae = float(labeled.loc[10, "h30m_mae"])
    assert ret == pytest.approx(0.6)
    assert mfe == pytest.approx(0.6)
    assert mfe >= ret - 1e-12
    assert mae == pytest.approx(0.0)
    assert mae <= 0.0
    assert float(labeled.loc[10, "h30m_t_mfe"]) >= 1.0


def test_path_win_endpoint_loss_long_tp_first() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[11:17] = np.array([99.0, 98.0, 97.0, 96.0, 95.0, 94.0])
    high = close.copy() + 0.1
    high[11] = 116.0
    low = np.minimum(close, 99.5)
    df = _frame(n, close=close, high=high, low=low, atr=10.0)
    labeled = compute_fusion_path_targets(df)
    ret = float(labeled.loc[10, "h30m_ret"])
    assert ret < 0.0
    assert direction_from_return(ret, 0.50) == 0
    fwd_high = labeled.loc[11:16, "high"].to_numpy()
    fwd_low = labeled.loc[11:16, "low"].to_numpy()
    outcome = tp_sl_from_path(
        fwd_high,
        fwd_low,
        entry=100.0,
        atr=10.0,
        tp_mult=1.5,
        sl_mult=1.0,
        side="LONG",
    )
    assert outcome == LABEL_V2_TP_SL_TP_FIRST
    assert float(labeled.loc[10, "h30m_mfe"]) == pytest.approx(1.6)


def test_same_bar_both_sides_is_ambiguous() -> None:
    high = np.array([120.0, 101.0])
    low = np.array([80.0, 99.0])
    assert (
        tp_sl_from_path(high, low, 100.0, 10.0, 1.5, 1.0, "LONG")
        == LABEL_V2_TP_SL_AMBIGUOUS
    )
    assert (
        tp_sl_from_path(high, low, 100.0, 10.0, 1.5, 1.0, "SHORT")
        == LABEL_V2_TP_SL_AMBIGUOUS
    )


def test_tp_sl_neither_when_path_stays_inside() -> None:
    high = np.array([101.0, 102.0, 101.5])
    low = np.array([99.0, 98.5, 99.2])
    assert (
        tp_sl_from_path(high, low, 100.0, 10.0, 1.5, 1.0, "LONG")
        == LABEL_V2_TP_SL_NEITHER
    )


def test_short_sl_first() -> None:
    high = np.array([112.0, 101.0])
    low = np.array([99.0, 98.0])
    assert (
        tp_sl_from_path(high, low, 100.0, 10.0, 1.5, 1.0, "SHORT")
        == LABEL_V2_TP_SL_SL_FIRST
    )


def test_bar_t_excluded_from_mfe_mae() -> None:
    n = 80
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    base = _frame(n, close=close, high=high, low=low, atr=10.0)
    labeled = compute_fusion_path_targets(base)
    bumped = base.copy()
    bumped.loc[10, "high"] = 180.0
    bumped.loc[10, "low"] = 20.0
    relabeled = compute_fusion_path_targets(bumped)
    for col in ("h30m_mfe", "h30m_mae", "h1h_mfe", "h1h_mae", "h2h_mfe", "h2h_mae"):
        assert float(labeled.loc[10, col]) == pytest.approx(float(relabeled.loc[10, col]))


def test_tail_nans_for_incomplete_2h() -> None:
    n = 80
    labeled = compute_fusion_path_targets(_frame(n))
    assert pd.isna(labeled.iloc[-1]["h2h_ret"])
    assert pd.isna(labeled.iloc[-MAX_FUSION_HORIZON_BARS]["h30m_ret"])
    assert pd.notna(labeled.iloc[-MAX_FUSION_HORIZON_BARS - 1]["h2h_ret"])
    trimmed = trim_fusion_label_tail(labeled)
    assert len(trimmed) == n - MAX_FUSION_HORIZON_BARS
    assert trimmed["h2h_ret"].notna().all()


def test_leakage_helper_lists_every_v2_column() -> None:
    leaked = label_v2_future_leak_cols()
    for col in LABEL_V2_COLS:
        assert col in leaked
    assert "close" not in leaked
    assert "h30m_dir" not in leaked
    live = fusion_future_leak_cols()
    assert "h30m_dir" in live
    assert "h30m_ret" not in live


def test_zero_atr_is_nan_not_exploded() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[16] = 110.0
    df = _frame(n, close=close, high=close + 0.1, low=close - 0.1, atr=0.0)
    labeled = compute_fusion_path_targets(df)
    assert pd.isna(labeled.loc[10, "h30m_ret"])
    assert pd.isna(labeled.loc[10, "h30m_mfe"])


def test_theta_free_persistence_mean_sign() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[11:17] = np.array([101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    df = _frame(n, close=close, high=close + 0.1, low=close - 0.1, atr=10.0)
    labeled = compute_fusion_path_targets(df)
    assert float(labeled.loc[10, "h30m_persist"]) == pytest.approx(1.0)
    path = close[11:17]
    assert state_persistence(path, 100.0, 10.0, 0.10) == pytest.approx(1.0)
    assert state_persistence(path, 100.0, 10.0, 0.25) == pytest.approx(4.0 / 6.0)


def test_summarize_report_shape_and_disagreement() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[11:17] = np.array([99.0, 98.0, 97.0, 96.0, 95.0, 94.0])
    high = close.copy() + 0.1
    high[11] = 116.0
    low = np.minimum(close, 99.5)
    df = _frame(n, close=close, high=high, low=low, atr=10.0)
    report = summarize_label_v2(df, thetas=(0.50,), tp_sl_grid=((1.0, 1.5),))
    assert "horizons" in report
    assert "h30m" in report["horizons"]
    h30 = report["horizons"]["h30m"]["by_theta"]["0.50"]
    assert h30["disagreement_rate"] >= 0.0
    assert "BEAR" in h30["classes"]
    assert "gate" in report["horizons"]["h30m"]
    assert report["overall"] in {
        "go",
        "no-go",
        "go_with_2h_regression_only",
    }
    live = h30["tp_sl"]["sl1.00_tp1.50"]
    assert live["live_bracket"] is True
    assert "AMBIGUOUS" in live["long"]


def test_fusion_label_v2_matrices_frozen_theta() -> None:
    n = 80
    close = np.full(n, 100.0)
    close[16] = 106.0
    df = _frame(n, close=close, high=close + 0.1, low=close - 0.1, atr=10.0)
    labeled = compute_fusion_path_targets(df)
    y_dir, y_reg = fusion_label_v2_matrices(labeled)
    assert y_dir.shape == (n, 3)
    assert y_reg.shape == (n, 3, 3)
    assert int(y_dir[10, 0]) == 2
    assert float(y_reg[10, 0, 0]) == pytest.approx(0.6)
    mask = valid_label_v2_mask(y_dir, y_reg)
    assert bool(mask[10])
    assert not bool(mask[-1])
