"""Unit tests for entry_decisions fire-and-forget persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.persistence.db_writes import persist_entry_decision_async


@pytest.mark.asyncio
async def test_persist_entry_decision_async_invokes_sync_insert(monkeypatch):
    calls: list[dict] = []

    def _mock_insert(database_url: str, **kwargs):
        calls.append({"database_url": database_url, **kwargs})

    monkeypatch.setattr(
        "agent.persistence.db_writes._insert_entry_decision_sync",
        _mock_insert,
    )

    ts = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    await persist_entry_decision_async(
        "postgresql://user:pass@localhost/testdb",
        decision_id="dec-1",
        symbol="BTCUSD",
        outcome="rejected",
        reject_reason="hold_at_synthesis",
        signal="HOLD",
        side="long",
        confidence=0.42,
        reasoning_chain_id="chain-abc",
        config_hash="a1b2c3d4",
        metadata={"snapshot_kind": "reject"},
        timestamp=ts,
    )

    assert len(calls) == 1
    assert calls[0]["decision_id"] == "dec-1"
    assert calls[0]["outcome"] == "rejected"
    assert calls[0]["reject_reason"] == "hold_at_synthesis"
    assert calls[0]["config_hash"] == "a1b2c3d4"


@pytest.mark.asyncio
async def test_persist_analytics_rollups_async_upserts_all_buckets(monkeypatch):
    from agent.persistence.db_writes import persist_analytics_rollups_async

    upserts: list[dict] = []

    def _mock_upsert(database_url: str, **kwargs):
        upserts.append(kwargs)

    monkeypatch.setattr(
        "agent.persistence.db_writes._upsert_analytics_rollup_sync",
        _mock_upsert,
    )

    closed_at = datetime(2026, 6, 29, 15, 30, tzinfo=timezone.utc)
    await persist_analytics_rollups_async(
        "postgresql://user:pass@localhost/testdb",
        symbol="BTCUSD",
        pnl_usd=12.5,
        closed_at=closed_at,
        metadata={
            "system_context": {"config_hash": "cfg12345"},
            "decision_context": {
                "rule_based_pipeline": {
                    "market_state": {"regime": "trending_bull"},
                    "structural_gates": {"setup_type": "breakout"},
                }
            },
        },
    )

    period_types = {u["period_type"] for u in upserts}
    assert period_types == {"daily", "weekly", "regime", "setup_type", "config_hash"}
    assert all(u["symbol"] == "BTCUSD" for u in upserts)
    assert sum(1 for u in upserts if u["won"]) == 5
