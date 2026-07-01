"""Rule-level evaluation with interaction analysis and FP/FN classification."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

_GATE_CATEGORIES = ("trend", "structure", "breakout", "liquidity", "volatility", "risk")


def _won(pnl: Any) -> bool:
    try:
        return float(pnl or 0) > 0
    except (TypeError, ValueError):
        return False


def _extract_categories(snapshot: Dict[str, Any]) -> Dict[str, bool]:
    dc = snapshot.get("decision_context") if isinstance(snapshot.get("decision_context"), dict) else {}
    ge = dc.get("gate_evaluation") if isinstance(dc.get("gate_evaluation"), dict) else {}
    cats = ge.get("categories")
    if isinstance(cats, dict):
        return {str(k): bool(v) for k, v in cats.items()}
    rb = dc.get("rule_based_pipeline") if isinstance(dc.get("rule_based_pipeline"), dict) else {}
    sg = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
    cats = sg.get("categories")
    if isinstance(cats, dict):
        return {str(k): bool(v) for k, v in cats.items()}
    return {}


def _combo_key(cats: Dict[str, bool], names: Tuple[str, ...]) -> str:
    parts = [n for n in names if cats.get(n)]
    return "+".join(sorted(parts)) if parts else "none"


def evaluate_rules_from_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-rule and interaction stats from trade_outcomes rows."""
    per_rule: Dict[str, Dict[str, Any]] = {
        cat: {"passed_wins": 0, "passed_losses": 0, "failed_wins": 0, "failed_losses": 0}
        for cat in _GATE_CATEGORIES
    }
    interactions: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"wins": 0, "losses": 0, "count": 0, "total_pnl": 0.0}
    )
    false_positives = 0
    false_negatives = 0

    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else row
        if not isinstance(meta, dict):
            continue
        pnl = row.get("pnl")
        if pnl is None:
            outcome = meta.get("outcome") if isinstance(meta.get("outcome"), dict) else {}
            pnl = outcome.get("pnl_usd")
        won = _won(pnl)
        cats = _extract_categories(meta)

        for cat in _GATE_CATEGORIES:
            passed = cats.get(cat, False)
            bucket = per_rule[cat]
            if passed and won:
                bucket["passed_wins"] += 1
            elif passed and not won:
                bucket["passed_losses"] += 1
                false_positives += 1
            elif not passed and won:
                bucket["failed_wins"] += 1
            elif not passed and not won:
                bucket["failed_losses"] += 1

        for r in (2, 3):
            for combo in combinations(_GATE_CATEGORIES, r):
                if not all(cats.get(c) for c in combo):
                    continue
                key = _combo_key(cats, combo)
                cell = interactions[key]
                cell["count"] += 1
                cell["total_pnl"] += float(pnl or 0)
                if won:
                    cell["wins"] += 1
                else:
                    cell["losses"] += 1

    rule_stats: Dict[str, Any] = {}
    for cat, bucket in per_rule.items():
        passed_total = bucket["passed_wins"] + bucket["passed_losses"]
        failed_total = bucket["failed_wins"] + bucket["failed_losses"]
        rule_stats[cat] = {
            "win_rate_when_passed": (
                bucket["passed_wins"] / passed_total if passed_total else None
            ),
            "win_rate_when_failed": (
                bucket["failed_wins"] / failed_total if failed_total else None
            ),
            "false_positive_rate": (
                bucket["passed_losses"] / passed_total if passed_total else None
            ),
            "false_negative_rate": (
                bucket["failed_wins"] / failed_total if failed_total else None
            ),
            "passed_count": passed_total,
            "failed_count": failed_total,
        }

    interaction_list = []
    for key, cell in sorted(interactions.items(), key=lambda x: -x[1]["count"]):
        n = cell["count"]
        interaction_list.append(
            {
                "combo": key,
                "trade_count": n,
                "win_rate": cell["wins"] / n if n else 0.0,
                "avg_pnl": cell["total_pnl"] / n if n else 0.0,
            }
        )

    return {
        "per_rule": rule_stats,
        "interactions": interaction_list[:50],
        "false_positive_trades": false_positives,
        "false_negative_signals": false_negatives,
        "trade_count": len(trades),
    }


def evaluate_confidence_calibration(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bucket structural confidence vs actual win rate."""
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})

    for row in trades:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else row
        if not isinstance(meta, dict):
            continue
        dc = meta.get("decision_context") if isinstance(meta.get("decision_context"), dict) else {}
        conf = dc.get("structural_confidence") or dc.get("confidence")
        try:
            c = float(conf or 0.5)
            if c > 1.0:
                c = c / 100.0
        except (TypeError, ValueError):
            c = 0.5
        low = int(c * 10) * 10
        label = f"{low}-{low + 10}"
        pnl = row.get("pnl")
        if pnl is None:
            outcome = meta.get("outcome") if isinstance(meta.get("outcome"), dict) else {}
            pnl = outcome.get("pnl_usd")
        buckets[label]["total"] += 1
        if _won(pnl):
            buckets[label]["wins"] += 1

    rows = []
    errors: List[float] = []
    for label in sorted(buckets.keys()):
        b = buckets[label]
        if b["total"] == 0:
            continue
        actual_wr = b["wins"] / b["total"]
        try:
            mid = (int(label.split("-")[0]) + int(label.split("-")[1])) / 200.0
        except (ValueError, IndexError):
            mid = 0.5
        delta = abs(mid - actual_wr)
        errors.append(delta)
        rows.append(
            {
                "bucket": label,
                "actual_win_rate": round(actual_wr, 4),
                "expected_mid": round(mid, 4),
                "delta_pp": round(delta * 100, 2),
                "count": b["total"],
            }
        )

    return {
        "buckets": rows,
        "calibration_error": round(sum(errors) / len(errors), 4) if errors else None,
    }
