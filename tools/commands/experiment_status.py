#!/usr/bin/env python3
"""Evaluate experiment registry entries against trade_outcomes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "data" / "experiments" / "registry.json"


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_by_config(config_hash: Optional[str], start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return []
    import psycopg2
    from psycopg2.extras import RealDictCursor

    clauses: List[str] = []
    params: List[Any] = []
    if start:
        clauses.append("closed_at::date >= %s")
        params.append(start)
    if end:
        clauses.append("closed_at::date <= %s")
        params.append(end)
    if config_hash:
        clauses.append("metadata->'system_context'->>'config_hash' = %s")
        params.append(config_hash)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""

    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT pnl, metadata FROM trade_outcomes WHERE 1=1 {where}",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"trade_count": 0, "profit_factor": 0.0, "expectancy": 0.0, "win_rate": 0.0}
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(pnls),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else 0.0,
        "expectancy": sum(pnls) / len(pnls),
        "win_rate": len(wins) / len(pnls),
    }


def evaluate_experiment(exp: Dict[str, Any], *, start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    trades = _fetch_by_config(exp.get("config_hash"), start or exp.get("start_date"), end or exp.get("end_date"))
    m = _metrics(trades)
    expected = exp.get("expected_metrics") or {}
    checks: List[Dict[str, Any]] = []

    min_trades = int(expected.get("min_trades") or 0)
    checks.append({"gate": "min_trades", "pass": m["trade_count"] >= min_trades, "value": m["trade_count"]})

    pf_min = expected.get("profit_factor_min")
    if pf_min is not None:
        checks.append(
            {
                "gate": "profit_factor_min",
                "pass": m["profit_factor"] >= float(pf_min),
                "value": round(m["profit_factor"], 4),
            }
        )

    exp_min = expected.get("expectancy_min_usd")
    if exp_min is not None:
        checks.append(
            {
                "gate": "expectancy_min",
                "pass": m["expectancy"] >= float(exp_min),
                "value": round(m["expectancy"], 4),
            }
        )

    passed = all(c["pass"] for c in checks) if checks else False
    status = "passed" if passed else "running" if m["trade_count"] < min_trades else "failed"

    return {
        "experiment_id": exp.get("experiment_id"),
        "hypothesis": exp.get("hypothesis"),
        "metrics": m,
        "checks": checks,
        "approval_status": status,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment registry status")
    parser.add_argument("--id", default=None, help="Experiment id filter")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    if not REGISTRY.is_file():
        print(f"Registry not found: {REGISTRY}", file=sys.stderr)
        return 2

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    experiments = data.get("experiments") or []
    if args.id:
        experiments = [e for e in experiments if e.get("experiment_id") == args.id]

    results = [evaluate_experiment(e, start=args.start, end=args.end) for e in experiments]
    print(json.dumps(results, indent=2))
    return 0 if all(r.get("approval_status") == "passed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
