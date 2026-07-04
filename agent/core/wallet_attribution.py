"""Map wallet ledger rows to closed positions for analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set


@dataclass
class WalletAttributionResult:
    """Attributed wallet costs for one closed position."""

    commission_usd: Decimal = Decimal("0")
    funding_usd: Decimal = Decimal("0")
    rebates_usd: Decimal = Decimal("0")
    net_wallet_impact_usd: Decimal = Decimal("0")
    attribution_confidence: str = "unattributed"
    linked_transaction_ids: List[int] = field(default_factory=list)
    unattributed_transaction_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commission_usd": float(self.commission_usd),
            "funding_usd": float(self.funding_usd),
            "rebates_usd": float(self.rebates_usd),
            "net_wallet_impact_usd": float(self.net_wallet_impact_usd),
            "attribution_confidence": self.attribution_confidence,
            "linked_transaction_ids": list(self.linked_transaction_ids),
            "unattributed_transaction_ids": list(self.unattributed_transaction_ids),
        }


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


class WalletAttributionEngine:
    """Deterministic wallet event → trade attribution."""

    COMMISSION_FALLBACK_SECONDS = 120

    def attribute_for_position(
        self,
        close_payload: Dict[str, Any],
        wallet_rows: List[Dict[str, Any]],
        *,
        known_order_ids: Optional[Set[int]] = None,
        product_id: Optional[int] = None,
    ) -> WalletAttributionResult:
        """Attribute wallet rows to one closed position."""
        result = WalletAttributionResult()
        if not wallet_rows:
            return result

        opened_at = _parse_dt(close_payload.get("entry_time")) or _parse_dt(
            close_payload.get("opened_at")
        )
        closed_at = _parse_dt(close_payload.get("timestamp")) or _parse_dt(
            close_payload.get("closed_at")
        )
        if closed_at is None:
            closed_at = datetime.now(timezone.utc)

        order_ids = known_order_ids or set()
        ex_oid = close_payload.get("exchange_order_id")
        if ex_oid is not None:
            try:
                order_ids.add(int(ex_oid))
            except (TypeError, ValueError):
                pass

        high_links = 0
        medium_links = 0

        for row in wallet_rows:
            if not isinstance(row, dict):
                continue
            tx_id = row.get("exchange_transaction_id")
            try:
                tx_id_int = int(tx_id) if tx_id is not None else None
            except (TypeError, ValueError):
                tx_id_int = None

            tx_type = str(row.get("transaction_type") or "").lower()
            amount = _to_decimal(row.get("amount"))
            occurred = _parse_dt(row.get("occurred_at"))
            if occurred is None:
                continue

            row_pid = row.get("product_id")
            if product_id is not None and row_pid is not None:
                try:
                    if int(row_pid) != int(product_id):
                        continue
                except (TypeError, ValueError):
                    pass

            if tx_type in ("deposit", "withdrawal", "trading_credits"):
                if tx_id_int is not None:
                    result.unattributed_transaction_ids.append(tx_id_int)
                continue

            if tx_type == "commission":
                order_id = row.get("order_id")
                linked = False
                if order_id is not None:
                    try:
                        oid = int(order_id)
                        if oid in order_ids:
                            result.commission_usd += amount
                            linked = True
                            high_links += 1
                    except (TypeError, ValueError):
                        pass
                if not linked and opened_at and product_id is not None:
                    window = timedelta(seconds=self.COMMISSION_FALLBACK_SECONDS)
                    if opened_at - window <= occurred <= closed_at + window:
                        result.commission_usd += amount
                        linked = True
                        medium_links += 1
                if linked and tx_id_int is not None:
                    result.linked_transaction_ids.append(tx_id_int)
                elif tx_id_int is not None:
                    result.unattributed_transaction_ids.append(tx_id_int)
                continue

            if tx_type == "commission_rebate":
                result.rebates_usd += amount
                if tx_id_int is not None:
                    result.linked_transaction_ids.append(tx_id_int)
                high_links += 1
                continue

            if tx_type == "funding":
                if opened_at and occurred > opened_at and occurred <= closed_at:
                    result.funding_usd += amount
                    if tx_id_int is not None:
                        result.linked_transaction_ids.append(tx_id_int)
                    high_links += 1
                elif tx_id_int is not None:
                    result.unattributed_transaction_ids.append(tx_id_int)
                continue

            if tx_id_int is not None:
                result.unattributed_transaction_ids.append(tx_id_int)

        result.net_wallet_impact_usd = (
            result.commission_usd + result.funding_usd + result.rebates_usd
        )
        if high_links > 0 and medium_links == 0:
            result.attribution_confidence = "high"
        elif high_links > 0 or medium_links > 0:
            result.attribution_confidence = "medium"
        elif result.linked_transaction_ids:
            result.attribution_confidence = "low"
        else:
            result.attribution_confidence = "unattributed"
        return result

    def attribute_commission_by_order_id(
        self,
        order_id: int,
        wallet_rows: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return first commission row matching order_id."""
        for row in wallet_rows:
            if str(row.get("transaction_type") or "").lower() != "commission":
                continue
            try:
                if int(row.get("order_id")) == int(order_id):
                    return row
            except (TypeError, ValueError):
                continue
        return None
