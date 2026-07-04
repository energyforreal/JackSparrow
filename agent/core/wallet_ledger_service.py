"""Incremental sync of Delta wallet transactions into PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.persistence.db_writes import (
    load_wallet_sync_state_async,
    persist_wallet_transactions_batch_async,
    update_wallet_sync_state_async,
)
from agent.persistence.wallet_transactions import (
    DEFAULT_EXCHANGE,
    DeltaWalletTransactionNormalizer,
    WalletTransactionRecord,
)

logger = structlog.get_logger()

DEFAULT_SCOPE_KEY = "default"
_MAX_PAGES_PER_SYNC = 50


class WalletLedgerService:
    """Orchestrates Delta wallet transaction sync with checkpointing."""

    def __init__(self, delta_client: Any) -> None:
        self._delta_client = delta_client
        self._debounce_task: Optional[asyncio.Task] = None
        self._debounce_reason: Optional[str] = None
        self._sync_lock = asyncio.Lock()

    def _database_url(self) -> str:
        return str(getattr(settings, "database_url", "") or "")

    def _default_transaction_types(self) -> str:
        return str(
            getattr(settings, "wallet_ledger_default_transaction_types", "commission,funding")
            or "commission,funding"
        )

    def _debounce_seconds(self) -> float:
        return float(getattr(settings, "wallet_ledger_fill_sync_debounce_seconds", 30) or 30)

    def _is_enabled(self) -> bool:
        return bool(getattr(settings, "wallet_ledger_sync_enabled", False))

    def schedule_debounced_sync(self, reason: str = "fill") -> None:
        """Coalesce rapid fill events into one sync (non-blocking)."""
        if not self._is_enabled():
            return
        self._debounce_reason = reason
        if self._debounce_task is not None and not self._debounce_task.done():
            return

        async def _run_debounced() -> None:
            try:
                await asyncio.sleep(self._debounce_seconds())
                await self.sync_incremental(
                    transaction_types=self._default_transaction_types(),
                    lookback_seconds=int(self._debounce_seconds()) + 120,
                    reason=self._debounce_reason or reason,
                )
            except Exception as exc:
                logger.warning(
                    "wallet_ledger_debounced_sync_failed",
                    reason=reason,
                    error=str(exc),
                )
            finally:
                self._debounce_task = None

        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(_run_debounced())
        except RuntimeError:
            pass

    async def sync_incremental(
        self,
        *,
        transaction_types: Optional[str] = None,
        lookback_seconds: int = 300,
        reason: str = "incremental",
        scope_key: str = DEFAULT_SCOPE_KEY,
    ) -> Dict[str, Any]:
        """Fetch new wallet pages since checkpoint (with optional lookback)."""
        if not self._is_enabled():
            return {"success": True, "skipped": True, "reason": "disabled"}
        if not self._delta_client:
            return {"success": False, "error": "no_delta_client"}
        db_url = self._database_url()
        if not db_url:
            return {"success": False, "error": "no_database_url"}

        types_str = transaction_types or self._default_transaction_types()

        async with self._sync_lock:
            try:
                state = await load_wallet_sync_state_async(
                    db_url, exchange=DEFAULT_EXCHANGE, scope_key=scope_key
                )
                start_time_us: Optional[int] = None
                after_cursor: Optional[str] = None
                if state and state.get("last_cursor"):
                    after_cursor = str(state["last_cursor"])
                elif lookback_seconds > 0:
                    since = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
                    start_time_us = int(since.timestamp() * 1_000_000)

                total_rows = 0
                last_cursor: Optional[str] = None
                last_tx_id: Optional[int] = None
                last_occurred: Optional[datetime] = None

                for _page in range(_MAX_PAGES_PER_SYNC):
                    resp = await self._delta_client.get_wallet_transactions(
                        transaction_types=types_str,
                        start_time=start_time_us if after_cursor is None else None,
                        page_size=100,
                        after=after_cursor,
                    )
                    if not isinstance(resp, dict):
                        break
                    if resp.get("success") is False:
                        err = str(resp.get("error") or "delta_wallet_sync_failed")
                        await update_wallet_sync_state_async(
                            db_url,
                            exchange=DEFAULT_EXCHANGE,
                            scope_key=scope_key,
                            last_error=err,
                        )
                        return {"success": False, "error": err}

                    raw_rows = resp.get("result")
                    if not isinstance(raw_rows, list):
                        raw_rows = []
                    records = DeltaWalletTransactionNormalizer.from_delta_rows(raw_rows)
                    if records:
                        db_rows = [r.to_db_dict() for r in records]
                        await persist_wallet_transactions_batch_async(db_url, db_rows)
                        total_rows += len(records)
                        for rec in records:
                            if last_occurred is None or rec.occurred_at > last_occurred:
                                last_occurred = rec.occurred_at
                                last_tx_id = rec.exchange_transaction_id

                    meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                    next_after = meta.get("after")
                    if next_after:
                        last_cursor = str(next_after)
                        after_cursor = last_cursor
                        start_time_us = None
                        continue
                    break

                await update_wallet_sync_state_async(
                    db_url,
                    exchange=DEFAULT_EXCHANGE,
                    scope_key=scope_key,
                    last_cursor=last_cursor,
                    last_transaction_id=last_tx_id,
                    last_occurred_at=last_occurred,
                    last_error=None,
                )
                logger.info(
                    "wallet_ledger_sync_completed",
                    reason=reason,
                    rows=total_rows,
                    last_transaction_id=last_tx_id,
                )
                return {
                    "success": True,
                    "rows_synced": total_rows,
                    "last_transaction_id": last_tx_id,
                }
            except Exception as exc:
                err = str(exc)
                logger.warning(
                    "wallet_ledger_sync_failed",
                    reason=reason,
                    error=err,
                    exc_info=True,
                )
                await update_wallet_sync_state_async(
                    db_url,
                    exchange=DEFAULT_EXCHANGE,
                    scope_key=scope_key,
                    last_error=err,
                )
                return {"success": False, "error": err}

    async def sync_since(
        self,
        timestamp_us: int,
        *,
        transaction_types: Optional[str] = None,
        scope_key: str = DEFAULT_SCOPE_KEY,
    ) -> Dict[str, Any]:
        """Bounded backfill from a microsecond epoch timestamp."""
        if not self._is_enabled() or not self._delta_client:
            return {"success": True, "skipped": True}
        db_url = self._database_url()
        if not db_url:
            return {"success": False, "error": "no_database_url"}

        types_str = transaction_types or self._default_transaction_types()
        total_rows = 0
        after_cursor: Optional[str] = None

        async with self._sync_lock:
            try:
                for _page in range(_MAX_PAGES_PER_SYNC):
                    resp = await self._delta_client.get_wallet_transactions(
                        transaction_types=types_str,
                        start_time=int(timestamp_us) if after_cursor is None else None,
                        page_size=100,
                        after=after_cursor,
                    )
                    if not isinstance(resp, dict) or resp.get("success") is False:
                        break
                    raw_rows = resp.get("result") if isinstance(resp.get("result"), list) else []
                    records = DeltaWalletTransactionNormalizer.from_delta_rows(raw_rows)
                    if records:
                        await persist_wallet_transactions_batch_async(
                            db_url, [r.to_db_dict() for r in records]
                        )
                        total_rows += len(records)
                    meta = resp.get("meta") if isinstance(resp.get("meta"), dict) else {}
                    next_after = meta.get("after")
                    if next_after:
                        after_cursor = str(next_after)
                        continue
                    break
                return {"success": True, "rows_synced": total_rows}
            except Exception as exc:
                return {"success": False, "error": str(exc)}


_wallet_ledger_service: Optional[WalletLedgerService] = None


def get_wallet_ledger_service(delta_client: Any = None) -> WalletLedgerService:
    """Return singleton wallet ledger service."""
    global _wallet_ledger_service
    if _wallet_ledger_service is None:
        if delta_client is None:
            from agent.data.delta_client import DeltaExchangeClient

            delta_client = DeltaExchangeClient()
        _wallet_ledger_service = WalletLedgerService(delta_client)
    return _wallet_ledger_service


def reset_wallet_ledger_service_for_tests() -> None:
    """Clear singleton (tests)."""
    global _wallet_ledger_service
    _wallet_ledger_service = None
