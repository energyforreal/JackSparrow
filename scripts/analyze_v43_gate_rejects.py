#!/usr/bin/env python3
"""Aggregate v43-related reject signals from agent NDJSON logs.

Usage:
  python scripts/analyze_v43_gate_rejects.py agent.ndjson
  docker logs jacksparrow-agent 2>&1 | python scripts/analyze_v43_gate_rejects.py

Counts JSON lines by ``event`` name and ``reject`` / ``reject_tail`` fields where present.
See docs/v43_trade_execution_runbook.md (Phase 5).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any, Dict, TextIO


def _iter_json_lines(stream: TextIO):
    for raw in stream:
        line = raw.strip()
        if not line or line.startswith("docker :"):
            line = line.removeprefix("docker :").strip()
        if not line or line[0] not in "{[":
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _accumulate(obj: Dict[str, Any], by_event: Counter, by_reject: Counter) -> None:
    ev = obj.get("event")
    if not isinstance(ev, str):
        return
    if ev in (
        "mcp_orchestrator_v43_prediction_complete",
        "v43_gate5_rejected",
        "trading_entry_rejected",
    ):
        by_event[ev] += 1
    rej = obj.get("reject")
    if isinstance(rej, str) and ev == "mcp_orchestrator_v43_prediction_complete":
        by_reject[f"v43_complete:{rej}"] += 1
    rt = obj.get("reject_tail") or obj.get("reason")
    if isinstance(rt, str) and ev == "trading_entry_rejected":
        by_reject[f"trading_handler:{rt}"] += 1


def main() -> int:
    paths = sys.argv[1:]
    by_event: Counter = Counter()
    by_reject: Counter = Counter()

    streams: list[TextIO]
    if not paths or paths == ["-"]:
        streams = [sys.stdin]
        paths = ["-"]
    else:
        streams = [open(p, "r", encoding="utf-8") for p in paths]

    try:
        for stream in streams:
            for obj in _iter_json_lines(stream):
                if isinstance(obj, dict):
                    _accumulate(obj, by_event, by_reject)
    finally:
        for p, stream in zip(paths, streams):
            if p != "-":
                stream.close()

    print("=== events (subset) ===")
    for k, v in by_event.most_common():
        print(f"  {k}: {v}")
    print("=== reject breakdown ===")
    for k, v in by_reject.most_common():
        print(f"  {k}: {v}")
    if not by_event and not by_reject:
        print("(no matching lines — pass an agent NDJSON log path or stdin)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
