#!/usr/bin/env python3
"""Trade analytics CLI — snapshot integrity, reject breakdown, regime performance."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _connect():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 required for DB commands", file=sys.stderr)
        return None
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("Set DATABASE_URL", file=sys.stderr)
        return None
    try:
        return psycopg2.connect(_normalize_psycopg_url(url))
    except Exception as exc:
        print(f"DB connection failed: {exc}", file=sys.stderr)
        return None


def _date_filter_sql(start: Optional[str], end: Optional[str]) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if start:
        clauses.append("closed_at::date >= %s")
        params.append(start)
    if end:
        clauses.append("closed_at::date <= %s")
        params.append(end)
    sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def _parse_audit_exit_triggers(audit_path: Path, start: str, end: str) -> Dict[str, int]:
    """Best-effort exit trigger counts from live_audit.md (pre-fix heuristics)."""
    counts: Dict[str, int] = {}
    if not audit_path.is_file():
        return counts
    exit_max_default = 50.0
    for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "`trade_lifecycle_verdict`" not in line or "action=`EXIT`" not in line:
            continue
        utc_m = re.search(r"utc=`([^`]+)`", line)
        if not utc_m:
            continue
        try:
            ts = datetime.fromisoformat(utc_m.group(1).replace("Z", "+00:00"))
            d = ts.date().isoformat()
            if d < start or d > end:
                continue
        except ValueError:
            continue
        detail_m = re.search(r"detail=`([^`]+)`", line)
        health_m = re.search(r"health=([0-9.]+)", line)
        detail = detail_m.group(1) if detail_m else ""
        health = float(health_m.group(1)) if health_m else 0.0
        if detail.startswith("opposite") or "opposite" in detail:
            bucket = "opposite_signal"
        elif detail.startswith("ml_reversal"):
            bucket = "ml_reversal"
        elif detail == "health_and_fsm_thesis_broken":
            bucket = "health_and_fsm"
        elif detail == "fsm_thesis_broken":
            bucket = "fsm_broken"
        elif detail == "health_below_exit_threshold" and health >= exit_max_default:
            bucket = "label_untrusted_fsm_likely"
        elif detail == "health_below_exit_threshold":
            bucket = "health_threshold"
        else:
            bucket = detail or "unknown"
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def cmd_snapshot_integrity(_: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trade_outcomes")
            total = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*) FROM trade_outcomes
                WHERE metadata->'decision_context'->'rule_based_pipeline' IS NOT NULL
                  AND metadata->'decision_context'->'rule_based_pipeline' != 'null'::jsonb
                """
            )
            with_rb = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*) FROM trade_outcomes
                WHERE metadata->>'snapshot_version' IS NOT NULL
                """
            )
            versioned = int(cur.fetchone()[0])
        pct = (with_rb / total * 100.0) if total else 0.0
        print(f"trade_outcomes total: {total}")
        print(f"with rule_based_pipeline: {with_rb} ({pct:.1f}%)")
        print(f"with snapshot_version: {versioned}")
        return 0
    finally:
        conn.close()


def cmd_reject_breakdown(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT reject_reason, COUNT(*) AS cnt
                FROM entry_decisions
                WHERE outcome = 'rejected'
            """
            params: List[Any] = []
            if args.symbol:
                sql += " AND symbol = %s"
                params.append(args.symbol)
            sql += " GROUP BY reject_reason ORDER BY cnt DESC LIMIT 50"
            cur.execute(sql, params)
            rows = cur.fetchall()
        for reason, cnt in rows:
            print(f"{cnt:6d}  {reason or 'unknown'}")
        return 0
    finally:
        conn.close()


