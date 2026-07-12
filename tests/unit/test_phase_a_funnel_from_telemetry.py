"""Unit tests for Phase A funnel telemetry helper."""

from __future__ import annotations

import json
from pathlib import Path

from tools.commands.phase_a_funnel_from_telemetry import analyze_rows, render_markdown


def test_analyze_rows_funnel_layers() -> None:
    rows = [
        {
            "ts": "2026-07-12T11:00:00+00:00",
            "event": "v43_prediction_complete",
            "thesis_signal": "SHORT",
            "signal": "HOLD",
            "policy_reason_codes": [
                "thesis_type=trend_continuation",
                "thesis_trend_continuation_short",
                "agent_thesis_entry",
                "quality_below_floor",
                "quality_score=47.1",
                "min_score=55.0",
            ],
            "gates": {"g5_pass": False},
            "extra": {
                "features": {
                    "adx_14": 20,
                    "di_spread": -1,
                    "vol_regime": 0.9,
                    "hurst_60": 0.05,
                    "h_trend": -0.001,
                    "h1_trend": -0.001,
                    "rsi_14": 55,
                    "bb_pos": 0.7,
                    "hurst_60_v2": 0.55,
                }
            },
        },
        {
            "ts": "2026-07-12T12:00:00+00:00",
            "event": "v43_prediction_complete",
            "thesis_signal": "HOLD",
            "signal": "HOLD",
            "policy_reason_codes": ["thesis_type=flat", "hypothesis_no_rule_fired"],
            "gates": {"g5_pass": True},
            "extra": {"features": {"hurst_60": 0.0, "hurst_60_v2": 0.5}},
        },
    ]
    report = analyze_rows(rows)
    assert report["thesis_fires"] == 1
    assert report["quality_below_floor"] == 1
    assert report["gate5_fail"] == 1
    assert report["hold_after_thesis_fire"] == 1
    assert report["dual_write_both_hurst"] == 2
    md = render_markdown(report)
    assert "Thesis fires" in md
    assert "Gate5 fail" in md


def test_load_and_write(tmp_path: Path) -> None:
    from tools.commands.phase_a_funnel_from_telemetry import load_telemetry

    tel = tmp_path / "t.ndjson"
    tel.write_text(
        json.dumps(
            {
                "ts": "2026-07-12T13:00:00+00:00",
                "event": "v43_prediction_complete",
                "thesis_signal": "HOLD",
                "signal": "HOLD",
                "policy_reason_codes": [],
                "extra": {"features": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rows = load_telemetry(tel, hours=0, since=None)
    assert len(rows) == 1
