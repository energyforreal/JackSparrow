#!/usr/bin/env python3
"""
Paper trade ledger utilities: count TRADE|/CLOSE| lines and reconcile with DB.

Default ledger directory (first match):
  1) --log-dir
  2) $LOGS_ROOT/paper_trades
  3) <repo>/logs/paper_trades (repo = parents[2] from this file)

Rotated files paper_trades.log, paper_trades.log.1, ... are included.

Examples:
  python tools/commands/paper_trade_audit.py count
  python tools/commands/paper_trade_audit.py count --log-dir D:/path/to/logs/paper_trades
  python tools/commands/paper_trade_audit.py reconcile
  DATABASE_URL=postgresql://... python tools/commands/paper_trade_audit.py reconcile
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_TRADE = re.compile(r"^TRADE\|")
_CLOSE = re.compile(r"^CLOSE\|")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_log_dir() -> Path:
    env = os.environ.get("LOGS_ROOT")
    if env:
        return Path(env) / "paper_trades"
    return _repo_root() / "logs" / "paper_trades"


def _iter_ledger_files(log_dir: Path) -> List[Path]:
    if not log_dir.is_dir():
        return []
    files: List[Path] = []
    primary = log_dir / "paper_trades.log"
    if primary.is_file():
        files.append(primary)
    for i in range(1, 10):
        p = log_dir / f"paper_trades.log.{i}"
        if p.is_file():
            files.append(p)
    return files


def count_lines_in_file(path: Path) -> Tuple[int, int]:
    """Returns (trade_lines, close_lines)."""
    trades = closes = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if _TRADE.match(s):
                trades += 1
            elif _CLOSE.match(s):
                closes += 1
    return trades, closes


def count_ledger(log_dir: Path) -> Tuple[int, int, Dict[str, Tuple[int, int]]]:
    """Returns (total_trades, total_closes, per_file)."""
    per: Dict[str, Tuple[int, int]] = {}
    tt = tc = 0
    for p in _iter_ledger_files(log_dir):
        a, b = count_lines_in_file(p)
        per[str(p)] = (a, b)
        tt += a
        tc += b
    return tt, tc, per


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _count_trades_in_db(database_url: str) -> Optional[int]:
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed; skip DB count.", file=sys.stderr)
        return None
    url = _normalize_psycopg_url(database_url.strip())
    try:
        conn = psycopg2.connect(url)
    except Exception as e:
        print(f"DB connection failed: {e}", file=sys.stderr)
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trades")
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        conn.close()


def cmd_count(args: argparse.Namespace) -> int:
    log_dir = Path(args.log_dir) if args.log_dir else _default_log_dir()
    if not log_dir.is_dir():
        print(f"Ledger directory not found: {log_dir}", file=sys.stderr)
        print("Set LOGS_ROOT or pass --log-dir.", file=sys.stderr)
        return 2
    tt, tc, per = count_ledger(log_dir)
    print(f"Ledger directory: {log_dir}")
    if not per:
        print("No paper_trades.log[.*] files found.")
        print("TRADE lines (fills): 0")
        print("CLOSE lines (exits): 0")
        return 0
    for path, (a, b) in per.items():
        print(f"  {path}: TRADE={a} CLOSE={b}")
    print("---")
    print(f"TRADE lines (fills): {tt}")
    print(f"CLOSE lines (exits): {tc}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    rc = cmd_count(args)
    if rc != 0:
        return rc
    log_dir = Path(args.log_dir) if args.log_dir else _default_log_dir()
    tt, _, _ = count_ledger(log_dir)

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("---")
        print("DB: skipped (set DATABASE_URL or --database-url to compare with `trades` table).")
        print("Backend log hints for persistence issues:")
        print('  Select-String -Path logs/backend/*.log -Pattern "trade_persisted_to_database|trade_persistence_failed|agent_event_subscriber_order_fill"')
        return 0

    n_db = _count_trades_in_db(db_url)
    print("---")
    if n_db is not None:
        print(f"PostgreSQL `trades` row count: {n_db}")
        print(f"Ledger TRADE| lines: {tt}")
        if tt > 0 and n_db == 0:
            print(
                "Mismatch: ledger has fills but DB has no trades — check event subscriber / "
                "RESET_PAPER_STATE_ON_STARTUP (backend wipes DB on startup when true)."
            )
        elif tt != n_db:
            print("Counts differ (expected after resets, duplicates, or partial persistence).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_count = sub.add_parser("count", help="Count TRADE| and CLOSE| lines in paper ledger files")
    p_count.add_argument("--log-dir", type=str, default=None, help="Directory containing paper_trades.log")
    p_count.set_defaults(func=cmd_count)

    p_rec = sub.add_parser("reconcile", help="Count ledger + optional DB row count")
    p_rec.add_argument("--log-dir", type=str, default=None)
    p_rec.add_argument("--database-url", type=str, default=None, help="Overrides DATABASE_URL")
    p_rec.set_defaults(func=cmd_reconcile)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
