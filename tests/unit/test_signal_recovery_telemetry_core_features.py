"""Tests for CORE_THESIS_FEATURES extraction/embedding in decision telemetry rows.

Covers the Phase 6 hardening described in
data/investigation/decision_observability_program_2026-07-11.md: telemetry rows
should carry extra["features"] for the core thesis feature subset so the
offline evidence assembler (scripts/signal_recovery/decision_evidence.py) can
source telemetry_embedded (medium-confidence) provenance without a raw
agent-log join.
"""

import json

import pytest

from agent.core.signal_recovery_telemetry import (
    CORE_THESIS_FEATURES,
    extract_core_thesis_features,
    record_decision_cycle,
)

# Keep in sync with scripts/signal_recovery/decision_evidence.CORE_THESIS_FEATURES.
_EXPECTED_CORE_FEATURES = (
    "adx_14",
    "di_spread",
    "vol_regime",
    "hurst_60",
    "h_trend",
    "h1_trend",
    "rsi_14",
    "bb_pos",
)


def test_core_thesis_features_matches_decision_evidence_contract() -> None:
    """Guards against the two feature lists drifting apart (see module docstring)."""
    assert CORE_THESIS_FEATURES == _EXPECTED_CORE_FEATURES


def test_extract_core_thesis_features_filters_and_coerces() -> None:
    raw = {
        "adx_14": "22.89",
        "di_spread": 6.1,
        "vol_regime": 1.05,
        "hurst_60": 0.48,
        "h_trend": -0.002,
        "h1_trend": 0.001,
        "rsi_14": 54.2,
        "bb_pos": 0.6,
        "not_a_core_feature": 999.0,
        "garbage": None,
    }
    out = extract_core_thesis_features(raw)
    assert set(out.keys()) == set(_EXPECTED_CORE_FEATURES)
    assert out["adx_14"] == pytest.approx(22.89)
    assert "not_a_core_feature" not in out
    assert "garbage" not in out


def test_extract_core_thesis_features_handles_missing_and_non_dict() -> None:
    assert extract_core_thesis_features(None) == {}
    assert extract_core_thesis_features({}) == {}
    assert extract_core_thesis_features({"adx_14": "not-a-number"}) == {}


def test_extract_core_thesis_features_is_case_insensitive() -> None:
    out = extract_core_thesis_features({"ADX_14": 25.0, "H_Trend": 0.01})
    assert out["adx_14"] == 25.0
    assert out["h_trend"] == 0.01


def test_record_decision_cycle_embeds_core_features(tmp_path, monkeypatch) -> None:
    telem_file = tmp_path / "decision_telemetry.ndjson"
    monkeypatch.setenv("LOGS_ROOT", str(tmp_path))

    import agent.core.signal_recovery_telemetry as srt

    monkeypatch.setattr(srt, "telemetry_path", lambda: telem_file)
    monkeypatch.setattr(srt, "_enabled", lambda: True)

    full_features = {
        "adx_14": 22.89,
        "di_spread": 6.1,
        "vol_regime": 1.05,
        "hurst_60": 0.48,
        "h_trend": -0.002,
        "h1_trend": 0.001,
        "rsi_14": 54.2,
        "bb_pos": 0.6,
        "close": 65000.0,  # non-core feature must not leak into extra.features
    }

    record_decision_cycle(
        symbol="BTCUSD",
        signal="HOLD",
        confidence=0.5,
        event="v43_prediction_complete",
        core_features=full_features,
    )

    lines = telem_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["extra"]["features"]["adx_14"] == pytest.approx(22.89)
    assert set(row["extra"]["features"].keys()) == set(_EXPECTED_CORE_FEATURES)
    assert "close" not in row["extra"]["features"]


def test_record_decision_cycle_merges_core_features_with_existing_extra(
    tmp_path, monkeypatch
) -> None:
    telem_file = tmp_path / "decision_telemetry.ndjson"

    import agent.core.signal_recovery_telemetry as srt

    monkeypatch.setattr(srt, "telemetry_path", lambda: telem_file)
    monkeypatch.setattr(srt, "_enabled", lambda: True)

    record_decision_cycle(
        symbol="BTCUSD",
        signal="LONG",
        confidence=0.7,
        event="v43_prediction_complete",
        extra={"final_long": True, "reject": None},
        core_features={"adx_14": 30.0},
    )

    row = json.loads(telem_file.read_text(encoding="utf-8").strip())
    assert row["extra"]["final_long"] is True
    assert row["extra"]["features"]["adx_14"] == 30.0


def test_record_decision_cycle_no_core_features_leaves_extra_untouched(
    tmp_path, monkeypatch
) -> None:
    telem_file = tmp_path / "decision_telemetry.ndjson"

    import agent.core.signal_recovery_telemetry as srt

    monkeypatch.setattr(srt, "telemetry_path", lambda: telem_file)
    monkeypatch.setattr(srt, "_enabled", lambda: True)

    record_decision_cycle(
        symbol="BTCUSD",
        signal="HOLD",
        confidence=0.5,
        event="v43_prediction_complete",
    )

    row = json.loads(telem_file.read_text(encoding="utf-8").strip())
    assert "extra" not in row
