"""Unit tests for path-prediction SL/TP, soft R:R, and sizing helpers."""

from __future__ import annotations

import pytest

from agent.core.path_execution_plan import (
    apply_soft_rr,
    build_execution_plan,
    compute_edge_confidence_size_scale,
    compute_path_stop_take_pcts,
    compute_path_stop_take_prices,
)


def test_long_path_pcts() -> None:
    sl, tp, fav, adv = compute_path_stop_take_pcts(
        mfe=0.02, mae=0.01, signal="BUY", sl_adverse_mult=1.0, tp_favorable_mult=1.0
    )
    assert fav == pytest.approx(0.02)
    assert adv == pytest.approx(0.01)
    assert sl == pytest.approx(0.01)
    assert tp == pytest.approx(0.02)


def test_short_path_pcts_use_mae_as_favorable() -> None:
    sl, tp, fav, adv = compute_path_stop_take_pcts(
        mfe=0.02, mae=0.01, signal="SELL", sl_adverse_mult=1.0, tp_favorable_mult=1.0
    )
    # Short: favorable=mae (down), adverse=mfe (up)
    assert fav == pytest.approx(0.01)
    assert adv == pytest.approx(0.02)
    assert sl == pytest.approx(0.02)
    assert tp == pytest.approx(0.01)


def test_soft_rr_never_holds() -> None:
    sig, scale, action, codes = apply_soft_rr(
        signal="STRONG_BUY",
        size_scale=1.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.015,  # R:R = 0.75 < 1.2
        min_risk_reward_ratio=1.2,
        rr_size_factor=0.7,
    )
    assert sig == "BUY"
    assert scale == pytest.approx(0.7)
    assert action == "strip_strong"
    assert "path_rr_reduce_size" in codes


def test_soft_rr_buy_only_reduces_size() -> None:
    sig, scale, action, codes = apply_soft_rr(
        signal="BUY",
        size_scale=1.0,
        stop_loss_pct=0.02,
        take_profit_pct=0.01,
        min_risk_reward_ratio=1.2,
        rr_size_factor=0.7,
    )
    assert sig == "BUY"
    assert scale == pytest.approx(0.7)
    assert action == "reduce_size"


def test_edge_confidence_size_scale() -> None:
    scale = compute_edge_confidence_size_scale(
        size_scale=1.0,
        winning_edge=0.005,
        threshold=0.005,
        size_floor=0.35,
        edge_weight=1.0,
    )
    assert scale == pytest.approx(1.0)
    scale_low = compute_edge_confidence_size_scale(
        size_scale=0.5,
        winning_edge=0.0025,
        threshold=0.005,
        size_floor=0.35,
        edge_weight=1.0,
    )
    assert scale_low >= 0.35
    assert scale_low < 1.0


def test_path_stop_take_prices_long() -> None:
    sl, tp, fav, adv = compute_path_stop_take_prices(
        100_000.0,
        signal="BUY",
        mfe=0.02,
        mae=0.01,
    )
    assert sl is not None and tp is not None
    assert sl < 100_000.0 < tp
    assert fav == pytest.approx(0.02)
    assert adv == pytest.approx(0.01)


def test_build_execution_plan_fields() -> None:
    plan = build_execution_plan(
        signal="STRONG_BUY",
        confidence=0.8,
        size_scale=1.0,
        long_edge=0.02,
        short_edge=-0.02,
        winning_edge=0.02,
        threshold=0.005,
        primary_tf="tf_15m",
        mfe=0.03,
        mae=0.01,
        future_volatility=0.003,
        vol_regime="NORMAL",
        reason_codes=["mtf_ok"],
        entry_portfolio_margin_fraction=0.6,
    )
    assert plan["signal"] in ("BUY", "STRONG_BUY")
    assert "stop_loss_pct" in plan
    assert "take_profit_pct" in plan
    assert plan["size_fraction"] > 0
    assert plan["primary_tf"] == "tf_15m"
    assert "rr_soft_action" in plan
