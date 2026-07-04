"""Unit tests for decision event emitter."""

from __future__ import annotations

from agent.core.config import settings
from agent.persistence.decision_events import DecisionEventEmitter, extract_denorm_from_metadata


def test_emit_if_changed_dedupes(monkeypatch):
    monkeypatch.setattr(settings, "trade_decision_events_enabled", True)
    emitter = DecisionEventEmitter()
    e1 = emitter.emit_if_changed(
        position_id="pos_1",
        symbol="BTCUSD",
        event_type="tle_verdict",
        payload={"action": "HOLD"},
    )
    e2 = emitter.emit_if_changed(
        position_id="pos_1",
        symbol="BTCUSD",
        event_type="tle_verdict",
        payload={"action": "HOLD"},
    )
    assert e1 is not None
    assert e2 is None
    emitter.reset_position("pos_1")


def test_extract_denorm_from_metadata():
    meta = {
        "system_context": {"config_hash": "abc12345"},
        "decision_context": {
            "entry_quality": {"quality_score": 0.82},
            "rule_based_pipeline": {
                "structural_gates": {"setup_type": "breakout"},
                "market_state": {"regime": "trending_bull"},
            },
        },
        "post_trade_assessment": {"root_cause": "poor_entry"},
        "execution_timing": {"execution_slippage_bps_entry": 3.2},
        "outcome": {"excursions": {"mfe_pct": 1.5, "mae_pct": 0.8}},
        "decision_event_count": 12,
    }
    denorm = extract_denorm_from_metadata(meta)
    assert denorm["config_hash"] == "abc12345"
    assert denorm["setup_type"] == "breakout"
    assert denorm["entry_quality_score"] == 0.82
    assert denorm["mfe_pct"] == 1.5
