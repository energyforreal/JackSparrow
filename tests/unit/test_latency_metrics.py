"""Tests for risk-approved to fill latency metrics."""

from agent.core.latency_metrics import latency_snapshot, record_risk_to_fill_ms


def test_latency_snapshot_percentiles():
    for ms in (10.0, 20.0, 30.0, 40.0, 100.0):
        record_risk_to_fill_ms(ms)
    snap = latency_snapshot()
    block = snap["risk_approved_to_fill_ms"]
    assert block["count"] >= 5
    assert block["p50"] is not None
    assert block["max"] == 100.0
