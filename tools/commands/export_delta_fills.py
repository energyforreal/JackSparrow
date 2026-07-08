#!/usr/bin/env python3
"""Export Delta Exchange fills/wallet data for PnL reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _export(start: str, end: str, out: Path) -> dict:
    from agent.core.product_specs import get_contract_specs
    from agent.data.delta_client import DeltaExchangeClient

    client = DeltaExchangeClient()
    specs = await get_contract_specs("BTCUSD")
    start_dt = datetime.fromisoformat(f"{start}T00:00:00+00:00")
    end_dt = datetime.fromisoformat(f"{end}T23:59:59+00:00")
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    fills = await client.get_fills(
        product_ids=str(specs.product_id),
        start_time=start_ts,
        end_time=end_ts,
    )
    wallet = []
    try:
        wallet = await client.get_wallet_transactions(
            start_time=start_ts,
            end_time=end_ts,
        )
    except Exception as exc:  # noqa: BLE001
        wallet = {"error": str(exc)}

    report = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start, "end": end},
        "product_id": specs.product_id,
        "fill_count": len(fills.get("result") or []) if isinstance(fills, dict) else 0,
        "fills": fills,
        "wallet_transactions": wallet,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Delta fills for reconciliation")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out = (
        Path(args.out)
        if args.out
        else ROOT / "data" / "investigation" / f"delta_fills_{args.start}_{args.end}.json"
    )
    report = asyncio.run(_export(args.start, args.end, out))
    print(json.dumps({"out": str(out), "fill_count": report["fill_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
