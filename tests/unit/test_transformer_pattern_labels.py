"""Unit tests for v6 path-pattern labels."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    CONTINUOUS_LABEL_COLS,
    FUTURE_CANDLE_COL,
    STRUCTURE_OUTCOME_COL,
    STRUCTURE_OUTCOME_NAMES,
)
from feature_store.transformer_btcusd.labels import compute_market_labels


def _frame(
    n: int = 40,
    *,
    close: np.ndarray | None = None,
    structure_bias: np.ndarray | None = None,
    failed_break: np.ndarray | None = None,
    bars_since_breakout: np.ndarray | None = None,
    candle_class_id: np.ndarray | None = None,
) -> pd.DataFrame:
    rng = np.arange(n, dtype=np.float64)
    if close is None:
        close = 50000.0 + rng * 20.0
    open_px = close - 5.0
    high = close + 15.0
    low = close - 8.0
    return pd.DataFrame(
        {
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 10.0),
            "atr": np.full(n, 20.0),
            "structure_bias": (
                structure_bias if structure_bias is not None else np.full(n, 0.4)
            ),
            "failed_break": failed_break if failed_break is not None else np.zeros(n),
            "bars_since_breakout": (
                bars_since_breakout
                if bars_since_breakout is not None
                else np.full(n, 8.0)
            ),
            CANDLE_CLASS_COL: (
                candle_class_id
                if candle_class_id is not None
                else np.full(n, 11, dtype=np.int64)
            ),
        }
    )


def test_continuous_label_count_is_nine() -> None:
    assert len(CONTINUOUS_LABEL_COLS) == 9
    assert "candle_follow_through_atr" in CONTINUOUS_LABEL_COLS
    assert "structure_delta" in CONTINUOUS_LABEL_COLS


def test_uptrend_continuation_long_and_positive_structure_delta() -> None:
    n = 40
    close = 50000.0 + np.arange(n) * 25.0
    bias = np.linspace(0.2, 0.9, n)
    labeled = compute_market_labels(
        _frame(n, close=close, structure_bias=bias),
        path_label_horizon_bars=8,
        mae_floor_atr_mult=0.25,
    )
    row = labeled.iloc[5]
    assert STRUCTURE_OUTCOME_NAMES[int(row[STRUCTURE_OUTCOME_COL])] == "CONTINUATION_LONG"
    assert float(row["structure_delta"]) > 0.0
    assert float(row["mfe"]) >= float(row["mae"])


def test_failed_break_outcome_takes_priority() -> None:
    n = 40
    failed = np.zeros(n)
    failed[8] = 1.0
    labeled = compute_market_labels(
        _frame(n, failed_break=failed, structure_bias=np.full(n, 0.5)),
        path_label_horizon_bars=8,
        mae_floor_atr_mult=0.25,
    )
    assert int(labeled.loc[2, STRUCTURE_OUTCOME_COL]) == 4
    assert STRUCTURE_OUTCOME_NAMES[4] == "FAILED_BREAK"


def test_future_candle_class_is_next_bar() -> None:
    n = 40
    ids = np.arange(n) % 13
    labeled = compute_market_labels(
        _frame(n, candle_class_id=ids.astype(np.int64)),
        path_label_horizon_bars=8,
        mae_floor_atr_mult=0.25,
    )
    for i in range(n - 8):
        assert int(labeled.loc[i, FUTURE_CANDLE_COL]) == int(ids[i + 1])


def test_candle_follow_through_signed_by_body() -> None:
    n = 30
    close = np.full(n, 50000.0)
    close[10] = 50100.0
    labeled = compute_market_labels(
        _frame(n, close=close, candle_class_id=np.full(n, 11, dtype=np.int64)),
        path_label_horizon_bars=8,
        mae_floor_atr_mult=0.25,
    )
    assert "candle_follow_through_atr" in labeled.columns
    assert np.isfinite(labeled.loc[9, "candle_follow_through_atr"])
