#!/usr/bin/env python3
"""Close backend OPEN position rows when the exchange shows flat."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _connect():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        return None, None
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None, None
    conn = psycopg2.connect(_normalize_psycopg_url(url))
    return conn, RealDictCursor


def _fetch_open_positions(conn, cursor_factory) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute(
            """
            SELECT position_id, symbol, side::text AS side, quantity, entry_price,
                   opened_at, status::text AS status
            FROM positions
            WHERE status::text = 'OPEN'
            ORDER BY opened_at NULLS LAST
            """
        )
        return [dict(r) for r in cur.fetchall()]


async def _exchange_signed_size(symbol: str) -> Optional[float]:
    from agent.data.delta_client import DeltaExchangeClient

    client = DeltaExchangeClient()
    try:
        resp = await client.get_margined_positions(contract_types="perpetual_futures")
    except Exception:
        try:
            resp = await client.get_positions(symbol=symbol)
        except Exception:
            return None
    rows = resp.get("result") if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        return None
    sym_u = str(symbol or "").strip().upper()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_sym = str(
            row.get("product_symbol") or row.get("symbol") or row.get("sy") or ""
        ).upper()
        if row_sym and row_sym != sym_u:
            continue
        try:
            return float(row.get("size") or 0.0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _close_position_row(
    conn,
    *,
    position_id: str,
    apply: bool,
) -> bool:
    if not apply:
        return True
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE positions
            SET status = 'CLOSED',
                closed_at = %s,
                updated_at = %s
            WHERE position_id = %s AND status::text = 'OPEN'
            """,
            (datetime.now(timezone.utc), datetime.now(timezone.utc), position_id),
        )
        updated = cur.rowcount
    conn.commit()
    return updated > 0


async def _reconcile(*, apply: bool, symbol_filter: Optional[str]) -> Dict[str, Any]:
    conn, RealDictCursor = _connect()
    if conn is None or RealDictCursor is None:
        return {"error": "DATABASE_URL required (psycopg2)"}

    rows = _fetch_open_positions(conn, RealDictCursor)
    if symbol_filter:
        sym_f = symbol_filter.strip().upper()
        rows = [r for r in rows if str(r.get("symbol") or "").upper() == sym_f]

    report: Dict[str, Any] = {
        "scanned": len(rows),
        "exchange_flat": [],
        "exchange_open": [],
        "closed": [],
        "dry_run": not apply,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    for row in rows:
        sym = str(row.get("symbol") or "")
        pid = str(row.get("position_id") or "")
        signed = await _exchange_signed_size(sym)
        item = {
            "position_id": pid,
            "symbol": sym,
            "exchange_signed_size": signed,
            "opened_at": str(row.get("opened_at")),
        }
        if signed is None:
            report.setdefault("unknown", []).append(item)
            continue
        if abs(signed) <= 1e-9:
            report["exchange_flat"].append(item)
            if _close_position_row(conn, position_id=pid, apply=apply):
                report["closed"].append(pid)
        else:
            report["exchange_open"].append(item)

    conn.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply CLOSED status (default is dry-run)",
    )
    parser.add_argument("--symbol", default=None, help="Limit to one symbol")
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "investigation" / "reconcile_stale_positions.json"),
        help="Write JSON report path",
    )
    args = parser.parse_args()

    report = asyncio.run(_reconcile(apply=args.apply, symbol_filter=args.symbol))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    if report.get("error"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