def cmd_regime_performance(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT period_key, trade_count, win_count, total_pnl_usd
                FROM analytics_rollups
                WHERE period_type = 'regime'
            """
            params: List[Any] = []
            if args.symbol:
                sql += " AND symbol = %s"
                params.append(args.symbol)
            sql += " ORDER BY total_pnl_usd DESC"
            cur.execute(sql, params)
            rows = cur.fetchall()
        if not rows:
            print("No analytics_rollups regime rows yet.")
            return 0
        for key, tc, wc, pnl in rows:
            wr = (wc / tc * 100.0) if tc else 0.0
            print(f"{key:20s}  trades={tc:4d}  win_rate={wr:5.1f}%  pnl_usd={float(pnl):.4f}")
        return 0
    finally:
        conn.close()


def cmd_config_diff(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT period_key, trade_count, win_count, total_pnl_usd
                FROM analytics_rollups
                WHERE period_type = 'config_hash'
                ORDER BY period_key
                """
            )
            rows = cur.fetchall()
        for key, tc, wc, pnl in rows:
            if args.a and args.b and key not in (args.a, args.b):
                continue
            wr = (wc / tc * 100.0) if tc else 0.0
            print(f"{key}  trades={tc}  win_rate={wr:.1f}%  pnl_usd={float(pnl):.4f}")
        return 0
    finally:
        conn.close()


def cmd_archive_verify(_: argparse.Namespace) -> int:
    manifest = _repo_root() / "data" / "agent_closed_trades" / "archive" / "manifest.json"
    if not manifest.is_file():
        print("No archive manifest found.")
        return 0
    data = json.loads(manifest.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2))
    return 0


def cmd_fee_dominance(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    date_sql, params = _date_filter_sql(args.start, args.end)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT close_reason,
                  COUNT(*) FILTER (
                    WHERE COALESCE((metadata->'outcome'->>'gross_pnl_usd')::float, 0) > 0
                      AND COALESCE(pnl::float, 0) < 0
                  ) AS gross_win_net_loss,
                  COUNT(*) AS total,
                  ROUND(AVG(COALESCE((metadata->'outcome'->>'fees_usd')::float, 0))::numeric, 4)
                    AS avg_fees
                FROM trade_outcomes
                WHERE 1=1 {date_sql}
                GROUP BY close_reason
                ORDER BY total DESC
                """,
                params,
            )
            rows = cur.fetchall()
        print(f"{'close_reason':24s}  {'gross+/net-':>12s}  {'total':>6s}  {'avg_fees':>10s}")
        for reason, gw_nl, total, avg_fees in rows:
            print(f"{reason or 'unknown':24s}  {int(gw_nl):12d}  {int(total):6d}  {float(avg_fees):10.4f}")
        return 0
    finally:
        conn.close()


def cmd_lifecycle_window(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    date_sql, params = _date_filter_sql(args.start, args.end)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) AS trades,
                  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                  ROUND(SUM(COALESCE(pnl::float, 0))::numeric, 4) AS total_net,
                  ROUND(SUM(COALESCE((metadata->'outcome'->>'gross_pnl_usd')::float, 0))::numeric, 4)
                    AS total_gross,
                  ROUND(AVG(quantity::float)::numeric, 2) AS avg_lots
                FROM trade_outcomes
                WHERE close_reason = 'lifecycle_exit' {date_sql}
                """,
                params,
            )
            row = cur.fetchone()
        if not row or not row[0]:
            print("No lifecycle_exit trades in window.")
            return 0
        trades, wins, total_net, total_gross, avg_lots = row
        wr = (wins / trades * 100.0) if trades else 0.0
        print(f"lifecycle_exit trades={trades} wins={wins} win_rate={wr:.1f}%")
        print(f"total_net_pnl={float(total_net):.4f} total_gross_pnl={float(total_gross):.4f}")
        print(f"avg_lots={float(avg_lots):.2f}")
        return 0
    finally:
        conn.close()


