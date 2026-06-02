"""Unit tests for dynamic confidence helpers."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.confidence_dynamics import (
    adjudication_confidence,
    aggregate_entry_proba_strength,
    margin_enhanced_confidence,
    proportional_v43_entry_floor,
    synthetic_entry_proba_from_ic,
)


def test_margin_enhanced_confidence_blends_with_entry_proba():
    preds = [
        {
            "model_name": "m1",
            "confidence": 0.5,
            "context": {"entry_proba": {"buy": 0.1, "sell": 0.75, "hold": 0.15}},
        },
    ]
    out = margin_enhanced_confidence(preds, fallback_avg=0.5, margin_weight=0.5)
    assert out > 0.5
    assert out <= 1.0


def test_aggregate_entry_proba_strength_empty():
    assert aggregate_entry_proba_strength([])["signal_strength"] is None


def test_proportional_v43_floor_not_flat_plateau():
    low_margin = proportional_v43_entry_floor(0.55, 0.60, 0.10, ai_floor=0.7)
    high_margin = proportional_v43_entry_floor(0.55, 0.60, 0.30, ai_floor=0.7)
    assert high_margin > low_margin
    assert high_margin < 0.7 * 0.99


def test_adjudication_confidence_scales_with_score():
    low = adjudication_confidence(40.0, verdict="agree")
    high = adjudication_confidence(90.0, verdict="agree")
    assert high > low
    assert 0.52 <= low <= 0.95


def test_synthetic_entry_proba_from_ic_sums_to_one():
    proba = synthetic_entry_proba_from_ic("SELL", edge=-0.01, threshold=0.005, unc_scale=0.9)
    assert abs(sum(proba.values()) - 1.0) < 1e-6
    assert proba["sell"] >= proba["buy"]


@pytest.mark.asyncio
async def test_step6_continuous_confidence_range():
    """Adjudication confidences span a wider band than legacy fixed buckets."""
    agree_100 = adjudication_confidence(100.0, verdict="agree")
    flat_0 = adjudication_confidence(0.0, verdict="flat")
    assert agree_100 - flat_0 > 0.35
