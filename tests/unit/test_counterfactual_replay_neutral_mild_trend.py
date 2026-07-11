"""Tests for the neutral_mild_trend counterfactual replay scenario.

Validates that the replay-side predicate in tools/commands/counterfactual_replay.py
mirrors agent_thesis_engine._eval_neutral_mild_trend_long (the prototype rule
behind AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED=false), and that it sources
features from extra["features"] (Phase 6 telemetry hardening) with a
reason-code fallback for older rows — never defaulting missing features.
"""

from tools.commands.counterfactual_replay import (
    ENTRY_SIGNALS,
    _core_features_from_row,
    _neutral_mild_trend_fires,
    _scenario_included,
    extract_candidates,
)


def _v43_row(**overrides):
    row = {
        "event": "v43_prediction_complete",
        "ts": "2026-07-11T13:00:00+00:00",
        "symbol": "BTCUSD",
        "signal": "HOLD",
        "signals": {"ml_gated": "LONG"},
        "policy_reason_codes": ["regime=neutral", "hypothesis_no_rule_fired"],
        "trade_score": 45.0,
    }
    row.update(overrides)
    return row


def test_core_features_from_extra_features_takes_precedence() -> None:
    row = {
        "extra": {"features": {"adx_14": 18.0}},
        "policy_reason_codes": ["adx_14=99.0"],
    }
    feats = _core_features_from_row(row)
    assert feats["adx_14"] == 18.0  # extra.features wins over reason-code fallback


def test_core_features_falls_back_to_reason_codes() -> None:
    row = {
        "policy_reason_codes": [
            "regime=neutral",
            "adx_14=18.50",
            "h1_trend=0.0021",
            "h_trend=0.0013",
        ]
    }
    feats = _core_features_from_row(row)
    assert feats["adx_14"] == 18.50
    assert feats["h1_trend"] == 0.0021
    assert feats["h_trend"] == 0.0013


def test_neutral_mild_trend_fires_requires_all_three_features() -> None:
    row = _v43_row(
        policy_reason_codes=["regime=neutral", "adx_14=18.0", "h1_trend=0.001"]
        # h_trend missing -> must not fire (no defaulting)
    )
    assert _neutral_mild_trend_fires(row, "neutral") is False


def test_neutral_mild_trend_fires_true_case() -> None:
    row = _v43_row(
        policy_reason_codes=[
            "regime=neutral",
            "adx_14=18.0",
            "h1_trend=0.0021",
            "h_trend=0.0013",
        ]
    )
    assert _neutral_mild_trend_fires(row, "neutral") is True


def test_neutral_mild_trend_respects_adx_ceiling() -> None:
    row = _v43_row(
        policy_reason_codes=[
            "regime=neutral",
            "adx_14=30.0",  # above default 22.0 ceiling
            "h1_trend=0.0021",
            "h_trend=0.0013",
        ]
    )
    assert _neutral_mild_trend_fires(row, "neutral") is False


def test_neutral_mild_trend_only_fires_in_neutral_regime() -> None:
    row = _v43_row(
        policy_reason_codes=[
            "regime=trending",
            "adx_14=18.0",
            "h1_trend=0.0021",
            "h_trend=0.0013",
        ]
    )
    assert _neutral_mild_trend_fires(row, "trending") is False


def test_extract_candidates_flags_neutral_mild_trend() -> None:
    rows = [
        _v43_row(
            policy_reason_codes=[
                "regime=neutral",
                "adx_14=18.0",
                "h1_trend=0.0021",
                "h_trend=0.0013",
            ]
        )
    ]
    candidates = extract_candidates(rows)
    assert len(candidates) == 1
    assert candidates[0]["neutral_mild_trend_fires"] is True


def test_scenario_included_excludes_rows_current_already_entered() -> None:
    """Incremental-candidate framing: don't double-count trades `current` already takes."""
    candidate = {
        "ml_direction": "LONG",
        "policy_signal": "LONG",
        "handler_reject": None,  # current scenario would already execute this
        "trade_score": 60.0,
        "flat_thesis": False,
        "neutral_mild_trend_fires": True,
    }
    assert _scenario_included("current", candidate) is True
    assert _scenario_included("neutral_mild_trend", candidate) is False


def test_scenario_included_captures_hold_at_synthesis_rejects() -> None:
    candidate = {
        "ml_direction": "LONG",
        "policy_signal": "HOLD",
        "handler_reject": "hold_at_synthesis",
        "trade_score": 45.0,
        "flat_thesis": True,
        "neutral_mild_trend_fires": True,
    }
    assert _scenario_included("current", candidate) is False
    assert _scenario_included("neutral_mild_trend", candidate) is True


def test_scenario_included_requires_rule_fire_and_long_direction() -> None:
    base = {
        "policy_signal": "HOLD",
        "handler_reject": "hold_at_synthesis",
        "trade_score": 45.0,
        "flat_thesis": True,
    }
    not_fired = {**base, "ml_direction": "LONG", "neutral_mild_trend_fires": False}
    short_dir = {**base, "ml_direction": "SHORT", "neutral_mild_trend_fires": True}
    assert _scenario_included("neutral_mild_trend", not_fired) is False
    assert _scenario_included("neutral_mild_trend", short_dir) is False
