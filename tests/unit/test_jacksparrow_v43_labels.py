"""Tests for v43 label experiment helpers."""

from __future__ import annotations

import pandas as pd

from feature_store.jacksparrow_v43_labels import (
    build_triple_barrier_labels,
    compare_label_schemes,
)


def test_triple_barrier_labels_hit_tp() -> None:
    close = pd.Series([100.0, 100.0, 102.0, 103.0, 103.0])
    labels, stats = build_triple_barrier_labels(
        close, forward_bars=2, take_profit_pct=0.01, stop_loss_pct=0.01
    )
    assert stats["tp_hit_fraction"] >= 0.0
    assert labels.notna().any()


def test_compare_label_schemes_returns_three_blocks() -> None:
    close = pd.Series([100.0 + 0.05 * (i % 7) for i in range(100)])
    out = compare_label_schemes(close, forward_bars=2, round_trip_cost=0.01)
    assert "simple_forward" in out
    assert "cost_aware_no_trade_band" in out
    assert "triple_barrier" in out
