#!/usr/bin/env python3
"""Monitor LOG_ONLY TLE observation cycles from signal audit logs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_VERDICT_RE = re.compile(
    r"trade_lifecycle_verdict.*?action=`(?P<action>[A-Z_]+)`.*?"
    r"(?:health_score=|health=)(?P<health>[\d.]+).*?"
    r"(?:opportunity_score=|opportunity=)(?P<opp>[\d.]+)"
)


def scan_audit_log(path: Path) -> dict:
    actions: Counter[str] = Counter()
    health_samples: list[float] = []
    opp_samples: list[float] = []
    if not path.is_file():
        return {"error": "audit_log_not_found", "path": str(path)}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "trade_lifecycle_verdict" not in line:
            continue
        m = _VERDICT_RE.search(line)
        if not m:
            continue
        actions[m.group("action")] += 1
        try:
            health_samples.append(float(m.group("health")))
            opp_samples.append(float(m.group("opp")))
        except ValueError:
            pass
    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "audit_log": str(path),
        "verdict_count": sum(actions.values()),
        "action_counts": dict(actions),
        "avg_health": round(sum(health_samples) / len(health_samples), 2) if health_samples else None,
        "avg_opportunity": round(sum(opp_samples) / len(opp_samples), 2) if opp_samples else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TLE LOG_ONLY observation monitor")
    parser.add_argument(
        "--audit-log",
        default=str(ROOT / "logs" / "agent" / "signal_audit" / "live_audit.md"),
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    report = scan_audit_log(Path(args.audit_log))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
