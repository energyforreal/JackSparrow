"""Live forecast signal map, horizon lock, and unapproved-bundle refusal."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.core.forecast_policy import (
    FORECAST_DECISION_PATH,
    apply_horizon_lock,
    build_forecast_execution_plan,
    clear_forecast_entries,
    map_forecast_signal,
    promoted_forecast_bundle,
    remember_forecast_entry,
    resolve_transformer_decision_path,
)
from agent.models.forecast_node import ForecastModelNode
from research.forecast_30m.inference import map_direction_signal


@pytest.fixture(autouse=True)
def _reset_horizon_locks() -> None:
    clear_forecast_entries()
    yield
    clear_forecast_entries()


def test_direction_map_emits_buy_sell_and_hold() -> None:
    assert map_direction_signal("BULLISH", 0.80, 0.35) == "BUY"
    assert map_direction_signal("BEARISH", 0.80, 0.35) == "SELL"
    assert map_direction_signal("NEUTRAL", 0.90, 0.35) == "HOLD"
    assert map_direction_signal("BULLISH", 0.20, 0.35) == "HOLD"


def test_forecast_signal_reasons_match_the_class() -> None:
    buy, buy_reasons = map_forecast_signal("BULLISH", 0.70, 0.35)
    sell, sell_reasons = map_forecast_signal("BEARISH", 0.70, 0.35)
    hold, hold_reasons = map_forecast_signal("NEUTRAL", 0.90, 0.35)
    assert buy == "BUY"
    assert sell == "SELL"
    assert hold == "HOLD"
    assert "forecast_buy" in buy_reasons
    assert "forecast_sell" in sell_reasons
    assert "forecast_neutral" in hold_reasons


def test_horizon_lock_skips_a_signal_inside_twelve_hours() -> None:
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    remember_forecast_entry("BTCUSD", now - timedelta(hours=3))
    signal, reasons = apply_horizon_lock("BUY", symbol="BTCUSD", now=now)
    assert signal == "HOLD"
    assert "forecast_horizon_busy" in reasons


def test_horizon_lock_allows_a_signal_after_twelve_hours() -> None:
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    remember_forecast_entry("BTCUSD", now - timedelta(hours=13))
    signal, reasons = apply_horizon_lock("SELL", symbol="BTCUSD", now=now)
    assert signal == "SELL"
    assert reasons == []


def test_execution_plan_is_empty_on_hold() -> None:
    assert build_forecast_execution_plan(
        signal="HOLD",
        confidence=0.0,
        size_fraction=0.0,
        reason_codes=["forecast_neutral"],
    ) == {}


def test_execution_plan_uses_twelve_hour_atr_brackets() -> None:
    plan = build_forecast_execution_plan(
        signal="BUY",
        confidence=0.7,
        size_fraction=0.07,
        reason_codes=["forecast_buy"],
    )
    assert plan["duration_minutes"] == 720
    assert plan["max_hold_minutes"] == 720
    assert plan["sl_tp_source"] == "atr"


def test_forecast_node_refuses_orders_enabled_false(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"orders_enabled": False, "spec_version": "forecast-30m-h24-v5"}),
        encoding="utf-8",
    )
    (tmp_path / "models.joblib").write_bytes(b"placeholder")
    with pytest.raises(RuntimeError, match="not approved"):
        ForecastModelNode.from_bundle_dir(tmp_path)


def test_promoted_bundle_requires_orders_enabled(tmp_path: Path) -> None:
    bundle = tmp_path / "JackSparrow_Forecast_BTCUSD_30m"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"orders_enabled": False}),
        encoding="utf-8",
    )
    (bundle / "models.joblib").write_bytes(b"placeholder")
    assert promoted_forecast_bundle(tmp_path) is None


def test_resolve_path_stays_fusion_without_a_promoted_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRANSFORMER_DECISION_PATH", raising=False)
    assert resolve_transformer_decision_path(tmp_path) in {
        "mtf_fusion",
        FORECAST_DECISION_PATH,
    }
    assert resolve_transformer_decision_path(tmp_path) == "mtf_fusion"


def test_explicit_fusion_env_is_the_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "JackSparrow_Forecast_BTCUSD_30m"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"orders_enabled": True}),
        encoding="utf-8",
    )
    (bundle / "models.joblib").write_bytes(b"placeholder")
    monkeypatch.setenv("TRANSFORMER_DECISION_PATH", "mtf_fusion")
    assert resolve_transformer_decision_path(tmp_path) == "mtf_fusion"
    monkeypatch.setenv("TRANSFORMER_DECISION_PATH", "forecast_30m")
    assert resolve_transformer_decision_path(tmp_path) == FORECAST_DECISION_PATH
