"""Unit tests for agent market understanding (views + synthesis)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from agent.core.market_understanding import (
    TfMarketView,
    build_tf_market_view,
    synthesize_agent_decision,
    typical_abs_edge_from_metadata,
)


def _meta(
    *,
    mfe_mean: float = 0.007,
    mae_mean: float = 0.007,
    mfe_std: float = 0.008,
    mae_std: float = 0.008,
    default_threshold: float = 0.005,
    path_bars: int = 16,
) -> Dict[str, Any]:
    return {
        "default_threshold": default_threshold,
        "path_label_horizon_bars": path_bars,
        "label_mean": [mfe_mean, mae_mean, 0.002, 1.5, 0.002, 0.05, 0.2],
        "label_std": [mfe_std, mae_std, 0.001, 1.0, 0.001, 0.1, 0.5],
    }


def _ctx(
    *,
    mfe: float,
    mae: float,
    vol_regime: str = "NORMAL",
    future_volatility: float = 0.003,
    trend_strength: float = 1.2,
    drawdown_before_mfe: float = 0.0,
    future_oi_change_pct: float = 0.0,
) -> Dict[str, Any]:
    path_edge = mfe - mae
    return {
        "path_edge": path_edge,
        "long_edge": path_edge,
        "short_edge": -path_edge,
        "transformer_vol_regime": vol_regime,
        "transformer_continuous_preds": {
            "mfe": mfe,
            "mae": mae,
            "future_volatility": future_volatility,
            "trend_strength": trend_strength,
            "drawdown_before_mfe": drawdown_before_mfe,
            "future_oi_change_pct": future_oi_change_pct,
        },
    }


def test_typical_abs_edge_uses_std_when_means_symmetric() -> None:
    typical = typical_abs_edge_from_metadata(_meta(mfe_mean=0.01, mae_mean=0.01, mfe_std=0.012))
    assert typical == pytest.approx(0.5 * (0.012 + 0.008), rel=1e-3)


def test_build_view_scale_differs_by_tf_metadata() -> None:
    # Same raw edge, different typical scale => different z
    ctx = _ctx(mfe=0.015, mae=0.005)  # edge +0.01
    tight = build_tf_market_view(
        tf_key="tf_15m",
        prediction_context=ctx,
        bundle_metadata=_meta(mfe_std=0.004, mae_std=0.004),
    )
    wide = build_tf_market_view(
        tf_key="tf_1h",
        prediction_context=ctx,
        bundle_metadata=_meta(mfe_std=0.02, mae_std=0.02),
    )
    assert abs(tight.path_imbalance_z) > abs(wide.path_imbalance_z)


def test_5m_view_never_emits_trade_stances() -> None:
    view = build_tf_market_view(
        tf_key="tf_5m",
        prediction_context=_ctx(mfe=0.03, mae=0.005),
        bundle_metadata=_meta(),
        setup_direction="long",
    )
    assert view.climate_stance is None
    assert view.setup_stance is None
    assert view.timing_stance in ("with", "against", "quiet")


def test_5m_without_setup_direction_is_quiet() -> None:
    view = build_tf_market_view(
        tf_key="tf_5m",
        prediction_context=_ctx(mfe=0.03, mae=0.005),
        bundle_metadata=_meta(),
        setup_direction=None,
    )
    assert view.timing_stance == "quiet"


def test_mild_2h_edge_is_two_sided() -> None:
    # typical ~0.008 from std; edge 0.003 => z ~0.375 < 0.75
    view = build_tf_market_view(
        tf_key="tf_2h",
        prediction_context=_ctx(mfe=0.009, mae=0.006),
        bundle_metadata=_meta(mfe_std=0.008, mae_std=0.008),
    )
    assert view.climate_stance == "two_sided"


def test_extreme_vol_on_1h_is_crisis() -> None:
    view = build_tf_market_view(
        tf_key="tf_1h",
        prediction_context=_ctx(mfe=0.02, mae=0.005, vol_regime="EXTREME"),
        bundle_metadata=_meta(),
    )
    assert view.climate_stance == "crisis"


def test_15m_setup_long_path() -> None:
    view = build_tf_market_view(
        tf_key="tf_15m",
        prediction_context=_ctx(mfe=0.02, mae=0.005),
        bundle_metadata=_meta(mfe_std=0.008, mae_std=0.008),
    )
    assert view.setup_stance == "long_path"
    assert view.climate_stance is None
    assert view.imbalance_ratio > 0
    assert view.drawdown_before_mfe == pytest.approx(0.0)


def test_15m_drawdown_flattens_setup() -> None:
    view = build_tf_market_view(
        tf_key="tf_15m",
        prediction_context=_ctx(mfe=0.02, mae=0.005, drawdown_before_mfe=0.005),
        bundle_metadata=_meta(mfe_std=0.008, mae_std=0.008),
    )
    assert view.setup_stance == "flat"


def test_15m_low_trend_flattens_mild_setup() -> None:
    # edge z ~1.0 (between PATH and STRONG), trend below floor
    view = build_tf_market_view(
        tf_key="tf_15m",
        prediction_context=_ctx(mfe=0.014, mae=0.006, trend_strength=0.5),
        bundle_metadata=_meta(mfe_std=0.008, mae_std=0.008),
    )
    assert view.setup_stance == "flat"


def test_30m_is_setup_not_climate() -> None:
    view = build_tf_market_view(
        tf_key="tf_30m",
        prediction_context=_ctx(mfe=0.02, mae=0.005),
        bundle_metadata=_meta(),
    )
    assert view.setup_stance == "long_path"
    assert view.climate_stance is None


def test_last_night_like_tiny_edges_are_ranging_flat() -> None:
    """LOW-vol sub-threshold residuals → climate ranging, setup flat."""
    views = {
        "tf_1h": build_tf_market_view(
            tf_key="tf_1h",
            prediction_context=_ctx(mfe=0.008, mae=0.006, vol_regime="LOW", trend_strength=0.6),
            bundle_metadata=_meta(),
        ),
        "tf_2h": build_tf_market_view(
            tf_key="tf_2h",
            prediction_context=_ctx(mfe=0.009, mae=0.0065, vol_regime="LOW", trend_strength=0.5),
            bundle_metadata=_meta(),
        ),
        "tf_15m": build_tf_market_view(
            tf_key="tf_15m",
            prediction_context=_ctx(mfe=0.0075, mae=0.007, vol_regime="LOW", trend_strength=0.5),
            bundle_metadata=_meta(),
        ),
        "tf_30m": build_tf_market_view(
            tf_key="tf_30m",
            prediction_context=_ctx(mfe=0.0072, mae=0.0065, vol_regime="LOW"),
            bundle_metadata=_meta(),
        ),
        "tf_5m": build_tf_market_view(
            tf_key="tf_5m",
            prediction_context=_ctx(mfe=0.006, mae=0.0062, vol_regime="LOW"),
            bundle_metadata=_meta(),
            setup_direction=None,
        ),
    }
    assert views["tf_1h"].climate_stance == "two_sided"
    assert views["tf_15m"].setup_stance == "flat"
    state = synthesize_agent_decision(views)
    assert state.wire_signal == "HOLD"
    assert state.climate == "two_sided"
    assert state.path_edge == pytest.approx(views["tf_15m"].path_edge)


def _views(
    *,
    climate_1h: str = "long",
    climate_2h: str = "long",
    setup_15: str = "long_path",
    setup_30: str = "long_path",
    timing_z: float = 1.5,
    extreme: bool = False,
    oi_15: float = 0.05,
) -> Dict[str, TfMarketView]:
    """Build a minimal view map for synthesizer tests."""

    def climate_view(tf: str, stance: str) -> TfMarketView:
        z = 1.2 if stance == "long" else (-1.2 if stance == "short" else 0.1)
        if stance == "crisis":
            z = 0.0
        return TfMarketView(
            tf_key=tf,
            resolution=tf.replace("tf_", ""),
            horizon_minutes=480,
            mfe=0.012,
            mae=0.006,
            path_edge=z * 0.008,
            long_edge=z * 0.008,
            short_edge=-z * 0.008,
            path_imbalance_z=z,
            typical_abs_edge=0.008,
            vol_regime="EXTREME" if stance == "crisis" or extreme else "NORMAL",
            future_volatility=0.004,
            trend_strength=1.2,
            quality="medium",
            risk="extreme" if stance == "crisis" else "normal",
            climate_stance=stance,
        )

    def setup_view(tf: str, stance: str, *, oi: float = 0.0) -> TfMarketView:
        z = 1.5 if stance == "long_path" else (-1.5 if stance == "short_path" else 0.1)
        return TfMarketView(
            tf_key=tf,
            resolution=tf.replace("tf_", ""),
            horizon_minutes=240,
            mfe=0.02 if stance == "long_path" else 0.005,
            mae=0.005 if stance == "long_path" else 0.02,
            path_edge=z * 0.008,
            long_edge=z * 0.008,
            short_edge=-z * 0.008,
            path_imbalance_z=z,
            typical_abs_edge=0.008,
            vol_regime="NORMAL",
            future_volatility=0.003,
            trend_strength=1.5,
            quality="high",
            risk="normal",
            setup_stance=stance,
            future_oi_change_pct=oi,
            drawdown_before_mfe=0.0,
            imbalance_ratio=float(z) / (abs(z) + 1.0),
        )

    timing = TfMarketView(
        tf_key="tf_5m",
        resolution="5m",
        horizon_minutes=240,
        mfe=0.015,
        mae=0.005,
        path_edge=timing_z * 0.008,
        long_edge=timing_z * 0.008,
        short_edge=-timing_z * 0.008,
        path_imbalance_z=timing_z,
        typical_abs_edge=0.008,
        vol_regime="NORMAL",
        future_volatility=0.002,
        trend_strength=1.0,
        quality="medium",
        risk="normal",
        timing_stance=None,
    )
    return {
        "tf_1h": climate_view("tf_1h", climate_1h),
        "tf_2h": climate_view("tf_2h", climate_2h),
        "tf_15m": setup_view("tf_15m", setup_15, oi=oi_15),
        "tf_30m": setup_view("tf_30m", setup_30),
        "tf_5m": timing,
    }


def test_synth_crisis_forces_flat() -> None:
    state = synthesize_agent_decision(
        _views(climate_1h="crisis", climate_2h="long", setup_15="long_path")
    )
    assert state.thesis == "flat"
    assert state.wire_signal == "HOLD"
    assert "climate_crisis" in state.reason_codes


def test_synth_ranging_forces_flat() -> None:
    state = synthesize_agent_decision(
        _views(climate_1h="two_sided", climate_2h="two_sided", setup_15="long_path")
    )
    assert state.thesis == "flat"
    assert "climate_ranging" in state.reason_codes


def test_synth_conflicted_forces_flat() -> None:
    state = synthesize_agent_decision(
        _views(climate_1h="long", climate_2h="short", setup_15="long_path")
    )
    assert state.thesis == "flat"
    assert "climate_conflicted" in state.reason_codes


def test_synth_5m_hot_alone_cannot_trade() -> None:
    # Flat setup + strong timing z
    state = synthesize_agent_decision(
        _views(setup_15="flat", timing_z=2.0)
    )
    assert state.thesis == "flat"
    assert state.wire_signal == "HOLD"


def test_synth_aligned_long_with_timing() -> None:
    state = synthesize_agent_decision(_views(timing_z=1.5))
    assert state.thesis == "long"
    assert state.wire_signal in ("BUY", "STRONG_BUY")
    assert state.primary_tf == "tf_15m"
    assert state.timing == "with"


def test_synth_timing_against_forces_flat() -> None:
    state = synthesize_agent_decision(_views(timing_z=-1.5))
    assert state.thesis == "flat"
    assert state.timing == "against"
    assert "timing_against_flat" in state.reason_codes


def test_synth_setup_fights_climate() -> None:
    state = synthesize_agent_decision(
        _views(climate_1h="long", climate_2h="long", setup_15="short_path", timing_z=-1.5)
    )
    assert state.thesis == "flat"
    assert "setup_fights_climate" in state.reason_codes


def test_synth_30m_opposed_caps_strong() -> None:
    state = synthesize_agent_decision(
        _views(setup_30="short_path", timing_z=1.5)
    )
    assert state.thesis == "long"
    assert state.wire_signal == "BUY"  # not STRONG
    assert "setup_30m_opposed_cap" in state.reason_codes


def test_synth_quiet_timing_no_strong() -> None:
    state = synthesize_agent_decision(_views(timing_z=0.2))
    assert state.thesis == "long"
    assert state.wire_signal == "BUY"
    assert state.timing == "quiet"


def test_synth_oi_opposing_caps_strong() -> None:
    state = synthesize_agent_decision(_views(timing_z=1.5, oi_15=-0.05))
    assert state.thesis == "long"
    assert state.wire_signal == "BUY"
    assert "oi_opposing_cap_strong" in state.reason_codes


def test_synth_hold_preserves_15m_path_edge() -> None:
    state = synthesize_agent_decision(
        _views(climate_1h="two_sided", climate_2h="two_sided", setup_15="long_path")
    )
    assert state.wire_signal == "HOLD"
    assert state.path_edge != 0.0
    assert state.primary_tf == "tf_15m"
