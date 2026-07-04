"""Unit tests for trade decision snapshot builders."""

from __future__ import annotations

from agent.persistence.performance_context import reset_for_tests
from agent.persistence.trade_snapshot import (
    build_entry_snapshot,
    build_reject_snapshot,
    build_system_context,
    enforce_snapshot_size_cap,
    extract_ledger_summary,
    merge_close_fields,
    reconstruct_market_context_from_snapshot,
)


def test_build_system_context_config_hash_stable():
    a = build_system_context()
    b = build_system_context()
    assert a["config_hash"] == b["config_hash"]
    assert len(a["config_hash"]) == 8
    assert a["gate_profile"] in ("permissive", "strict")


def test_build_entry_snapshot_v2_fields():
    risk_payload = {
        "symbol": "BTCUSD",
        "side": "long",
        "confidence": 0.72,
        "policy_verdict": {
            "signal": "LONG",
            "conviction": 0.81,
            "reason_codes": ["agent_thesis_entry"],
            "abstention": None,
        },
        "market_context": {
            "entry_quality": {
                "quality_score": 0.75,
                "passed": True,
                "dimensions": {"structural": 0.8},
                "reason_codes": [],
                "required_ml_confirmation": False,
            },
            "hypothesis_snapshot": {
                "long_pressure": 0.62,
                "short_pressure": 0.31,
                "aggregate_direction": "LONG",
            },
            "thesis_verdict": {"signal": "LONG", "confidence": 0.7},
            "rule_based_pipeline": {"structural_gates": {"setup_type": "breakout"}},
        },
    }
    snap = build_entry_snapshot(
        risk_payload=risk_payload,
        timing_ctx={
            "execution_slippage_bps_entry": 2.5,
            "reference_price_entry": 90000.0,
            "fill_price_entry": 90018.0,
        },
    )
    dc = snap["decision_context"]
    assert dc["entry_quality"]["quality_score"] == 0.75
    assert dc["hypothesis_snapshot"]["long_pressure"] == 0.62
    assert dc["policy_verdict"]["signal"] == "LONG"
    assert dc["thesis_verdict"]["signal"] == "LONG"
    assert snap["execution_timing"]["execution_slippage_bps_entry"] == 2.5


def test_merge_close_fields_includes_slippage_and_tp_history():
    entry = build_entry_snapshot(
        risk_payload={
            "symbol": "BTCUSD",
            "side": "long",
            "market_context": {"rule_based_pipeline": {"structural_gates": {"setup_type": "none"}}},
        },
    )
    merged = merge_close_fields(
        entry,
        {
            "position_id": "pos_1",
            "exit_price": 91000.0,
            "entry_price": 90000.0,
            "pnl": 10.0,
            "exit_reason": "take_profit",
            "timestamp": "2026-06-29T11:00:00+00:00",
            "reference_price_exit": 90950.0,
            "fill_price_exit": 91000.0,
            "execution_slippage_bps_exit": 5.5,
            "tp_sl_history": [
                {"change_type": "take_profit", "before": 95000.0, "after": 94000.0}
            ],
        },
    )
    assert merged["outcome"]["fill_price_exit"] == 91000.0
    assert merged["execution_timing"]["execution_slippage_bps_exit"] == 5.5
    assert len(merged["outcome"]["tp_sl_history"]) == 1


def test_build_entry_snapshot_includes_rule_based_pipeline():
    risk_payload = {
        "symbol": "BTCUSD",
        "side": "long",
        "confidence": 0.72,
        "stop_loss": 90000.0,
        "take_profit": 95000.0,
        "market_context": {
            "features": {"atr_14": 1200.5, "rsi_14": 55.0},
            "rule_based_pipeline": {
                "market_state": {"regime": "trending_bull", "trend": "bullish"},
                "structural_gates": {
                    "trade_allowed": True,
                    "categories": {"trend": True, "liquidity": True},
                    "block_reasons": [],
                    "setup_type": "breakout",
                },
                "fsm_decision": {"fsm_state": "EntryReady", "entry_signal": "LONG"},
                "structural_confidence": 0.61,
                "narrative_tail": [{"event_type": "breakout_confirmed"}],
            },
        },
    }
    snap = build_entry_snapshot(risk_payload=risk_payload)
    assert snap["snapshot_version"] == 1
    assert snap["decision_context"]["gate_evaluation"]["setup_type"] == "breakout"
    assert snap["decision_context"]["features"].get("atr_14") == 1200.5
    summary = extract_ledger_summary(snap)
    assert summary["regime"] == "trending_bull"
    assert summary["setup_type"] == "breakout"


def test_merge_close_fields_adds_outcome_and_timing():
    entry = build_entry_snapshot(
        risk_payload={
            "symbol": "BTCUSD",
            "side": "long",
            "market_context": {"rule_based_pipeline": {"structural_gates": {"setup_type": "none"}}},
        },
        timing_ctx={
            "risk_approved_at": "2026-06-29T10:00:00+00:00",
            "exchange_filled_at": "2026-06-29T10:00:01+00:00",
        },
    )
    merged = merge_close_fields(
        entry,
        {
            "position_id": "pos_abc",
            "exit_price": 91000.0,
            "entry_price": 90000.0,
            "pnl": 10.0,
            "exit_reason": "take_profit",
            "timestamp": "2026-06-29T11:00:00+00:00",
        },
    )
    assert merged["snapshot_kind"] == "closed_round_trip"
    assert merged["outcome"]["exit_reason"] == "take_profit"
    assert merged["execution_timing"].get("risk_to_fill_ms") == 1000.0


def test_reconstruct_market_context_from_snapshot():
    entry = build_entry_snapshot(
        risk_payload={
            "symbol": "BTCUSD",
            "side": "long",
            "market_context": {
                "rule_based_pipeline": {
                    "market_state": {"regime": "neutral"},
                    "structural_gates": {"setup_type": "trend_continuation"},
                }
            },
        }
    )
    mc = reconstruct_market_context_from_snapshot(entry)
    assert "rule_based_pipeline" in mc
    assert mc["rule_based_pipeline"]["market_state"]["regime"] == "neutral"


def test_build_reject_snapshot():
    snap = build_reject_snapshot(
        symbol="BTCUSD",
        signal="LONG",
        event_id="evt-1",
        reject_reason="hold_at_synthesis",
        diagnostics={"raw_confidence": 0.4},
    )
    assert snap["snapshot_kind"] == "reject"
    assert snap["decision_context"]["reject_reason"] == "hold_at_synthesis"


def test_enforce_snapshot_size_cap_truncates():
    huge = {
        "snapshot_version": 1,
        "decision_context": {
            "features": {f"f{i}": float(i) for i in range(5000)},
            "narrative_tail": [{"x": "y"}] * 500,
        },
    }
    capped = enforce_snapshot_size_cap(huge)
    assert capped.get("_truncated") is True or len(str(capped)) < len(str(huge))


def test_performance_context_streaks():
    from agent.persistence.performance_context import (
        record_position_closed,
        snapshot_performance_context,
    )

    reset_for_tests()
    record_position_closed(pnl_usd=5.0)
    record_position_closed(pnl_usd=3.0)
    record_position_closed(pnl_usd=-2.0)
    ctx = snapshot_performance_context()
    assert ctx["closed_trades_count"] == 3
    assert ctx["win_streak"] == 0
    assert ctx["loss_streak"] == 1
    reset_for_tests()
