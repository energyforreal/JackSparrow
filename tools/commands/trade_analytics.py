#!/usr/bin/env python3
"""Trade analytics CLI — snapshot integrity, reject breakdown, regime performance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


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

    args = parser.parse_args()
    handlers = {
        "snapshot-integrity": cmd_snapshot_integrity,
        "reject-breakdown": cmd_reject_breakdown,
        "regime-performance": cmd_regime_performance,
        "config-diff": cmd_config_diff,
        "archive-verify": cmd_archive_verify,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
