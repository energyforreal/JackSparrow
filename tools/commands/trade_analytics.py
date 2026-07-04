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
            cur.execute(
                """
                SELECT COUNT(*) FROM trade_outcomes
                WHERE metadata->'decision_context'->'entry_quality' IS NOT NULL
                """
            )
            with_eq = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*) FROM trade_outcomes
                WHERE metadata->'execution_timing'->'execution_slippage_bps_entry' IS NOT NULL
                """
            )
            with_slip = int(cur.fetchone()[0])
        pct = (with_rb / total * 100.0) if total else 0.0
        eq_pct = (with_eq / total * 100.0) if total else 0.0
        slip_pct = (with_slip / total * 100.0) if total else 0.0
        print(f"trade_outcomes total: {total}")
        print(f"with rule_based_pipeline: {with_rb} ({pct:.1f}%)")
        print(f"with snapshot_version: {versioned}")
        print(f"with entry_quality: {with_eq} ({eq_pct:.1f}%)")
        print(f"with entry slippage: {with_slip} ({slip_pct:.1f}%)")
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


def cmd_economic_summary(args: argparse.Namespace) -> int:
    """Sharpe, Sortino, max drawdown, recovery factor from trade_outcomes."""
    conn = _connect()
    if conn is None:
        return 2
    date_sql, params = _date_filter_sql(args.start, args.end)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT closed_at, COALESCE(pnl::float, 0) AS pnl
                FROM trade_outcomes
                WHERE 1=1 {date_sql}
                ORDER BY closed_at
                """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("No trades in window.")
        return 0

    import math

    pnls = [float(r[1]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = sum(pnls) / len(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    mean = expectancy
    var = sum((p - mean) ** 2 for p in pnls) / max(len(pnls) - 1, 1)
    std = math.sqrt(var) if var > 0 else 0.0
    sharpe = (mean / std) * math.sqrt(len(pnls)) if std > 0 else 0.0

    downside = [min(0.0, p) for p in pnls]
    d_var = sum(d ** 2 for d in downside) / max(len(downside) - 1, 1)
    d_std = math.sqrt(d_var) if d_var > 0 else 0.0
    sortino = (mean / d_std) * math.sqrt(len(pnls)) if d_std > 0 else 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
    max_dd_pct = (max_dd / peak * 100.0) if peak > 0 else 0.0
    recovery_factor = sum(pnls) / max_dd if max_dd > 0 else 0.0

    summary = {
        "trade_count": len(pnls),
        "expectancy_per_trade": round(expectancy, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "win_loss_ratio": round(avg_win / avg_loss, 4) if avg_loss > 0 else None,
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_usd": round(max_dd, 4),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "recovery_factor": round(recovery_factor, 4),
        "net_pnl": round(sum(pnls), 4),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _fetch_metadata_trades(conn, start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor

    date_sql, params = _date_filter_sql(start, end)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT pnl, metadata FROM trade_outcomes WHERE 1=1 {date_sql} ORDER BY closed_at",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def cmd_market_validation(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        trades = _fetch_metadata_trades(conn, args.start, args.end)
    finally:
        conn.close()
    scores: List[float] = []
    with_mv = 0
    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        mv = dc.get("market_validation")
        if isinstance(mv, dict):
            with_mv += 1
            try:
                scores.append(float(mv.get("validation_score") or 0))
            except (TypeError, ValueError):
                pass
    n = len(trades)
    mean_score = sum(scores) / len(scores) if scores else 0.0
    print(f"trades={n} with_market_validation={with_mv} mean_validation_score={mean_score:.2f}")
    return 0


def cmd_regime_benchmarks(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        trades = _fetch_metadata_trades(conn, args.start, args.end)
    finally:
        conn.close()
    buckets: Dict[str, Dict[str, float]] = {}
    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        bench = dc.get("regime_benchmark")
        if not bench:
            rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
            ms = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
            bench = ms.get("regime_benchmark") or ms.get("regime") or "unknown"
        key = str(bench)
        if key not in buckets:
            buckets[key] = {"count": 0, "wins": 0, "pnl": 0.0}
        buckets[key]["count"] += 1
        try:
            pnl = float(row.get("pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        buckets[key]["pnl"] += pnl
        if pnl > 0:
            buckets[key]["wins"] += 1
    for key, b in sorted(buckets.items(), key=lambda x: -x[1]["count"]):
        wr = b["wins"] / b["count"] * 100 if b["count"] else 0
        print(f"{key:20s}  n={int(b['count']):4d}  win_rate={wr:5.1f}%  pnl={b['pnl']:.4f}")
    return 0


def cmd_signal_explainability(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        trades = _fetch_metadata_trades(conn, args.start, args.end)
    finally:
        conn.close()
    limit = int(args.limit or 5)
    shown = 0
    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        expl = dc.get("signal_explanation")
        if not isinstance(expl, dict):
            continue
        print(json.dumps(expl, indent=2))
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        print("No signal_explanation blocks found in snapshots.")
    return 0


def cmd_rule_evaluation(args: argparse.Namespace) -> int:
    conn = _connect()
    if conn is None:
        return 2
    try:
        trades = _fetch_metadata_trades(conn, args.start, args.end)
    finally:
        conn.close()
    from agent.intelligence.rule_evaluation_engine import (
        evaluate_confidence_calibration,
        evaluate_rules_from_trades,
    )

    report = {
        "rules": evaluate_rules_from_trades(trades),
        "calibration": evaluate_confidence_calibration(trades),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


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

    es = sub.add_parser("economic-summary", help="Sharpe, Sortino, drawdown, recovery factor")
    es.add_argument("--start", default=None)
    es.add_argument("--end", default=None)

    mv = sub.add_parser("market-validation", help="Market validation score summary")
    mv.add_argument("--start", default=None)
    mv.add_argument("--end", default=None)

    rb2 = sub.add_parser("regime-benchmarks", help="Performance by regime_benchmark")
    rb2.add_argument("--start", default=None)
    rb2.add_argument("--end", default=None)

    se = sub.add_parser("signal-explainability", help="Sample signal explanation blocks")
    se.add_argument("--start", default=None)
    se.add_argument("--end", default=None)
    se.add_argument("--limit", type=int, default=5)

    re = sub.add_parser("rule-evaluation", help="Per-rule and calibration report")
    re.add_argument("--start", default=None)
    re.add_argument("--end", default=None)

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
        "economic-summary": cmd_economic_summary,
        "market-validation": cmd_market_validation,
        "regime-benchmarks": cmd_regime_benchmarks,
        "signal-explainability": cmd_signal_explainability,
        "rule-evaluation": cmd_rule_evaluation,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
