#!/usr/bin/env python3
"""Quick check of recent trade snapshot fields for Phase A verification."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import psycopg2

    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, closed_at, opened_at, close_reason, pnl,
               metadata->'decision_context'->'entry' AS entry
        FROM trade_outcomes
        WHERE closed_at::date >= '2026-07-07'
        ORDER BY closed_at DESC
        LIMIT 5
        """
    )
    rows = cur.fetchall()
    out = [
        {
            "id": r[0],
            "closed_at": str(r[1]),
            "opened_at": str(r[2]) if r[2] else None,
            "close_reason": r[3],
            "pnl": float(r[4]) if r[4] is not None else None,
            "entry": r[5],
        }
        for r in rows
    ]
    report = {
        "recent_trades": out,
        "opened_at_populated": sum(1 for r in out if r["opened_at"]),
        "entry_metadata_populated": sum(1 for r in out if r["entry"]),
    }
    path = ROOT / "data" / "investigation" / "recovery_phase_a_verification.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
