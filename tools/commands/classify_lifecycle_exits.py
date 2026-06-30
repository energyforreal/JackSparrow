#!/usr/bin/env python3
"""Classify TLE lifecycle EXIT events from live_audit.md and join trade_outcomes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_EXIT_LINE_RE = re.compile(
    r"`trade_lifecycle_verdict`.*?action=`EXIT`.*?symbol=(?P<symbol>\S+).*?"
    r"health=(?P<health>[0-9.]+).*?opportunity=(?P<opportunity>[0-9.]+)"
    r"(?:.*?detail=`(?P<detail>[^`]+)`)?(?:.*?utc=`(?P<utc>[^`]+)`)?"
    r"(?:.*?event_id=`(?P<event_id>[^`]+)`)?"
)


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _classify_detail(detail: str, health: float, exit_max: float = 50.0) -> str:
    if detail.startswith("opposite") or detail == "opposite_entry_signal":
        return "opposite_signal"
    if detail.startswith("ml_reversal"):
        return "ml_reversal"
    if detail == "health_and_fsm_thesis_broken":
        return "health_and_fsm"
    if detail == "fsm_thesis_broken":
        return "fsm_broken"
    if detail == "health_below_exit_threshold" and health >= exit_max:
        return "label_untrusted_fsm_likely"
    if detail == "health_below_exit_threshold":
        return "health_threshold"
    return detail or "unknown"


def parse_audit_exits(path: Path, start: str, end: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "`trade_lifecycle_verdict`" not in line or "action=`EXIT`" not in line:
            continue
        m = _EXIT_LINE_RE.search(line)
        if not m:
            sym_m = re.search(r"symbol=(\S+)", line)
            health_m = re.search(r"health=([0-9.]+)", line)
            utc_m = re.search(r"utc=`([^`]+)`", line)
            detail_m = re.search(r"detail=`([^`]+)`", line)
            if not sym_m:
                continue
            health = float(health_m.group(1)) if health_m else 0.0
            detail = detail_m.group(1) if detail_m else ""
            utc = utc_m.group(1) if utc_m else ""
        else:
            health = float(m.group("health"))
            detail = m.group("detail") or ""
            utc = m.group("utc") or ""
        if utc:
            try:
                ts = datetime.fromisoformat(utc.replace("Z", "+00:00"))
                if ts.date().isoformat() < start or ts.date().isoformat() > end:
                    continue
            except ValueError:
                pass
        rows.append(
            {
                "symbol": m.group("symbol") if m else sym_m.group(1),
                "health": health,
                "opportunity": float(m.group("opportunity")) if m else 0.0,
                "detail": detail,
                "trigger": _classify_detail(detail, health),
                "utc": utc,
                "event_id": (m.group("event_id") if m else "") or "",
                "source": "audit_log",
            }
        )
    return rows


def _fetch_outcomes(start: str, end: str) -> List[Dict[str, Any]]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return []
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        return []
    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT closed_at, symbol, side, entry_price, exit_price, quantity, pnl,
                       close_reason, opened_at, metadata
                FROM trade_outcomes
                WHERE closed_at::date BETWEEN %s AND %s
                ORDER BY closed_at
                """,
                (start, end),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _join_outcome(
    exit_row: Dict[str, Any],
    outcomes: List[Dict[str, Any]],
    tolerance_sec: float,
) -> Optional[Dict[str, Any]]:
    if not exit_row.get("utc"):
        return None
    try:
        exit_ts = datetime.fromisoformat(str(exit_row["utc"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    sym = exit_row.get("symbol", "")
    best: Optional[Dict[str, Any]] = None
    best_delta = tolerance_sec + 1
    for o in outcomes:
        if str(o.get("symbol", "")) != sym:
            continue
        if o.get("close_reason") != "lifecycle_exit":
            continue
        closed = o.get("closed_at")
        if closed is None:
            continue
        if hasattr(closed, "tzinfo") and closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        delta = abs((closed - exit_ts).total_seconds())
        if delta <= tolerance_sec and delta < best_delta:
            best = o
            best_delta = delta
    return best


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_trigger: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_trigger[r.get("trigger") or "unknown"].append(r)
    summary: Dict[str, Any] = {}
    for trigger, group in sorted(by_trigger.items()):
        pnls = [float(g["pnl"]) for g in group if g.get("pnl") is not None]
        wins = sum(1 for p in pnls if p > 0)
        summary[trigger] = {
            "count": len(group),
            "wins": wins,
            "win_rate_pct": round(wins / len(group) * 100, 1) if group else 0,
            "total_pnl": round(sum(pnls), 4) if pnls else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify lifecycle EXIT triggers")
    parser.add_argument("--audit-log", default=str(ROOT / "logs" / "signal_audit" / "live_audit.md"))
    parser.add_argument("--start", default="2026-06-29")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--fix-deployed-at", default=None, help="ISO timestamp; pre-fix rows flagged")
    parser.add_argument("--tolerance-sec", type=float, default=120.0)
    parser.add_argument("--out", default=None, help="Write JSON rows to file")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    fix_at: Optional[datetime] = None
    if args.fix_deployed_at:
        try:
            fix_at = datetime.fromisoformat(args.fix_deployed_at.replace("Z", "+00:00"))
        except ValueError:
            print("Invalid --fix-deployed-at", file=sys.stderr)

    exits = parse_audit_exits(Path(args.audit_log), args.start, args.end)
    outcomes = _fetch_outcomes(args.start, args.end)

    merged: List[Dict[str, Any]] = []
    for ex in exits:
        row = dict(ex)
        if fix_at and ex.get("utc"):
            try:
                ts = datetime.fromisoformat(str(ex["utc"]).replace("Z", "+00:00"))
                if ts < fix_at:
                    row["label_untrusted"] = True
            except ValueError:
                pass
        match = _join_outcome(ex, outcomes, args.tolerance_sec)
        if match:
            meta = match.get("metadata") or {}
            outcome = meta.get("outcome") if isinstance(meta, dict) else {}
            lifecycle = outcome.get("lifecycle_exit") if isinstance(outcome, dict) else None
            if isinstance(lifecycle, dict) and lifecycle.get("exit_trigger"):
                row["trigger"] = lifecycle["exit_trigger"]
                row["source"] = "db_metadata"
            row["pnl"] = float(match["pnl"]) if match.get("pnl") is not None else None
            row["gross_pnl_usd"] = (
                float(outcome.get("gross_pnl_usd"))
                if isinstance(outcome, dict) and outcome.get("gross_pnl_usd") is not None
                else None
            )
            row["closed_at"] = (
                match["closed_at"].isoformat()
                if hasattr(match.get("closed_at"), "isoformat")
                else str(match.get("closed_at"))
            )
        merged.append(row)

    summary = summarize(merged)
    print("=== Trigger summary ===")
    for trigger, stats in summary.items():
        print(
            f"{trigger:28s}  n={stats['count']:3d}  "
            f"win_rate={stats['win_rate_pct']:5.1f}%  "
            f"total_pnl={stats['total_pnl']:8.4f}  avg={stats['avg_pnl']:7.4f}"
        )
    untrusted = sum(1 for r in merged if r.get("label_untrusted"))
    if untrusted:
        print(f"\nWarning: {untrusted} rows pre-fix (label_untrusted)")

    if not args.summary_only:
        print(f"\nParsed {len(exits)} audit EXIT lines, joined {sum(1 for r in merged if r.get('pnl') is not None)} trades")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": summary, "rows": merged}
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
