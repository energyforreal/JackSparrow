"""Threshold adapter regime segmentation tests."""

from __future__ import annotations

from agent.learning.threshold_adapter import _extract_regime_from_row, _segment_rows_by_regime


def _row(regime: str, pnl: float = 1.0) -> dict:
    return {
        "pnl": pnl,
        "metadata": {
            "decision_context": {
                "rule_based_pipeline": {
                    "market_state": {"regime": regime},
                }
            }
        },
    }


def test_extract_regime_from_row_unknown_when_missing():
    assert _extract_regime_from_row({}) == "unknown"


def test_segment_rows_by_regime_filters_dominant():
    rows = [_row("trending_bull")] * 15 + [_row("neutral")] * 5
    segmented, dominant = _segment_rows_by_regime(rows, min_rows=10)
    assert dominant == "trending_bull"
    assert len(segmented) == 15
    assert all(_extract_regime_from_row(r) == "trending_bull" for r in segmented)


def test_segment_rows_falls_back_when_segment_too_small():
    rows = [_row("trending_bull")] * 8 + [_row("neutral")] * 12
    segmented, dominant = _segment_rows_by_regime(rows, min_rows=20)
    assert dominant == "neutral"
    assert len(segmented) == 20
