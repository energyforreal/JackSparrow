#!/usr/bin/env python3
"""Audit entry thesis stability vs first post-entry lifecycle verdict."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_trades(start: str, end: str) -> List[Dict[str, Any]]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("Set DATABASE_URL", file=sys.stderr)
        return []
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT closed_at, symbol, side, pnl, metadata, opened_at
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _parse_verdicts_after(
    audit_path: Path, after_ts: datetime, symbol: str, window_min: int = 30
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not audit_path.is_file():
        return rows
    for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "`trade_lifecycle_verdict`" not in line or f"symbol={symbol}" not in line:
            continue
        utc_m = re.search(r"utc=`([^`]+)`", line)
        if not utc_m:
            continue
        try:
            ts = datetime.fromisoformat(utc_m.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < after_ts:
            continue
        if (ts - after_ts).total_seconds() > window_min * 60:
            break
        action_m = re.search(r"action=`([^`]+)`", line)
        health_m = re.search(r"health=([0-9.]+)", line)
        rows.append(
            {
                "utc": ts.isoformat(),
                "action": action_m.group(1) if action_m else "",
                "health": float(health_m.group(1)) if health_m else None,
            }
        )
    return rows


def _entry_fields(meta: Dict[str, Any]) -> Dict[str, Any]:
    summary = meta.get("entry_state_summary")
    if isinstance(summary, dict):
        return summary
    dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else meta
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
    mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
    return {
        "conviction": dc.get("conviction_at_entry"),
        "regime": mstate.get("regime"),
        "fsm_thesis_health": fsm.get("thesis_health"),
        "signal": dc.get("signal"),
    }


def audit_trade(
    trade: Dict[str, Any], audit_path: Path
) -> Dict[str, Any]:
    meta = trade.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    entry = _entry_fields(meta)
    opened = trade.get("opened_at") or trade.get("closed_at")
    flags: List[str] = []
    first_verdicts: List[Dict[str, Any]] = []
    if opened is not None:
        if hasattr(opened, "isoformat"):
            after = opened
        else:
            try:
                after = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
            except ValueError:
                after = None
        if after is not None:
            first_verdicts = _parse_verdicts_after(audit_path, after, str(trade["symbol"]))
    if first_verdicts:
        fv = first_verdicts[0]
        if fv.get("action") == "EXIT" and (fv.get("health") or 100) < 50:
            flags.append("exit_first_bar")
        if entry.get("fsm_thesis_health") == "broken":
            flags.append("thesis_broken_at_entry")
        entry_conv = entry.get("conviction")
        if entry_conv is not None and fv.get("health") is not None and fv["health"] < 45:
            flags.append("low_health_first_bar")
    return {
        "symbol": trade.get("symbol"),
        "closed_at": str(trade.get("closed_at")),
        "pnl": float(trade.get("pnl") or 0),
        "entry": entry,
        "flags": flags,
        "first_verdicts": first_verdicts[:3],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Entry thesis stability audit")
    parser.add_argument("--start", default="2026-06-29")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--audit-log", default=str(ROOT / "logs" / "signal_audit" / "live_audit.md"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    audit_path = Path(args.audit_log)
    results = [audit_trade(t, audit_path) for t in trades]

    flag_counts: Dict[str, int] = {}
    for r in results:
        for f in r.get("flags") or []:
            flag_counts[f] = flag_counts.get(f, 0) + 1

    print("=== Entry stability flags ===")
    for flag, cnt in sorted(flag_counts.items(), key=lambda x: -x[1]):
        print(f"  {flag}: {cnt}")

    bad_entry = sum(1 for r in results if "thesis_broken_at_entry" in r.get("flags", []))
    fast_exit = sum(1 for r in results if "exit_first_bar" in r.get("flags", []))
    print(f"\nTrades: {len(results)}  thesis_broken_at_entry: {bad_entry}  exit_first_bar: {fast_exit}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
