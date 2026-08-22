"""Unit tests for transformer-only decision mapping."""

from __future__ import annotations

import pytest

from agent.models.transformer_context_builder import (
    build_transformer_prediction_context,
    map_prediction_to_signal,
)
from feature_store.transformer_btcusd.contract import (
    compute_long_edge,
    compute_short_edge,
    path_favorable_adverse,
)


def test_map_prediction_buy_signal() -> None:
    signal, conf, codes, size_scale = map_prediction_to_signal(
        path_edge=0.01,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.72,
        min_confidence=0.55,
        confidence_hold_floor=0.40,
    )
    assert signal == "STRONG_BUY"
    assert conf == pytest.approx(0.72)
    assert size_scale == pytest.approx(1.0)
    assert "transformer_long_edge" in codes


def test_map_prediction_hold_below_threshold() -> None:
    signal, conf, codes, size_scale = map_prediction_to_signal(
        path_edge=0.001,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.8,
    )
    assert signal == "HOLD"
    assert size_scale == pytest.approx(0.0)
    assert "transformer_below_threshold" in codes


def test_map_prediction_extreme_regime_veto() -> None:
    signal, _, codes, size_scale = map_prediction_to_signal(
        path_edge=0.02,
        threshold=0.005,
        vol_regime="EXTREME",
        confidence=0.9,
        extreme_regime_veto=True,
    )
    assert signal == "HOLD"
    assert size_scale == pytest.approx(0.0)
    assert "transformer_extreme_regime_veto" in codes


def test_map_prediction_below_hold_floor() -> None:
    signal, _, codes, size_scale = map_prediction_to_signal(
        path_edge=0.02,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.35,
        min_confidence=0.55,
        confidence_hold_floor=0.40,
    )
    assert signal == "HOLD"
    assert size_scale == pytest.approx(0.0)
    assert "transformer_below_confidence_hold_floor" in codes


def test_map_prediction_reduced_size_confidence_band() -> None:
    signal, conf, codes, size_scale = map_prediction_to_signal(
        path_edge=0.02,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.45,
        min_confidence=0.55,
        confidence_hold_floor=0.40,
        size_floor=0.35,
    )
    assert signal == "BUY"  # not STRONG in reduced band
    assert conf == pytest.approx(0.45)
    assert 0.35 <= size_scale < 1.0
    assert "transformer_reduced_size_confidence_band" in codes


def test_map_prediction_short_edge() -> None:
    signal, _, codes, size_scale = map_prediction_to_signal(
        path_edge=-0.012,
        threshold=0.005,
        vol_regime="NORMAL",
        confidence=0.7,
        long_edge=-0.012,
        short_edge=0.012,
    )
    assert signal in ("SELL", "STRONG_SELL")
    assert size_scale == pytest.approx(1.0)
    assert "transformer_short_edge" in codes


def test_path_edge_helpers() -> None:
    assert compute_long_edge(0.02, 0.005) == pytest.approx(0.015)
    assert compute_short_edge(0.02, 0.005) == pytest.approx(-0.015)
    fav, adv = path_favorable_adverse(0.02, 0.008, side="BUY")
    assert fav == pytest.approx(0.02)
    assert adv == pytest.approx(0.008)
    fav_s, adv_s = path_favorable_adverse(0.02, 0.008, side="SELL")
    assert fav_s == pytest.approx(0.008)
    assert adv_s == pytest.approx(0.02)


def test_context_stores_horizon_ladder_and_h5m_path_stats() -> None:
    ctx, _pred, _conf = build_transformer_prediction_context(
        bundle_metadata={"resolution": "5m"},
        continuous_preds={
            "h5m_mfe": 0.02,
            "h5m_mae": 0.005,
            "h5m_vol": 0.01,
            "h5m_trend_strength": 1.2,
        },
        vol_regime="NORMAL",
        regime_probs={"NORMAL": 0.8},
        bar_index_hint=0,
        resolution_minutes=5,
        future_candle_class=-1,
        future_candle_name="",
        horizon_ladder={"h5m": {"dir": 2}, "h10m": {"dir": 2}},
    )
    assert ctx["horizon_ladder"]["h5m"]["dir"] == 2
    assert ctx["transformer_future_candle_class"] == -1
    assert ctx["path_edge"] == pytest.approx(0.015)
    assert ctx["chart_pattern"] == -1
