#!/usr/bin/env python3
"""Probe Delta GET /v2/wallet/transactions with multiple parameter sets."""

from __future__ import annotations

import asyncio
import json
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


def _us(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000)


async def _probe(label: str, client, **kwargs) -> None:
    print(f"\n=== {label} ===")
    print(f"params: {kwargs}")
    try:
        resp = await client.get_wallet_transactions(**kwargs)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return
    if not isinstance(resp, dict):
        print(f"unexpected response type: {type(resp)}")
        return
    print(f"success={resp.get('success')} error={resp.get('error')}")
    rows = resp.get("result")
    if not isinstance(rows, list):
        print(f"result type={type(rows)!r} keys={list(resp.keys())}")
        return
    print(f"row_count={len(rows)}")
    meta = resp.get("meta")
    if meta:
        print(f"meta={meta}")
    for row in rows[:5]:
        print(
            json.dumps(
                {
                    "id": row.get("id"),
                    "transaction_type": row.get("transaction_type"),
                    "amount": row.get("amount"),
                    "asset_symbol": row.get("asset_symbol"),
                    "product_id": row.get("product_id"),
                    "created_at": row.get("created_at"),
                    "meta_data": row.get("meta_data"),
                },
                default=str,
            )
        )


async def main() -> int:
    from agent.data.delta_client import DeltaExchangeClient

    client = DeltaExchangeClient()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    await _probe("no filters", client, page_size=20)
    await _probe(
        "commission,funding 7d lookback",
        client,
        transaction_types="commission,funding",
        start_time=_us(week_ago),
        page_size=100,
    )
    await _probe(
        "commission only 30d",
        client,
        transaction_types="commission",
        start_time=_us(month_ago),
        page_size=100,
    )
    await _probe(
        "all types 30d (no transaction_types filter)",
        client,
        start_time=_us(month_ago),
        page_size=100,
    )
    await _probe(
        "trading_credits,commission_rebate 30d",
        client,
        transaction_types="trading_credits,commission_rebate,trading_credits_paid",
        start_time=_us(month_ago),
        page_size=100,
    )

    print("\n=== fills comparison (7d) ===")
    try:
        fills = await client.get_fills(
            start_time=_us(week_ago),
            page_size=10,
            contract_types="perpetual_futures",
        )
        frows = fills.get("result") if isinstance(fills, dict) else None
        print(f"fills success={fills.get('success')} count={len(frows) if isinstance(frows, list) else 'n/a'}")
        if isinstance(frows, list):
            for f in frows[:3]:
                print(
                    json.dumps(
                        {
                            "id": f.get("id"),
                            "commission": f.get("commission"),
                            "created_at": f.get("created_at"),
                            "product_id": f.get("product_id"),
                        },
                        default=str,
                    )
                )
    except Exception as exc:
        print(f"fills ERROR: {exc}")

    print("\n=== wallet balances ===")
    try:
        bal = await client.get_wallet_balances()
        brows = bal.get("result") if isinstance(bal, dict) else None
        if isinstance(brows, list):
            for b in brows[:5]:
                print(
                    f"  {b.get('asset_symbol')}: balance={b.get('balance')} "
                    f"available={b.get('available_balance')}"
                )
    except Exception as exc:
        print(f"balances ERROR: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
