#!/usr/bin/env python3
"""Evaluate quantitative readiness gates between implementation phases."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    except ImportError:
        return None
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        return psycopg2.connect(_normalize_psycopg_url(url))
    except Exception:
        return None


GATES: Dict[str, Dict[str, Any]] = {
    "0_to_1a": {
        "description": "Phase 0 → 1a: snapshot integrity",
        "min_snapshot_integrity_pct": 95.0,
    },
    "1a_to_1b": {
        "description": "Phase 1a → 1b: market validation coverage",
        "min_signal_cycles": 100,
        "min_mean_validation_score": 70.0,
        "min_validation_coverage_pct": 100.0,
    },
    "1b_to_2": {
        "description": "Phase 1b → 2: rule_based cohort baseline",
        "min_trades": 50,
        "min_profit_factor": 1.0,
        "min_expectancy": 0.0,
        "min_signal_quality_pass_pct": 60.0,
    },
    "2_to_2b": {
        "description": "Phase 2 → 2b: monitoring persistence",
        "min_trades": 30,
        "min_monitoring_coverage_pct": 90.0,
        "min_timeline_coverage_pct": 80.0,
    },
    "2b_to_3": {
        "description": "Phase 2b → 3: TLE replay agreement",
        "min_overall_agreement": 0.80,
        "min_exit_agreement": 0.75,
        "min_opportunity_precision": 0.65,
        "min_trades": 30,
    },
    "3_to_4": {
        "description": "Phase 3 → 4: live TLE vs baseline",
        "min_trades": 50,
        "max_profit_factor_degradation_pct": 15.0,
    },
    "4_to_5": {
        "description": "Phase 4 → 5: attribution complete",
        "min_trades": 100,
        "min_post_trade_coverage_pct": 100.0,
        "max_calibration_error": 0.15,
    },
    "5_to_portfolio": {
        "description": "Phase 5 → portfolio layer",
        "min_trades": 100,
        "min_profit_factor": 1.2,
        "min_expectancy": 0.0,
        "min_sharpe": 0.5,
        "max_drawdown_pct": 15.0,
    },
    "v1_to_v2_snapshot": {
        "description": "Snapshot v2: entry_quality coverage",
        "min_entry_quality_coverage_pct": 95.0,
        "min_trades": 10,
    },
    "v2_events": {
        "description": "Decision event stream coverage",
        "min_decision_event_coverage_pct": 90.0,
        "min_trades": 10,
    },
    "v2_causality": {
        "description": "Lifecycle exits have causal chain",
        "min_causal_links": 2,
        "min_lifecycle_trades": 5,
    },
    "v2_mfe_mae": {
        "description": "MFE/MAE excursions at close",
        "min_excursion_coverage_pct": 90.0,
        "min_trades": 10,
    },
    "v2_reject_labels": {
        "description": "Rejected entry forward labels",
        "min_labeled_rejects": 50,
    },
}


def _fetch_trades(conn, start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
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
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT pnl, metadata FROM trade_outcomes WHERE 1=1 {where} ORDER BY closed_at",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def _profit_factor(trades: List[Dict[str, Any]]) -> float:
    wins = losses = 0.0
    for t in trades:
        try:
            p = float(t.get("pnl") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            wins += p
        elif p < 0:
            losses += abs(p)
    return wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)


def _expectancy(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    total = sum(float(t.get("pnl") or 0) for t in trades)
    return total / len(trades)


def _snapshot_integrity(conn) -> float:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM trade_outcomes")
        total = int(cur.fetchone()[0])
        if total == 0:
            return 100.0
        cur.execute(
            """
            SELECT COUNT(*) FROM trade_outcomes
            WHERE metadata->'decision_context'->'rule_based_pipeline' IS NOT NULL
            """
        )
        with_rb = int(cur.fetchone()[0])
    return with_rb / total * 100.0


def evaluate_gate(gate_id: str, *, start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    """Evaluate a single phase transition gate."""
    spec = GATES.get(gate_id)
    if not spec:
        return {"gate_id": gate_id, "pass": False, "error": "unknown_gate"}

    conn = _connect()
    checks: List[Dict[str, Any]] = []
    passed = True

    if gate_id == "0_to_1a":
        if conn is None:
            return {"gate_id": gate_id, "pass": False, "error": "no_db"}
        pct = _snapshot_integrity(conn)
        ok = pct >= float(spec["min_snapshot_integrity_pct"])
        checks.append({"check": "snapshot_integrity_pct", "value": pct, "pass": ok})
        passed = ok
        conn.close()
        return {"gate_id": gate_id, "pass": passed, "checks": checks, **spec}

    if conn is None:
        return {"gate_id": gate_id, "pass": False, "error": "no_db", **spec}

    trades = _fetch_trades(conn, start, end)
    conn.close()

    if gate_id == "1b_to_2":
        pf = _profit_factor(trades)
        exp = _expectancy(trades)
        n = len(trades)
        ok_n = n >= int(spec["min_trades"])
        ok_pf = pf >= float(spec["min_profit_factor"]) or exp >= float(spec["min_expectancy"])
        checks.extend(
            [
                {"check": "trade_count", "value": n, "pass": ok_n},
                {"check": "profit_factor", "value": round(pf, 4), "pass": pf >= 1.0 or exp >= 0},
            ]
        )
        passed = ok_n and ok_pf

    elif gate_id == "2_to_2b":
        n = len(trades)
        mon = sum(
            1
            for t in trades
            if isinstance((t.get("metadata") or {}).get("position_monitoring"), list)
            and (t.get("metadata") or {})["position_monitoring"]
        )
        tl = sum(
            1
            for t in trades
            if isinstance((t.get("metadata") or {}).get("market_structure_timeline"), list)
            and (t.get("metadata") or {})["market_structure_timeline"]
        )
        mon_pct = mon / n * 100 if n else 0
        tl_pct = tl / n * 100 if n else 0
        ok = (
            n >= int(spec["min_trades"])
            and mon_pct >= float(spec["min_monitoring_coverage_pct"])
            and tl_pct >= float(spec["min_timeline_coverage_pct"])
        )
        checks = [
            {"check": "trade_count", "value": n, "pass": n >= int(spec["min_trades"])},
            {"check": "monitoring_coverage_pct", "value": round(mon_pct, 2), "pass": mon_pct >= 90},
            {"check": "timeline_coverage_pct", "value": round(tl_pct, 2), "pass": tl_pct >= 80},
        ]
        passed = ok

    elif gate_id == "2b_to_3":
        report_path = ROOT / "data" / "experiments" / "tle_agreement_latest.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            oa = float(report.get("overall_agreement") or 0)
            ea = float(report.get("exit_agreement_rate") or 0)
            op = float(report.get("opportunity_precision") or 0)
            passed = (
                oa >= float(spec["min_overall_agreement"])
                and ea >= float(spec["min_exit_agreement"])
                and op >= float(spec["min_opportunity_precision"])
            )
            checks = [
                {"check": "overall_agreement", "value": oa, "pass": oa >= 0.80},
                {"check": "exit_agreement_rate", "value": ea, "pass": ea >= 0.75},
                {"check": "opportunity_precision", "value": op, "pass": op >= 0.65},
            ]
        else:
            passed = False
            checks = [{"check": "tle_agreement_report", "value": None, "pass": False}]

    elif gate_id == "4_to_5":
        n = len(trades)
        assessed = sum(
            1
            for t in trades
            if isinstance((t.get("metadata") or {}).get("post_trade_assessment"), dict)
        )
        cov = assessed / n * 100 if n else 0
        from agent.intelligence.rule_evaluation_engine import evaluate_confidence_calibration

        cal = evaluate_confidence_calibration(trades)
        cal_err = cal.get("calibration_error")
        ok_cal = cal_err is None or float(cal_err) < float(spec["max_calibration_error"])
        passed = n >= int(spec["min_trades"]) and cov >= 100.0 and ok_cal
        checks = [
            {"check": "post_trade_coverage_pct", "value": round(cov, 2), "pass": cov >= 100},
            {"check": "calibration_error", "value": cal_err, "pass": ok_cal},
        ]

    elif gate_id == "v1_to_v2_snapshot":
        n = len(trades)
        eq_n = sum(
            1
            for t in trades
            if isinstance(
                ((t.get("metadata") or {}).get("decision_context") or {}).get(
                    "entry_quality"
                ),
                dict,
            )
        )
        cov = eq_n / n * 100 if n else 0
        passed = n >= int(spec["min_trades"]) and cov >= float(
            spec["min_entry_quality_coverage_pct"]
        )
        checks = [
            {"check": "trade_count", "value": n, "pass": n >= int(spec["min_trades"])},
            {
                "check": "entry_quality_coverage_pct",
                "value": round(cov, 2),
                "pass": cov >= float(spec["min_entry_quality_coverage_pct"]),
            },
        ]

    elif gate_id == "v2_events":
        n = len(trades)
        with_events = sum(
            1
            for t in trades
            if int((t.get("metadata") or {}).get("decision_event_count") or 0) > 0
        )
        cov = with_events / n * 100 if n else 0
        passed = n >= int(spec["min_trades"]) and cov >= float(
            spec["min_decision_event_coverage_pct"]
        )
        checks = [
            {"check": "trade_count", "value": n, "pass": n >= int(spec["min_trades"])},
            {
                "check": "decision_event_coverage_pct",
                "value": round(cov, 2),
                "pass": cov >= float(spec["min_decision_event_coverage_pct"]),
            },
        ]

    elif gate_id == "v2_causality":
        lifecycle = [
            t
            for t in trades
            if str(
                ((t.get("metadata") or {}).get("outcome") or {}).get("exit_reason") or ""
            )
            == "lifecycle_exit"
        ]
        linked = 0
        for t in lifecycle:
            graph = (t.get("metadata") or {}).get("causality_graph") or {}
            edges = graph.get("edges") if isinstance(graph, dict) else []
            if isinstance(edges, list) and len(edges) >= int(spec["min_causal_links"]):
                linked += 1
        n = len(lifecycle)
        passed = n >= int(spec["min_lifecycle_trades"]) and (
            linked == n if n else False
        )
        checks = [
            {"check": "lifecycle_trade_count", "value": n, "pass": n >= 5},
            {"check": "causal_chain_count", "value": linked, "pass": linked == n if n else False},
        ]

    elif gate_id == "v2_mfe_mae":
        n = len(trades)
        exc_n = sum(
            1
            for t in trades
            if isinstance(
                ((t.get("metadata") or {}).get("outcome") or {}).get("excursions"),
                dict,
            )
        )
        cov = exc_n / n * 100 if n else 0
        passed = n >= int(spec["min_trades"]) and cov >= float(
            spec["min_excursion_coverage_pct"]
        )
        checks = [
            {"check": "trade_count", "value": n, "pass": n >= int(spec["min_trades"])},
            {
                "check": "excursion_coverage_pct",
                "value": round(cov, 2),
                "pass": cov >= float(spec["min_excursion_coverage_pct"]),
            },
        ]

    elif gate_id == "v2_reject_labels":
        conn2 = _connect()
        labeled = 0
        if conn2 is not None:
            with conn2.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM entry_decision_labels")
                labeled = int(cur.fetchone()[0])
            conn2.close()
        passed = labeled >= int(spec["min_labeled_rejects"])
        checks = [
            {
                "check": "labeled_rejects",
                "value": labeled,
                "pass": passed,
            }
        ]

    else:
        checks.append({"check": "manual", "value": len(trades), "pass": len(trades) > 0})
        passed = len(trades) >= int(spec.get("min_trades", 1))

    return {
        "gate_id": gate_id,
        "pass": passed,
        "checks": checks,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in spec.items() if k != "description"},
        "description": spec.get("description"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase readiness gate evaluator")
    parser.add_argument("--gate", required=True, choices=list(GATES.keys()))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = evaluate_gate(args.gate, start=args.start, end=args.end)
    text = json.dumps(result, indent=2)
    print(text)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")

    registry_path = ROOT / "data" / "experiments" / "readiness_gates.jsonl"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result) + "\n")

    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
