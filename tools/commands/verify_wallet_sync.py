#!/usr/bin/env python3
"""Verify wallet normalizer + sync against live Delta + DB."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (*here.parents, Path("/app"), Path.cwd()):
        if (candidate / "agent").is_dir():
            return candidate
    return Path("/app")


ROOT = _repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from agent.core.config import settings
    from agent.core.wallet_ledger_service import WalletLedgerService
    from agent.data.delta_client import DeltaExchangeClient
    from agent.persistence.db_writes import fetch_wallet_transactions_async
    from agent.persistence.wallet_transactions import DeltaWalletTransactionNormalizer

    client = DeltaExchangeClient()
    week = datetime.now(timezone.utc) - timedelta(days=7)
    start_us = int(week.timestamp() * 1_000_000)

    resp = await client.get_wallet_transactions(
        transaction_types="commission,funding",
        start_time=start_us,
        page_size=5,
    )
    rows = resp.get("result") or []
    recs = DeltaWalletTransactionNormalizer.from_delta_rows(rows)
    print(f"raw_rows={len(rows)} normalized={len(recs)}")
    if recs:
        sample = recs[0]
        print(
            "sample",
            sample.exchange_transaction_id,
            sample.transaction_type,
            sample.amount,
            sample.raw_payload.get("_synthetic_exchange_transaction_id"),
        )

    svc = WalletLedgerService(client)
    result = await svc.sync_since(start_us, transaction_types="commission,funding")
    print("sync_since", result)

    db_url = str(getattr(settings, "database_url", "") or "")
    if db_url:
        db_rows = await fetch_wallet_transactions_async(db_url, limit=5)
        print(f"db_wallet_transactions={len(db_rows)}")
        for row in db_rows[:3]:
            print(
                row.get("exchange_transaction_id"),
                row.get("transaction_type"),
                row.get("amount"),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
