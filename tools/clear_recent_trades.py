#!/usr/bin/env python3
"""Clear Recent Trades: wipe local DB rows and suppress Delta order-history in the UI.

Usage (from repo root):
    python tools/clear_recent_trades.py

Requires Postgres. Redis is optional but recommended (suppression flag + cache bust).
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
    from backend.services.portfolio_fetch import set_recent_trades_suppressed

    redis_ok = await clear_recent_trades_display()
    set_recent_trades_suppressed(False)
    print("Cleared trades/positions in Postgres and agent trade ledger.")
    if redis_ok:
        print("Also cleared portfolio Redis caches.")
    else:
        print("Redis was unavailable; agent ledger file flag still applied.")
    print("Hard-refresh the dashboard — Agent trades will repopulate as Jack Sparrow closes positions.")


if __name__ == "__main__":
    asyncio.run(main())
