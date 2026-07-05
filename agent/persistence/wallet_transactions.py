"""Canonical wallet transaction model and Delta Exchange normalizer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from agent.data.delta_client import DeltaExchangeClient

DEFAULT_EXCHANGE = "delta"


@dataclass
class WalletTransactionRecord:
    """Exchange-agnostic wallet ledger row."""

    exchange: str
    exchange_transaction_id: int
    transaction_type: str
    asset_symbol: str
    amount: Decimal
    occurred_at: datetime
    product_id: Optional[int] = None
    order_id: Optional[int] = None
    balance_after: Optional[Decimal] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_db_dict(self) -> Dict[str, Any]:
        """Map to parameters for wallet_transactions INSERT."""
        return {
            "exchange": self.exchange,
            "exchange_transaction_id": int(self.exchange_transaction_id),
            "transaction_type": self.transaction_type,
            "asset_symbol": self.asset_symbol,
            "product_id": self.product_id,
            "order_id": self.order_id,
            "amount": self.amount,
            "balance_after": self.balance_after,
            "occurred_at": self.occurred_at,
            "metadata": self.raw_payload,
        }


def _parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None


def _extract_order_id(meta: Any) -> Optional[int]:
    if not isinstance(meta, dict):
        return None
    raw = meta.get("order_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _synthetic_exchange_transaction_id(row: Dict[str, Any]) -> int:
    """Stable bigint id when Delta omits ``id`` (common on India testnet).

    Prefer ``meta_data.fill_uuid`` so commission rows dedupe with fills API ids.
    """
    meta = row.get("meta_data")
    if meta is None:
        meta = row.get("metadata")
    fill_uuid = None
    if isinstance(meta, dict):
        fill_uuid = meta.get("fill_uuid") or meta.get("fill_id")
    if fill_uuid:
        digest = hashlib.sha256(str(fill_uuid).encode("utf-8")).hexdigest()
        return int(digest[:15], 16)

    key = "|".join(
        str(part)
        for part in (
            row.get("transaction_type"),
            row.get("created_at"),
            row.get("amount"),
            row.get("product_id"),
            row.get("asset_symbol"),
        )
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _resolve_exchange_transaction_id(row: Dict[str, Any]) -> tuple[int, bool]:
    """Return (exchange_transaction_id, synthetic)."""
    tx_id = row.get("id")
    if tx_id is not None:
        try:
            return int(tx_id), False
        except (TypeError, ValueError):
            pass
    return _synthetic_exchange_transaction_id(row), True


class DeltaWalletTransactionNormalizer:
    """Convert Delta GET /v2/wallet/transactions rows to canonical records."""

    @staticmethod
    def from_delta_row(
        row: Dict[str, Any],
        *,
        exchange: str = DEFAULT_EXCHANGE,
    ) -> Optional[WalletTransactionRecord]:
        if not isinstance(row, dict):
            return None
        exchange_transaction_id, synthetic_id = _resolve_exchange_transaction_id(row)

        transaction_type = str(row.get("transaction_type") or "").strip().lower()
        if not transaction_type:
            return None

        asset_symbol = str(row.get("asset_symbol") or "").strip().upper() or "UNKNOWN"
        amount = _parse_decimal(row.get("amount"))
        if amount is None:
            return None

        occurred_at = DeltaExchangeClient.parse_fill_timestamp(row.get("created_at"))
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        product_id: Optional[int] = None
        raw_pid = row.get("product_id")
        if raw_pid is not None:
            try:
                product_id = int(raw_pid)
            except (TypeError, ValueError):
                product_id = None

        meta = row.get("meta_data")
        if meta is None:
            meta = row.get("metadata")
        order_id = _extract_order_id(meta)
        raw_payload = dict(row)
        if synthetic_id:
            raw_payload["_synthetic_exchange_transaction_id"] = True

        return WalletTransactionRecord(
            exchange=exchange,
            exchange_transaction_id=exchange_transaction_id,
            transaction_type=transaction_type,
            asset_symbol=asset_symbol,
            product_id=product_id,
            order_id=order_id,
            amount=amount,
            balance_after=_parse_decimal(row.get("balance")),
            occurred_at=occurred_at,
            raw_payload=raw_payload,
        )

    @classmethod
    def from_delta_rows(
        cls,
        rows: List[Dict[str, Any]],
        *,
        exchange: str = DEFAULT_EXCHANGE,
    ) -> List[WalletTransactionRecord]:
        out: List[WalletTransactionRecord] = []
        for row in rows:
            rec = cls.from_delta_row(row, exchange=exchange)
            if rec is not None:
                out.append(rec)
        return out
