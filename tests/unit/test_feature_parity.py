"""
Feature parity tests: verify batch and single compute produce identical values.

Ensures train-serve parity for UnifiedFeatureEngine.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from feature_store.unified_feature_engine import UnifiedFeatureEngine
from feature_store.feature_registry import (
    FEATURE_LIST,
    CANDLESTICK_FEATURES,
    CHART_PATTERN_FEATURES,
    MTF_CONTEXT_FEATURES,
    EXPANDED_FEATURE_LIST,
)
from feature_store.unified_feature_engine import FEATURE_ALIASES


def _make_test_df(n: int = 150) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame."""
    np.random.seed(42)
    base = 50000
    returns = np.random.randn(n).cumsum() * 0.002
    close = base * (1 + returns)
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(100, 1000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume
    })


def _make_test_df_5m_with_ts(n: int = 200) -> pd.DataFrame:
    """OHLCV with UTC timestamps on a 5-minute grid (required for MTF resample path)."""
    df = _make_test_df(n)
    start = pd.Timestamp("2024-01-01", tz="UTC")
    df["timestamp"] = start + pd.to_timedelta(np.arange(n) * 5, unit="m")
    return df


@pytest.mark.parametrize("feature_name", MTF_CONTEXT_FEATURES)
def test_mtf_context_feature_parity(feature_name: str):
    """Batch vs compute_single for MTF context features (5m primary)."""
    df = _make_test_df_5m_with_ts(220)
    candles = df.to_dict("records")
    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(
        df,
        resolution_minutes=5,
        fill_invalid=True,
        include_mtf_context=True,
    )
    single_val = engine.compute_single(feature_name, candles, resolution_minutes=5)
    batch_val = float(batch[feature_name].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5, (
        f"Parity failure for {feature_name}: batch={batch_val:.8f}, single={single_val:.8f}"
    )


@pytest.mark.parametrize("feature_name", FEATURE_LIST[:10])  # Test subset for speed
def test_canonical_feature_parity(feature_name: str):
    """Batch last-row value matches compute_single for canonical features."""
    df = _make_test_df(100)
    candles = df.to_dict("records")

    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True)
    single_val = engine.compute_single(feature_name, candles, resolution_minutes=15)

    batch_val = float(batch[feature_name].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5, (
        f"Parity failure for {feature_name}: batch={batch_val:.8f}, single={single_val:.8f}"
    )


def test_candlestick_feature_parity():
    """Batch last-row matches compute_single for candlestick features."""
    df = _make_test_df(150)
    candles = df.to_dict("records")

    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True, include_pattern_features=True)
    single_val = engine.compute_single("cdl_doji", candles)

    batch_val = float(batch["cdl_doji"].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5


@pytest.mark.parametrize("feature_name", CANDLESTICK_FEATURES[:8])  # subset for speed
def test_candlestick_feature_parity_subset(feature_name: str):
    """Subset parity check for candlestick features."""
    df = _make_test_df(150)
    candles = df.to_dict("records")
    engine = UnifiedFeatureEngine()

    batch = engine.compute_batch(df, fill_invalid=True, include_pattern_features=True)
    single_val = engine.compute_single(feature_name, candles, resolution_minutes=15)

    batch_val = float(batch[feature_name].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5, (
        f"Parity failure for {feature_name}: batch={batch_val:.8f}, single={single_val:.8f}"
    )


@pytest.mark.parametrize("feature_name", CHART_PATTERN_FEATURES[:8])  # subset for speed
def test_chart_pattern_feature_parity_subset(feature_name: str):
    """Subset parity check for chart pattern features."""
    df = _make_test_df(180)
    candles = df.to_dict("records")
    engine = UnifiedFeatureEngine()

    batch = engine.compute_batch(df, fill_invalid=True, include_pattern_features=True)
    single_val = engine.compute_single(feature_name, candles, resolution_minutes=15)

    batch_val = float(batch[feature_name].iloc[-1])
    assert abs(batch_val - single_val) < 1e-5, (
        f"Parity failure for {feature_name}: batch={batch_val:.8f}, single={single_val:.8f}"
    )


def test_full_canonical_parity():
    """All 50 canonical features have parity."""
    df = _make_test_df(100)
    candles = df.to_dict("records")
    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(df, fill_invalid=True)

    for name in FEATURE_LIST:
        single_val = engine.compute_single(name, candles)
        batch_val = float(batch[name].iloc[-1])
        assert abs(batch_val - single_val) < 1e-5, f"Parity failure: {name}"


def test_active_v5_bundle_metadata_features_known_to_engine():
    """metadata features_required must map to UnifiedFeatureEngine (train-serve gate)."""
    meta_path = (
        ROOT
        / "agent"
        / "model_storage"
        / "jacksparrow_v5_BTCUSD_2026-03-21"
        / "metadata_BTCUSD_5m.json"
    )
    if not meta_path.is_file():
        pytest.skip("jacksparrow_v5_BTCUSD_2026-03-21 metadata not present")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    required = meta.get("features_required") or []
    assert len(required) > 0
    expanded = set(EXPANDED_FEATURE_LIST)
    engine = UnifiedFeatureEngine()
    df = _make_test_df_5m_with_ts(220)
    candles = df.to_dict("records")
    for name in required[:40]:
        canonical = FEATURE_ALIASES.get(name, name)
        assert canonical in expanded or name in expanded, f"Unknown feature in metadata: {name}"
        val = engine.compute_single(name, candles, resolution_minutes=5)
        assert val == val, f"Non-numeric feature {name}"


def test_compute_batch_last_row_is_finite_for_active_v5_required_features():
    """
    Guardrail: for the active slim bundle, UnifiedFeatureEngine must produce finite
    (not NaN/Inf) values for the metadata-required features on the most recent bar.
    """
    meta_path = (
        ROOT
        / "agent"
        / "model_storage"
        / "jacksparrow_v5_BTCUSD_2026-03-21"
        / "metadata_BTCUSD_5m.json"
    )
    if not meta_path.is_file():
        pytest.skip("jacksparrow_v5_BTCUSD_2026-03-21 metadata not present")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    required = meta.get("features_required") or []
    assert len(required) > 0

    df = _make_test_df_5m_with_ts(240)
    engine = UnifiedFeatureEngine()
    batch = engine.compute_batch(
        df,
        resolution_minutes=5,
        fill_invalid=True,
        include_pattern_features=True,
        include_mtf_context=True,
    )

    # Validate only what the model requests (train-serve contract).
    last = batch.iloc[-1]
    for name in required:
        assert name in batch.columns, f"Missing required feature in batch output: {name}"
        v = float(last[name])
        assert np.isfinite(v), f"Non-finite value for feature {name}: {v}"


def test_feature_pipeline_wrapper_produces_finite_last_row():
    """Guardrail: FeaturePipeline.transform should never output NaN/Inf on last row."""
    from feature_store.feature_pipeline import FeaturePipeline

    df = _make_test_df(200)
    pipe = FeaturePipeline(resolution_minutes=15, fill_invalid=True, validate=True)
    feat = pipe.transform(df)
    last = feat.iloc[-1].to_numpy(dtype=float)
    assert np.isfinite(last).all(), "FeaturePipeline produced NaN/Inf in last row"
