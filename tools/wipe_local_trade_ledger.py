#!/usr/bin/env python3
"""One-time wipe of local Postgres trades/positions and portfolio Redis caches.

Testnet portfolio data is sourced from Delta exchange; paper-era DB rows can
pollute WebSocket recent-trades until removed.

Usage (from repo root):
    python tools/wipe_local_trade_ledger.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.services.portfolio_fetch import clear_recent_trades_display  # noqa: E402


async def main() -> None:
    redis_ok = await clear_recent_trades_display()
    print("Wiped trades and positions tables.")
    if redis_ok:
        print("Cleared portfolio Redis caches and suppressed recent-trades display.")
    else:
        print("Redis unavailable — cache/suppression skipped. Use tools/clear_recent_trades.py after starting Redis.")


if __name__ == "__main__":
    asyncio.run(main())
