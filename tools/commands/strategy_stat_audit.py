#!/usr/bin/env python3
"""Phase 4 statistical strategy audit — expectancy, rejections, slippage, cohort compare."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_psycopg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _connect():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        return None, None
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None, None
    return psycopg2.connect(_normalize_psycopg_url(url)), RealDictCursor


def _date_clause(start: Optional[str], end: Optional[str]) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if start:
        clauses.append("closed_at::date >= %s")
        params.append(start)
    if end:
        clauses.append("closed_at::date <= %s")
        params.append(end)
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _expectancy_block(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    pf = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
    return {
        "trade_count": len(trades),
        "expectancy_usd": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": round(pf, 4),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "avg_win_usd": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_usd": round(sum(losses) / len(losses), 4) if losses else 0.0,
    }


def _rejection_breakdown(conn, cursor_factory) -> Dict[str, Any]:
    counts: Counter[str] = Counter()
    with conn.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute(
            """
            SELECT reject_reason, COUNT(*) AS n
            FROM entry_decisions
            WHERE reject_reason IS NOT NULL
            GROUP BY reject_reason
            ORDER BY n DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall()
    for row in rows:
        counts[str(row["reject_reason"] or "unknown")] = int(row["n"])

    structural: Counter[str] = Counter()
    with conn.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute(
            """
            SELECT metadata
            FROM entry_decisions
            WHERE metadata IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5000
            """
        )
        for (meta,) in cur.fetchall():
            if not isinstance(meta, dict):
                continue
            dc = meta.get("decision_context") or meta
            rb = dc.get("rule_based_pipeline") or {}
            gates = rb.get("structural_gates") or {}
            cats = gates.get("categories") or {}
            if isinstance(cats, dict):
                for cat, val in cats.items():
                    if val:
                        structural[str(cat)] += 1
            reasons = gates.get("block_reasons") or []
            if isinstance(reasons, list):
                for r in reasons:
                    structural[str(r)] += 1

    total = sum(counts.values()) or 1
    top = [
        {"reason": k, "count": v, "pct": round(v / total * 100, 2)}
        for k, v in counts.most_common(15)
    ]
    return {
        "entry_decisions_top": top,
        "structural_gate_categories": dict(structural.most_common(20)),
    }


def _slippage_study(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    entry_bps: List[float] = []
    exit_bps: List[float] = []
    by_regime: Dict[str, List[float]] = {}
    for t in trades:
        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        timing = meta.get("execution_timing") or {}
        e_slip = timing.get("execution_slippage_bps_entry") or meta.get(
            "slippage_bps_entry"
        )
        x_slip = timing.get("execution_slippage_bps_exit")
        if e_slip is not None:
            try:
                entry_bps.append(float(e_slip))
            except (TypeError, ValueError):
                pass
        if x_slip is not None:
            try:
                exit_bps.append(float(x_slip))
            except (TypeError, ValueError):
                pass
        dc = meta.get("decision_context") or {}
        rb = dc.get("rule_based_pipeline") or {}
        regime = str((rb.get("market_state") or {}).get("regime") or "unknown")
        if e_slip is not None:
            by_regime.setdefault(regime, []).append(float(e_slip))

    def _stats(vals: List[float]) -> Dict[str, float]:
        if not vals:
            return {}
        s = sorted(vals)
        p95_idx = min(len(s) - 1, int(len(s) * 0.95))
        return {
            "count": len(vals),
            "mean_bps": round(sum(vals) / len(vals), 2),
            "p95_bps": round(s[p95_idx], 2),
        }

    return {
        "entry_slippage": _stats(entry_bps),
        "exit_slippage": _stats(exit_bps),
        "entry_slippage_by_regime": {
            k: _stats(v) for k, v in by_regime.items() if v
        },
    }


def _feature_compare(conn, cursor_factory) -> Dict[str, Any]:
    """Compare accepted trade snapshots vs rejected entry_decisions metadata."""
    accepted_atr: List[float] = []
    rejected_atr: List[float] = []
    with conn.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute(
            """
            SELECT metadata FROM trade_outcomes
            WHERE metadata IS NOT NULL
            ORDER BY closed_at DESC
            LIMIT 500
            """
        )
        for (meta,) in cur.fetchall():
            if not isinstance(meta, dict):
                continue
            feats = (meta.get("decision_context") or {}).get("features") or meta.get(
                "features"
            )
            if isinstance(feats, dict) and feats.get("atr_14") is not None:
                try:
                    accepted_atr.append(float(feats["atr_14"]))
                except (TypeError, ValueError):
                    pass
        cur.execute(
            """
            SELECT metadata FROM entry_decisions
            WHERE reject_reason IS NOT NULL AND metadata IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
            """
        )
        for (meta,) in cur.fetchall():
            if not isinstance(meta, dict):
                continue
            feats = (meta.get("decision_context") or {}).get("features") or meta.get(
                "features"
            )
            if isinstance(feats, dict) and feats.get("atr_14") is not None:
                try:
                    rejected_atr.append(float(feats["atr_14"]))
                except (TypeError, ValueError):
                    pass

    def _mean(vals: List[float]) -> Optional[float]:
        return round(sum(vals) / len(vals), 6) if vals else None

    return {
        "accepted_atr_14_mean": _mean(accepted_atr),
        "rejected_atr_14_mean": _mean(rejected_atr),
        "accepted_sample": len(accepted_atr),
        "rejected_sample": len(rejected_atr),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "investigation" / "strategy_stat_audit.json"),
    )
    args = parser.parse_args()

    conn, RealDictCursor = _connect()
    if conn is None:
        print("Set DATABASE_URL", file=sys.stderr)
        return 2

    where, params = _date_clause(args.start, args.end)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT pnl, metadata, close_reason, opened_at
            FROM trade_outcomes
            WHERE 1=1 {where}
            ORDER BY closed_at
            """,
            params,
        )
        trades = [dict(r) for r in cur.fetchall()]

    report = {
        "phase": "4_statistical_audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": args.start, "end": args.end},
        "expectancy_primary": _expectancy_block(trades),
        "rejection_breakdown": _rejection_breakdown(conn, RealDictCursor),
        "slippage_study": _slippage_study(trades),
        "accepted_vs_rejected_features": _feature_compare(conn, RealDictCursor),
    }
    conn.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
