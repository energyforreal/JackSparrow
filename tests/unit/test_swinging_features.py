"""Causal feature snapshots."""

from __future__ import annotations

import pandas as pd

from research.swinging.contract import FORBIDDEN_FEATURE_COLUMNS
from research.swinging.features import snapshot_columns, snapshot_features
from research.swinging.regime import regime_target
from tests.unit.swinging_fixtures import make_ohlcv


def test_snapshot_ignores_a_future_bar_and_hides_labels() -> None:
    frame = make_ohlcv(48, drift=0.4)
    original = snapshot_features(frame, 30, "5m")
    changed = frame.copy()
    changed.loc[47, "close"] = float(changed.loc[47, "close"]) + 500.0
    changed.loc[47, "high"] = float(changed.loc[47, "high"]) + 500.0
    perturbed = snapshot_features(changed, 30, "5m")
    assert original == perturbed
    assert FORBIDDEN_FEATURE_COLUMNS.isdisjoint(original)
    assert list(original) == list(snapshot_columns())
    assert all(pd.notna(value) for value in original.values())


def test_regime_target_matches_structure_thresholds() -> None:
    from agent.core.market_structure import classify_market_structure

    trending = {
        "adx_14": 30.0,
        "atr_pct": 0.01,
        "vol_regime": 1.0,
        "hurst_60": 0.6,
    }
    assert regime_target(trending) == "trending"
    assert classify_market_structure(trending).market_type == "TRENDING"
    ranging = {
        "adx_14": 10.0,
        "atr_pct": 0.01,
        "vol_regime": 1.0,
        "hurst_60": 0.4,
    }
    assert regime_target(ranging) == "ranging"
    assert classify_market_structure(ranging).market_type == "RANGING"
    assert regime_target({"adx_14": 10.0, "atr_pct": 0.0005, "vol_regime": 0.5}) == (
        "low_volatility"
    )
