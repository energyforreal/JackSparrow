#!/usr/bin/env python3
"""Decision telemetry attribution — funnel, correlation, latent buckets."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402


def _nested(row: Dict[str, Any], *keys: str) -> Any:
    cur: Any = row
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den_x = math.sqrt(sum((xs[i] - mx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ys[i] - my) ** 2 for i in range(n)))
    if den_x < 1e-12 or den_y < 1e-12:
        return None
    return num / (den_x * den_y)


def _rank(vals: Sequence[float]) -> List[float]:
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    return _pearson(_rank(list(xs[:n])), _rank(list(ys[:n])))


def gate_funnel(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Survival rates per gate layer from v3 telemetry."""
    cycles = [r for r in rows if r.get("event") in ("decision_cycle", None, "")]
    if not cycles:
        cycles = list(rows)

    n = len(cycles) or 1
    g1 = g2 = g3 = g4 = g5 = executed = 0
    terminal = Counter()

    for r in cycles:
        gates = r.get("gates") if isinstance(r.get("gates"), dict) else {}
        if gates:
            if gates.get("g1_raw_long") or gates.get("g1_raw_short"):
                g1 += 1
            if gates.get("g2_pass"):
                g2 += 1
            if gates.get("g3_pass"):
                g3 += 1
            if gates.get("g4_pass"):
                g4 += 1
            if gates.get("g5_pass"):
                g5 += 1
        else:
            fl = _nested(r, "extra", "final_long")
            fs = _nested(r, "extra", "final_short")
            rl = _nested(r, "extra", "raw_long")
            rs = _nested(r, "extra", "raw_short")
            if rl or rs:
                g1 += 1
            if fl or fs:
                g5 += 1
                if g2 == 0:
                    g2 = g3 = g4 = g1
                else:
                    g2 += 1
                    g3 += 1
                    g4 += 1

        tc = str(r.get("terminal_cause") or "unknown")
        terminal[tc] += 1
        if tc == "executed":
            executed += 1

    return {
        "sample_count": len(cycles),
        "gate_survival": {
            "g1_raw_signal_rate": round(g1 / n, 4),
            "g2_pass_rate": round(g2 / n, 4),
            "g3_pass_rate": round(g3 / n, 4),
            "g4_pass_rate": round(g4 / n, 4),
            "g5_pass_rate": round(g5 / n, 4),
            "executed_rate": round(executed / n, 4),
        },
        "terminal_cause_histogram": dict(terminal.most_common()),
        "dominant_reject_layer": terminal.most_common(1)[0][0] if terminal else None,
    }


def correlation_matrix(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Pearson/Spearman matrix over decision metrics."""
    fields = {
        "trade_score": lambda r: _float_or_none(r.get("trade_score")),
        "conviction": lambda r: _float_or_none(_nested(r, "scores", "conviction")),
        "policy_confidence": lambda r: _float_or_none(
            r.get("confidence") or _nested(r, "scores", "policy_confidence")
        ),
        "expected_return": lambda r: _float_or_none(r.get("expected_return")),
        "epsilon_proxy": lambda r: _float_or_none(_nested(r, "latent", "epsilon_proxy")),
        "hypothesis_margin": lambda r: _float_or_none(r.get("hypothesis_margin")),
        "collapse_rate": lambda r: _float_or_none(r.get("v43_collapse_rate")),
    }

    series: Dict[str, List[float]] = {k: [] for k in fields}
    for r in rows:
        for name, fn in fields.items():
            v = fn(r)
            if v is not None:
                series[name].append(v)

    keys = [k for k, vals in series.items() if len(vals) >= 5]
    pearson: Dict[str, Dict[str, Optional[float]]] = {}
    spearman: Dict[str, Dict[str, Optional[float]]] = {}
    for a in keys:
        pearson[a] = {}
        spearman[a] = {}
        for b in keys:
            n = min(len(series[a]), len(series[b]))
            pearson[a][b] = _pearson(series[a][:n], series[b][:n])
            spearman[a][b] = _spearman(series[a][:n], series[b][:n])

    return {
        "field_counts": {k: len(series[k]) for k in keys},
        "pearson": pearson,
        "spearman": spearman,
    }


def _regime_bucket(row: Dict[str, Any]) -> str:
    for key in ("market_type", "regime"):
        v = row.get(key)
        if v:
            return str(v).lower()
    extra = row.get("extra")
    if isinstance(extra, dict):
        for key in ("market_type", "regime"):
            v = extra.get(key)
            if v:
                return str(v).lower()
    return "unknown"


def latent_buckets(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Conditional rejection rate by regime / market_type proxy."""
    by_regime: Dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()

    for r in rows:
        bucket = _regime_bucket(r)
        totals[bucket] += 1
        tc = str(r.get("terminal_cause") or "unknown")
        by_regime[bucket][tc] += 1

    out: Dict[str, Any] = {}
    for bucket, hist in by_regime.items():
        total = totals[bucket] or 1
        reject = sum(v for k, v in hist.items() if k not in ("executed",))
        out[bucket] = {
            "count": total,
            "rejection_rate": round(reject / total, 4),
            "terminal_causes": dict(hist),
        }
    return {"buckets": out, "total_rows": sum(totals.values())}


def run_attribution(
    *,
    telemetry_path: Path,
    hours: float = 168.0,
    out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    rows = load_telemetry(telemetry_path)
    rows = filter_since(rows, hours)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "source": str(telemetry_path),
        "funnel": gate_funnel(rows),
        "correlation": correlation_matrix(rows),
        "latent_buckets": latent_buckets(rows),
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_attr = sub.add_parser("attribution", help="Gate funnel + terminal cause histogram")
    p_attr.add_argument("--hours", type=float, default=168.0)
    p_attr.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    p_attr.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "attribution_report.json",
    )

    p_corr = sub.add_parser("correlation", help="Metric correlation matrix")
    p_corr.add_argument("--hours", type=float, default=168.0)
    p_corr.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "decision_telemetry.ndjson",
    )

    p_lat = sub.add_parser("latent-buckets", help="Rejection by regime bucket")
    p_lat.add_argument("--hours", type=float, default=168.0)
    p_lat.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "decision_telemetry.ndjson",
    )

    args = parser.parse_args()
    telemetry = args.telemetry

    if args.command == "attribution":
        report = run_attribution(
            telemetry_path=telemetry,
            hours=args.hours,
            out_path=args.out,
        )
        print(json.dumps(report["funnel"], indent=2))
        print(f"\nWrote {args.out}")
        return 0

    rows = filter_since(load_telemetry(telemetry), args.hours)
    if args.command == "correlation":
        print(json.dumps(correlation_matrix(rows), indent=2))
        return 0
    if args.command == "latent-buckets":
        print(json.dumps(latent_buckets(rows), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
