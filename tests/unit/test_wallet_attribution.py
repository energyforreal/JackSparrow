"""Tests for wallet attribution engine."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agent.core.wallet_attribution import WalletAttributionEngine


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_commission_by_order_id_high_confidence():
    engine = WalletAttributionEngine()
    close = {
        "entry_time": "2026-07-04T10:00:00+00:00",
        "timestamp": "2026-07-04T12:00:00+00:00",
        "exchange_order_id": 987654,
    }
    rows = [
        {
            "exchange_transaction_id": 1,
            "transaction_type": "commission",
            "order_id": 987654,
            "amount": Decimal("-0.25"),
            "occurred_at": _dt("2026-07-04T10:05:00Z"),
            "product_id": 27,
        }
    ]
    result = engine.attribute_for_position(
        close, rows, known_order_ids={987654}, product_id=27
    )
    assert result.commission_usd == Decimal("-0.25")
    assert result.attribution_confidence == "high"
    assert 1 in result.linked_transaction_ids


def test_funding_within_position_window():
    engine = WalletAttributionEngine()
    close = {
        "entry_time": "2026-07-04T10:00:00+00:00",
        "timestamp": "2026-07-04T12:00:00+00:00",
    }
    rows = [
        {
            "exchange_transaction_id": 2,
            "transaction_type": "funding",
            "amount": Decimal("-1.12"),
            "occurred_at": _dt("2026-07-04T11:00:00Z"),
            "product_id": 27,
        }
    ]
    result = engine.attribute_for_position(close, rows, product_id=27)
    assert result.funding_usd == Decimal("-1.12")
    assert result.attribution_confidence == "high"


def test_funding_outside_window_unattributed():
    engine = WalletAttributionEngine()
    close = {
        "entry_time": "2026-07-04T10:00:00+00:00",
        "timestamp": "2026-07-04T12:00:00+00:00",
    }
    rows = [
        {
            "exchange_transaction_id": 3,
            "transaction_type": "funding",
            "amount": Decimal("-0.5"),
            "occurred_at": _dt("2026-07-04T09:00:00Z"),
            "product_id": 27,
        }
    ]
    result = engine.attribute_for_position(close, rows, product_id=27)
    assert result.funding_usd == Decimal("0")
    assert 3 in result.unattributed_transaction_ids


def test_deposit_never_attributed():
    engine = WalletAttributionEngine()
    close = {"entry_time": "2026-07-04T10:00:00+00:00", "timestamp": "2026-07-04T12:00:00+00:00"}
    rows = [
        {
            "exchange_transaction_id": 4,
            "transaction_type": "deposit",
            "amount": Decimal("100"),
            "occurred_at": _dt("2026-07-04T11:00:00Z"),
        }
    ]
    result = engine.attribute_for_position(close, rows)
    assert result.net_wallet_impact_usd == Decimal("0")
    assert 4 in result.unattributed_transaction_ids


def test_commission_by_fill_uuid_high_confidence():
    engine = WalletAttributionEngine()
    fill_uuid = "abc-123-fill"
    close = {
        "entry_time": "2026-07-04T10:00:00+00:00",
        "timestamp": "2026-07-04T12:00:00+00:00",
        "entry_fill_uuid": fill_uuid,
        "exit_fill_uuid": "other-fill",
    }
    rows = [
        {
            "exchange_transaction_id": 10,
            "transaction_type": "commission",
            "order_id": None,
            "amount": Decimal("-0.31"),
            "occurred_at": _dt("2026-07-04T10:01:00Z"),
            "product_id": 27,
            "metadata": {
                "meta_data": {"fill_uuid": fill_uuid},
            },
        },
        {
            "exchange_transaction_id": 11,
            "transaction_type": "commission",
            "order_id": None,
            "amount": Decimal("-0.31"),
            "occurred_at": _dt("2026-07-04T12:01:00Z"),
            "product_id": 27,
            "metadata": {
                "meta_data": {"fill_uuid": "other-fill"},
            },
        },
    ]
    result = engine.attribute_for_position(close, rows, product_id=27)
    assert result.commission_usd == Decimal("-0.62")
    assert result.attribution_confidence == "high"
    assert 10 in result.linked_transaction_ids
    assert 11 in result.linked_transaction_ids


def test_attribute_commission_by_fill_uuid_helper():
    engine = WalletAttributionEngine()
    fill_uuid = "fee-row-uuid"
    rows = [
        {
            "transaction_type": "commission",
            "metadata": {"meta_data": {"fill_uuid": fill_uuid}},
        }
    ]
    row = engine.attribute_commission_by_fill_uuid(fill_uuid, rows)
    assert row is not None
    assert row["transaction_type"] == "commission"