def cmd_baseline_capture(args: argparse.Namespace) -> int:
    conn = _connect()
    start = args.start or "2026-06-29"
    end = args.end or "2026-06-30"
    audit_path = Path(args.audit_log) if args.audit_log else _repo_root() / "logs" / "signal_audit" / "live_audit.md"
    out_path = Path(args.out) if args.out else _repo_root() / "data" / "investigation" / f"baseline_{start}_{end}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    baseline: Dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start, "end": end},
        "data_gaps": [],
    }

    if conn is None:
        baseline["data_gaps"].append("DATABASE_URL not set or connection failed")
        out_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        print(f"Wrote partial baseline to {out_path}")
        return 2

    date_sql, params = _date_filter_sql(start, end)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) AS trades,
                  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                  ROUND(SUM(COALESCE(pnl::float, 0))::numeric, 4) AS total_pnl,
                  ROUND(AVG(COALESCE(pnl::float, 0))::numeric, 4) AS avg_pnl,
                  SUM(CASE WHEN COALESCE((metadata->'outcome'->>'gross_pnl_usd')::float, 0) > 0
                            AND COALESCE(pnl::float, 0) < 0 THEN 1 ELSE 0 END) AS fee_dominated,
                  ROUND(AVG(COALESCE((metadata->'outcome'->>'fees_usd')::float, 0))::numeric, 4)
                    AS avg_fees,
                  COUNT(*) FILTER (WHERE opened_at IS NULL) AS missing_opened_at
                FROM trade_outcomes
                WHERE 1=1 {date_sql}
                """,
                params,
            )
            row = cur.fetchone()
            if row:
                trades, wins, total_pnl, avg_pnl, fee_dom, avg_fees, missing_opened = row
                baseline["trades"] = {
                    "count": int(trades or 0),
                    "wins": int(wins or 0),
                    "win_rate_pct": round((wins / trades * 100.0) if trades else 0.0, 2),
                    "total_pnl_usd": float(total_pnl or 0),
                    "avg_pnl_usd": float(avg_pnl or 0),
                    "fee_dominated_count": int(fee_dom or 0),
                    "avg_fees_usd": float(avg_fees or 0),
                }
                if missing_opened:
                    baseline["data_gaps"].append(
                        f"opened_at NULL on {missing_opened}/{trades} rows"
                    )

            cur.execute(
                f"""
                SELECT close_reason, COUNT(*), ROUND(SUM(COALESCE(pnl::float,0))::numeric, 4)
                FROM trade_outcomes WHERE 1=1 {date_sql}
                GROUP BY close_reason ORDER BY COUNT(*) DESC
                """,
                params,
            )
            baseline["by_close_reason"] = [
                {"close_reason": r, "count": int(c), "total_pnl": float(p)}
                for r, c, p in cur.fetchall()
            ]
    finally:
        conn.close()

    baseline["exit_triggers_audit_heuristic"] = _parse_audit_exit_triggers(
        audit_path, start, end
    )
    if not audit_path.is_file():
        baseline["data_gaps"].append(f"audit log not found: {audit_path}")

    baseline["mfe_mae"] = {
        "status": "partial_price_delta_only",
        "note": "Full MFE/MAE via replay_trade_excursions.py",
    }

    out_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(json.dumps(baseline, indent=2))
    print(f"\nWrote baseline to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JackSparrow trade analytics utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot-integrity", help="Check trade_outcomes snapshot coverage")
    rb = sub.add_parser("reject-breakdown", help="Count entry reject reasons")
    rb.add_argument("--symbol", default=None)
    rp = sub.add_parser("regime-performance", help="Regime rollup summary")
    rp.add_argument("--symbol", default=None)
    cd = sub.add_parser("config-diff", help="Config hash cohort comparison")
    cd.add_argument("--a", default=None, help="First config_hash prefix")
    cd.add_argument("--b", default=None, help="Second config_hash prefix")
    sub.add_parser("archive-verify", help="Show agent ledger archive manifest")

    fd = sub.add_parser("fee-dominance", help="Gross-win net-loss counts by close_reason")
    fd.add_argument("--start", default=None)
    fd.add_argument("--end", default=None)

    lw = sub.add_parser("lifecycle-window", help="Lifecycle exit rollup for date window")
    lw.add_argument("--start", default=None)
    lw.add_argument("--end", default=None)

    bc = sub.add_parser("baseline-capture", help="Capture investigation baseline JSON")
    bc.add_argument("--start", default="2026-06-29")
    bc.add_argument("--end", default="2026-06-30")
    bc.add_argument("--audit-log", default=None)
    bc.add_argument("--out", default=None)

    args = parser.parse_args()
    handlers = {
        "snapshot-integrity": cmd_snapshot_integrity,
        "reject-breakdown": cmd_reject_breakdown,
        "regime-performance": cmd_regime_performance,
        "config-diff": cmd_config_diff,
        "archive-verify": cmd_archive_verify,
        "fee-dominance": cmd_fee_dominance,
        "lifecycle-window": cmd_lifecycle_window,
        "baseline-capture": cmd_baseline_capture,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
