#!/usr/bin/env python3
"""TLE replay agreement and opportunity score validation."""

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


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _fetch_trades(start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
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
    where = (" AND " + " AND ".join(clauses)) if clauses else ""

    conn = psycopg2.connect(_normalize_psycopg_url(url))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT pnl, side, entry_price, exit_price, metadata FROM trade_outcomes WHERE 1=1 {where}",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _side_sign(side: str) -> int:
    return 1 if str(side).lower() in ("long", "buy") else -1


def evaluate_opportunity_cycles(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score whether opportunity_score predicted continuation."""
    high_correct = high_total = 0
    low_hold_bad = low_hold_total = 0

    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        monitoring = meta.get("position_monitoring")
        if not isinstance(monitoring, list):
            continue
        side = _side_sign(str(row.get("side") or "long"))
        try:
            entry = float(row.get("entry_price") or 0)
            exit_p = float(row.get("exit_price") or 0)
        except (TypeError, ValueError):
            continue
        if entry <= 0:
            continue
        trade_return = side * (exit_p - entry) / entry

        for i, rec in enumerate(monitoring):
            opp = rec.get("opportunity_score")
            action = str(rec.get("action_would_be") or "HOLD")
            if opp is None:
                continue
            try:
                opp_f = float(opp)
            except (TypeError, ValueError):
                continue

            if action == "EXIT" and opp_f >= 80:
                high_total += 1
                if trade_return > 0.005:
                    high_correct += 1
            if action == "HOLD" and opp_f <= 40:
                low_hold_total += 1
                if trade_return < 0:
                    low_hold_bad += 1

    precision = high_correct / high_total if high_total else 0.0
    recall_denom = low_hold_bad + (high_total - high_correct)
    recall = low_hold_bad / recall_denom if recall_denom else 0.0

    return {
        "opportunity_precision": round(precision, 4),
        "opportunity_recall": round(recall, 4),
        "high_opp_exit_cycles": high_total,
        "low_opp_hold_cycles": low_hold_total,
    }


def evaluate_exit_agreement(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare log-only TLE EXIT recommendations vs bracket outcomes."""
    exit_agree = exit_total = 0
    hold_agree = hold_total = 0

    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        monitoring = meta.get("position_monitoring")
        if not isinstance(monitoring, list):
            continue
        pnl = float(row.get("pnl") or 0)
        for rec in monitoring:
            action = str(rec.get("action_would_be") or "HOLD")
            if action == "EXIT":
                exit_total += 1
                if pnl >= 0:
                    exit_agree += 1
            elif action == "HOLD":
                hold_total += 1
                health = rec.get("health_score")
                try:
                    if health is not None and float(health) >= 50:
                        hold_agree += 1
                except (TypeError, ValueError):
                    pass

    exit_rate = exit_agree / exit_total if exit_total else 0.0
    hold_rate = hold_agree / hold_total if hold_total else 0.0
    overall = (exit_rate + hold_rate) / 2.0 if (exit_total or hold_total) else 0.0

    return {
        "exit_agreement_rate": round(exit_rate, 4),
        "hold_agreement_rate": round(hold_rate, 4),
        "overall_agreement": round(overall, 4),
        "exit_cycles": exit_total,
        "hold_cycles": hold_total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TLE agreement and opportunity validation")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    trades = _fetch_trades(args.start, args.end)
    report: Dict[str, Any] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(trades),
        **evaluate_exit_agreement(trades),
        **evaluate_opportunity_cycles(trades),
    }
    report["pass"] = (
        report.get("overall_agreement", 0) >= 0.80
        and report.get("exit_agreement_rate", 0) >= 0.75
        and report.get("opportunity_precision", 0) >= 0.65
    )

    text = json.dumps(report, indent=2)
    print(text)

    out = Path(args.out) if args.out else ROOT / "data" / "experiments" / "tle_agreement_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
