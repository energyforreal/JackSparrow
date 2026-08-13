"""Tests for MTF transformer decision policy."""

from __future__ import annotations

import pytest

from agent.core.mtf_decision_policy import (
    TfLocalStance,
    evaluate_mtf_policy,
    interpret_tf_prediction,
)


def _stance(
    tf_key: str,
    resolution: str,
    *,
    local_signal: str = "HOLD",
    direction: str = "neutral",
    path_edge: float = 0.0,
    vol_regime: str = "NORMAL",
    confidence: float = 0.7,
    size_scale: float = 1.0,
) -> TfLocalStance:
    long_edge = float(path_edge)
    short_edge = float(-path_edge)
    winning = long_edge if long_edge >= short_edge else short_edge
    return TfLocalStance(
        tf_key=tf_key,
        resolution=resolution,
        local_signal=local_signal,
        direction=direction,
        path_edge=path_edge,
        threshold=0.005,
        vol_regime=vol_regime,
        regime="neutral",
        confidence=confidence,
        quality="medium",
        risk="normal",
        trend_strength=1.0,
        mfe=0.01,
        mae=0.005,
        future_volatility=0.003,
        long_edge=long_edge,
        short_edge=short_edge,
        winning_edge=winning,
        size_scale=size_scale,
    )


def test_bias_veto_blocks_buy_when_1h_2h_bearish() -> None:
    stances = {
        "tf_5m": _stance("tf_5m", "5m", local_signal="BUY", direction="bullish", path_edge=0.01),
        "tf_15m": _stance("tf_15m", "15m", local_signal="BUY", direction="bullish", path_edge=0.01),
        "tf_30m": _stance("tf_30m", "30m", local_signal="HOLD", direction="neutral"),
        "tf_1h": _stance("tf_1h", "1h", local_signal="SELL", direction="bearish", path_edge=-0.01),
        "tf_2h": _stance("tf_2h", "2h", local_signal="SELL", direction="bearish", path_edge=-0.01),
    }
    result = evaluate_mtf_policy(stances)
    assert result.signal == "HOLD"
    assert "mtf_bias_veto" in result.reason_codes


def test_execution_from_15m_produces_buy() -> None:
    stances = {
        "tf_5m": _stance("tf_5m", "5m", local_signal="BUY", direction="bullish", path_edge=0.008),
        "tf_15m": _stance("tf_15m", "15m", local_signal="BUY", direction="bullish", path_edge=0.01),
        "tf_30m": _stance("tf_30m", "30m", local_signal="BUY", direction="bullish", path_edge=0.009),
        "tf_1h": _stance("tf_1h", "1h", local_signal="BUY", direction="bullish", path_edge=0.007),
        "tf_2h": _stance("tf_2h", "2h", local_signal="BUY", direction="bullish", path_edge=0.006),
    }
    result = evaluate_mtf_policy(stances, min_tf_alignment=3)
    assert result.signal in ("BUY", "STRONG_BUY")
    assert "mtf_15m_execution_bullish" in result.reason_codes


def test_extreme_veto_on_1h_forces_hold() -> None:
    stances = {
        "tf_15m": _stance("tf_15m", "15m", local_signal="BUY", direction="bullish", path_edge=0.01),
        "tf_1h": _stance("tf_1h", "1h", vol_regime="EXTREME"),
        "tf_2h": _stance("tf_2h", "2h"),
    }
    result = evaluate_mtf_policy(stances)
    assert result.signal == "HOLD"
    assert any("extreme_veto" in c for c in result.reason_codes)


def test_interpret_tf_prediction_from_context() -> None:
    ctx = {
        "transformer_continuous_preds": {
            "future_volatility": 0.003,
            "mae": 0.005,
            "mfe": 0.02,
            "trend_strength": 1.5,
        },
        "transformer_vol_regime": "NORMAL",
        "entry_confidence": 0.72,
        "path_edge": 0.01,
        "regime": "trending",
    }
    stance = interpret_tf_prediction(
        tf_key="tf_15m",
        prediction_context=ctx,
        bundle_metadata={"default_threshold": 0.005},
        model_name="test_15m",
    )
    assert stance.tf_key == "tf_15m"
    assert stance.local_signal in ("BUY", "STRONG_BUY")
    assert stance.direction == "bullish"
    assert stance.long_edge == pytest.approx(0.015)  # mfe - mae
    assert stance.size_scale > 0.0


def test_interpret_short_edge_stance() -> None:
    ctx = {
        "transformer_continuous_preds": {
            "future_volatility": 0.003,
            "mae": 0.02,
            "mfe": 0.005,
            "trend_strength": 1.2,
        },
        "transformer_vol_regime": "NORMAL",
        "entry_confidence": 0.7,
        "path_edge": -0.015,
        "long_edge": -0.015,
        "short_edge": 0.015,
        "regime": "neutral",
    }
    stance = interpret_tf_prediction(
        tf_key="tf_15m",
        prediction_context=ctx,
        bundle_metadata={"default_threshold": 0.005},
        model_name="test_15m",
    )
    assert stance.local_signal in ("SELL", "STRONG_SELL")
    assert stance.direction == "bearish"
    assert stance.short_edge == pytest.approx(0.015)
