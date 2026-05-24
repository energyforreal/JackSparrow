"""Unit tests for signal recovery KPI and promotion gates."""

from __future__ import annotations

from scripts.signal_recovery.kpi import (
    actionable_rate,
    compute_baseline_kpis,
    decision_entropy,
    hold_ratio,
)
from scripts.signal_recovery.phase5_promotion_gates import evaluate_promotion


def test_decision_entropy_not_zero_for_mixed_signals() -> None:
    signals = ["HOLD", "BUY", "SELL", "HOLD"]
    assert decision_entropy(signals) > 0.0
    assert hold_ratio(signals) == 0.5
    assert actionable_rate(signals) == 0.5


def test_compute_baseline_kpis_fields() -> None:
    rows = [
        {"signal": "HOLD", "confidence": 0.48, "expected_return": 0.001},
        {"signal": "BUY", "confidence": 0.72, "expected_return": 0.012},
    ]
    kpis = compute_baseline_kpis(rows)
    assert kpis["sample_count"] == 2
    assert "confidence_std" in kpis
    assert kpis["hold_ratio"] == 0.5


def test_promotion_gates_iterate_when_flat() -> None:
    base = {"kpis": {"hold_ratio": 0.9, "confidence_std": 0.01, "expected_return_std": 0.001, "actionable_rate": 0.05}}
    cand = {"kpis": {"hold_ratio": 0.9, "confidence_std": 0.01, "expected_return_std": 0.001, "actionable_rate": 0.05}}
    verdict = evaluate_promotion(base, cand, prediction_failed_count=0)
    assert verdict["decision"] == "iterate"
    assert verdict["promotable"] is False
