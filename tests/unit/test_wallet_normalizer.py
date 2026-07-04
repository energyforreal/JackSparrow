"""Tests for Delta wallet transaction normalizer."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agent.persistence.wallet_transactions import (
    DeltaWalletTransactionNormalizer,
    WalletTransactionRecord,
)


def test_from_delta_row_commission_with_order_id():
    row = {
        "id": 100234,
        "amount": "-0.00025000",
        "balance": "1.23456789",
        "transaction_type": "commission",
        "meta_data": {"order_id": 987654},
        "product_id": 27,
        "asset_id": 5,
        "asset_symbol": "BTC",
        "created_at": "2026-07-04T10:30:00.000Z",
    }
    rec = DeltaWalletTransactionNormalizer.from_delta_row(row)
    assert rec is not None
    assert rec.exchange_transaction_id == 100234
    assert rec.transaction_type == "commission"
    assert rec.order_id == 987654
    assert rec.product_id == 27
    assert rec.amount == Decimal("-0.00025000")
    assert rec.balance_after == Decimal("1.23456789")
    assert rec.occurred_at.tzinfo is not None


def test_from_delta_row_funding_without_order_id():
    row = {
        "id": 100235,
        "amount": "0.00012500",
        "balance": "1.23469289",
        "transaction_type": "funding",
        "meta_data": {},
        "product_id": 27,
        "asset_symbol": "BTC",
        "created_at": "2026-07-04T11:00:00.000Z",
    }
    rec = DeltaWalletTransactionNormalizer.from_delta_row(row)
    assert rec is not None
    assert rec.transaction_type == "funding"
    assert rec.order_id is None


def test_from_delta_row_invalid_returns_none():
    assert DeltaWalletTransactionNormalizer.from_delta_row({}) is None
    assert DeltaWalletTransactionNormalizer.from_delta_row({"id": 1}) is None


def test_to_db_dict_roundtrip():
    rec = WalletTransactionRecord(
        exchange="delta",
        exchange_transaction_id=1,
        transaction_type="commission",
        asset_symbol="BTC",
        amount=Decimal("-0.1"),
        occurred_at=datetime(2026, 7, 4, 10, 30, tzinfo=timezone.utc),
        order_id=99,
    )
    d = rec.to_db_dict()
    assert d["exchange"] == "delta"
    assert d["exchange_transaction_id"] == 1
    assert d["order_id"] == 99
