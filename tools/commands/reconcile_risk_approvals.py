#!/usr/bin/env python3
"""
Reconcile structlog JSON agent logs with execution outcomes.

For each `trading_handler_risk_approved_published` event_id, expects either:
- `execution_order_fill_published` with the same event_id, or
- `trading_execution_rejected` with correlation_id == event_id, or
- `execution_failed` with correlation_id == event_id

Optionally compares to paper ledger TRADE| lines (time-ordered; best-effort).

Usage:
  python tools/commands/reconcile_risk_approvals.py path/to/agent.log [path/to/paper_trades.log]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple


def _iter_json_objects(line: str) -> Iterable[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            yield obj
    except json.JSONDecodeError:
        pass


def _event_name(obj: Dict[str, Any]) -> Optional[str]:
    return obj.get("event") or obj.get("logger") or obj.get("msg")


def _scan_agent_log(path: Path) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Returns (approved_ids, filled_ids, rejected_ids, failed_ids)."""
    approved: Set[str] = set()
    filled: Set[str] = set()
    rejected: Set[str] = set()
    failed: Set[str] = set()

    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            for obj in _iter_json_objects(line):
                ev = _event_name(obj)
                if ev == "trading_handler_risk_approved_published":
                    eid = obj.get("event_id")
                    if eid:
                        approved.add(str(eid))
                elif ev == "execution_order_fill_published":
                    eid = obj.get("event_id")
                    if eid:
                        filled.add(str(eid))
                elif ev == "trading_execution_rejected":
                    cid = obj.get("correlation_id")
                    if cid:
                        rejected.add(str(cid))
                elif ev == "execution_failed":
                    cid = obj.get("correlation_id")
                    if cid:
                        failed.add(str(cid))
    return approved, filled, rejected, failed


_TRADE_LINE = re.compile(r"^TRADE\|")


def _count_paper_trades(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if _TRADE_LINE.match(line.strip()):
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "agent_log",
        type=Path,
        help="Structlog JSON log (e.g. agent.log)",
    )
    parser.add_argument(
        "paper_log",
        type=Path,
        nargs="?",
        default=None,
        help="Optional paper_trades.log for TRADE| count summary",
    )
    args = parser.parse_args()

    if not args.agent_log.is_file():
        print(f"Not a file: {args.agent_log}", file=sys.stderr)
        return 2

    approved, filled, rejected, failed = _scan_agent_log(args.agent_log)

    accounted = filled | rejected | failed
    orphans = approved - accounted
    unexpected_fills = filled - approved

    print("--- Risk approval reconciliation ---")
    print(f"trading_handler_risk_approved_published: {len(approved)}")
    print(f"execution_order_fill_published (matched ids): {len(filled)}")
    print(f"trading_execution_rejected (correlation_id): {len(rejected)}")
    print(f"execution_failed (correlation_id): {len(failed)}")
    if args.paper_log:
        n_trade = _count_paper_trades(args.paper_log)
        print(f"paper TRADE| lines in {args.paper_log.name}: {n_trade}")

    if orphans:
        print(f"\nUNMATCHED approvals (no fill / rejection / failure log): {len(orphans)}")
        for x in sorted(orphans)[:50]:
            print(f"  - {x}")
        if len(orphans) > 50:
            print(f"  ... and {len(orphans) - 50} more")
        rc = 1
    else:
        print("\nAll logged approvals have a recorded outcome (fill, rejection, or failure).")
        rc = 0

    if unexpected_fills:
        print(
            f"\nWARN: execution_order_fill_published event_ids not seen in approvals: "
            f"{len(unexpected_fills)}"
        )
        for x in sorted(unexpected_fills)[:20]:
            print(f"  - {x}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
