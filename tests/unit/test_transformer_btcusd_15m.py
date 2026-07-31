"""Unit tests for BTCUSD 15m transformer integration."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent.models.transformer_context_builder import (
    build_transformer_prediction_context,
    expected_return_for_horizon,
)
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEYS, V43_HORIZON_KEY_TO_BARS
from feature_store.transformer_btcusd_15m.contract import (
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    HORIZON_RETURN_COLS,
    PATH_LABEL_HORIZON_BARS,
    RETURN_HORIZON_BARS,
    TRANSFORMER_MODEL_FAMILY,
    max_label_horizon_bars,
)
from feature_store.transformer_btcusd_15m.features import add_features, build_feature_matrix
from feature_store.transformer_btcusd_15m.inference import (
    build_inference_window,
    unstandardize_continuous,
    zscore_window,
)
from feature_store.transformer_btcusd_15m.labels import (
    compute_market_labels,
    trim_label_tail,
)
from scripts.colab.transformer_data import validate_derivatives_coverage


def _synthetic_ohlcv(n: int = 300) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = 50000 + np.cumsum(np.random.default_rng(42).normal(0, 20, n))
    return pd.DataFrame(
        {
            "time": ts,
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.full(n, 100.0),
            "funding_rate": np.linspace(0.0001, 0.0002, n),
            "open_interest": np.linspace(1e6, 1.1e6, n),
        }
    )


def _transformer_metadata() -> dict:
    thr = 0.005
    horizons = {}
    for key in V43_HORIZON_KEYS:
        fb = V43_HORIZON_KEY_TO_BARS[key]
        horizons[key] = {
            "forward_bars": fb,
            "horizon_minutes": fb * 5,
            "horizon_key": key,
            "validation_metrics": {
                "dynamic_threshold": thr,
                "short_threshold": thr,
            },
            "dynamic_threshold": thr,
            "short_threshold": thr,
        }
    return {
        "version": "transformer_v2",
        "model_name": "jacksparrow_transformer_test",
        "model_family": TRANSFORMER_MODEL_FAMILY,
        "path_label_horizon_bars": PATH_LABEL_HORIZON_BARS,
        "return_horizon_bars": dict(RETURN_HORIZON_BARS),
        "primary_execution_horizon_bars": 2,
        "default_threshold": thr,
        "horizons": horizons,
    }


def test_add_features_produces_all_feature_cols() -> None:
    feat_df = build_feature_matrix(_synthetic_ohlcv(300), dropna=True)
    for col in FEATURE_COLS:
        assert col in feat_df.columns
    assert len(feat_df) >= 128


def test_build_inference_window_shape() -> None:
    feat_df = build_feature_matrix(_synthetic_ohlcv(300), dropna=True)
    values = feat_df[list(FEATURE_COLS)].values.astype(np.float32)
    window = build_inference_window(values, window_len=128)
    assert window.shape == (1, 128, len(FEATURE_COLS))
    assert np.isfinite(window).all()


def test_zscore_window_zero_mean_unit_scale() -> None:
    raw = np.random.default_rng(1).normal(size=(128, 4)).astype(np.float32)
    normed = zscore_window(raw)
    assert abs(float(normed.mean())) < 0.05
    assert abs(float(normed.std()) - 1.0) < 0.2


def test_unstandardize_continuous_roundtrip() -> None:
    mean = np.zeros(len(CONTINUOUS_LABEL_COLS))
    std = np.ones(len(CONTINUOUS_LABEL_COLS))
    z = np.random.default_rng(0).normal(size=len(CONTINUOUS_LABEL_COLS))
    out = unstandardize_continuous(z, mean, std)
    assert set(out.keys()) == set(CONTINUOUS_LABEL_COLS)
    assert out[HORIZON_RETURN_COLS[0]] == pytest.approx(float(z[0]))


def test_multi_horizon_labels_no_lookahead() -> None:
    raw = _synthetic_ohlcv(300)
    feat = add_features(raw).dropna().reset_index(drop=True)
    labeled = compute_market_labels(
        feat,
        return_horizon_bars=RETURN_HORIZON_BARS,
        path_label_horizon_bars=PATH_LABEL_HORIZON_BARS,
        mae_floor_atr_mult=0.25,
    )
    trimmed = trim_label_tail(
        labeled,
        return_horizon_bars=RETURN_HORIZON_BARS,
        path_label_horizon_bars=PATH_LABEL_HORIZON_BARS,
    )
    max_h = max_label_horizon_bars()
    assert len(trimmed) == len(labeled) - (max_h + 1)

    i = 50
    assert i + RETURN_HORIZON_BARS["scalp_10m"] < len(trimmed)
    entry = float(trimmed.loc[i, "close"])
    h_scalp = RETURN_HORIZON_BARS["scalp_10m"]
    expected = (float(trimmed.loc[i + h_scalp, "close"]) - entry) / entry
    assert trimmed.loc[i, "future_return_scalp_10m"] == pytest.approx(expected, rel=1e-6)


def test_build_transformer_prediction_context_multi_head_direct() -> None:
    preds = {col: 0.0 for col in CONTINUOUS_LABEL_COLS}
    preds.update(
        {
            "future_return_scalp_10m": 0.004,
            "future_return_intraday_30m": 0.008,
            "future_return_trend_1h": 0.012,
            "future_return_swing_2h": 0.020,
            "mfe": 0.02,
            "mae": 0.008,
            "future_volatility": 0.003,
            "trend_strength": 1.6,
        }
    )
    ctx, pred_val, conf = build_transformer_prediction_context(
        bundle_metadata=_transformer_metadata(),
        continuous_preds=preds,
        vol_regime="NORMAL",
        regime_probs={"LOW": 0.1, "NORMAL": 0.7, "HIGH": 0.15, "EXTREME": 0.05},
        bar_index_hint=50,
        short_enabled=False,
        label_horizon_bars=PATH_LABEL_HORIZON_BARS,
    )
    heads = ctx["multi_horizon_heads"]
    assert set(heads.keys()) == set(V43_HORIZON_KEYS)
    assert heads["scalp_10m"]["expected_return"] == pytest.approx(0.004)
    assert heads["intraday_30m"]["expected_return"] == pytest.approx(0.008)
    assert heads["trend_1h"]["expected_return"] == pytest.approx(0.012)
    assert heads["swing_2h"]["expected_return"] == pytest.approx(0.020)
    assert ctx["transformer_legacy_horizon_scaling"] is False
    assert ctx["format"] == "jacksparrow_transformer_btcusd_15m"
    assert -1.0 <= pred_val <= 1.0
    assert 0.0 <= conf <= 1.0


def test_legacy_future_return_scaling_fallback() -> None:
    preds = {
        "future_return": 0.48,
        "future_volatility": 0.003,
        "mae": 0.008,
        "mfe": 0.02,
        "trend_strength": 1.0,
    }
    er_scalp = expected_return_for_horizon(
        "scalp_10m",
        preds,
        label_horizon_bars=32,
        resolution_minutes=15,
    )
    assert er_scalp < preds["future_return"]
    assert er_scalp > 0.0

    ctx, _, _ = build_transformer_prediction_context(
        bundle_metadata=_transformer_metadata(),
        continuous_preds=preds,
        vol_regime="NORMAL",
        regime_probs={"NORMAL": 1.0},
        bar_index_hint=0,
        short_enabled=True,
        label_horizon_bars=32,
    )
    assert ctx["transformer_legacy_horizon_scaling"] is True


def test_validate_derivatives_coverage_ok() -> None:
    df = _synthetic_ohlcv(50)
    report = validate_derivatives_coverage(df, min_coverage=0.5, warn_coverage=0.9)
    assert report["worst_coverage"] >= 0.9


def test_validate_derivatives_coverage_raises() -> None:
    df = _synthetic_ohlcv(50)
    df["funding_rate"] = np.nan
    df["open_interest"] = np.nan
    with pytest.raises(ValueError, match="coverage below minimum"):
        validate_derivatives_coverage(df, min_coverage=0.5)


def test_transformer_metadata_bundle_manifest(tmp_path: Path) -> None:
    bundle = Path("agent/model_storage/JackSparrow_Transformer_BTCUSD/metadata_transformer.json")
    if not bundle.is_file():
        pytest.skip("bundle manifest not present")
    raw = json.loads(bundle.read_text(encoding="utf-8"))
    assert raw["model_family"] == TRANSFORMER_MODEL_FAMILY
    assert raw["version"] == "transformer_v2"
    assert "return_horizon_bars" in raw
    assert "horizons" in raw
