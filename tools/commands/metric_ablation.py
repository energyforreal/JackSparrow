#!/usr/bin/env python3
"""Metric ablation — LOO logistic regression + policy module disable replay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.log_parser import load_telemetry  # noqa: E402


METRICS = (
    "epsilon_proxy",
    "kappa_raw",
    "q",
    "A",
    "trade_score",
    "conviction",
    "hypothesis_margin",
)


def _rows_from_telemetry(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in load_telemetry(path):
        latent = r.get("latent") if isinstance(r.get("latent"), dict) else {}
        scores = r.get("scores") if isinstance(r.get("scores"), dict) else {}
        y = 1 if str(r.get("terminal_cause")) == "executed" else 0
        row = {
            "epsilon_proxy": latent.get("epsilon_proxy"),
            "kappa_raw": scores.get("conviction") or r.get("confidence"),
            "q": latent.get("q_composite"),
            "A": latent.get("A_composite"),
            "trade_score": r.get("trade_score"),
            "conviction": scores.get("conviction") or r.get("confidence"),
            "hypothesis_margin": r.get("hypothesis_margin"),
            "y": y,
        }
        if all(row.get(m) is not None for m in METRICS[:4]):
            out.append(row)
    return out


def _sigmoid(z: float) -> float:
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _logit_fit(
    X: List[List[float]],
    y: List[int],
    *,
    steps: int = 400,
    lr: float = 0.05,
) -> List[float]:
    n_feat = len(X[0]) if X else 0
    w = [0.0] * n_feat
    b = 0.0
    for _ in range(steps):
        for i in range(len(X)):
            z = b + sum(w[j] * X[i][j] for j in range(n_feat))
            p = _sigmoid(z)
            err = p - y[i]
            for j in range(n_feat):
                w[j] -= lr * err * X[i][j]
            b -= lr * err
    return w + [b]


def _predict(X: List[List[float]], coeffs: List[float]) -> List[float]:
    n_feat = len(coeffs) - 1
    b = coeffs[-1]
    out: List[float] = []
    for row in X:
        z = b + sum(coeffs[j] * row[j] for j in range(n_feat))
        out.append(_sigmoid(z))
    return out


def _auc(y: Sequence[int], p: Sequence[float]) -> float:
    pairs = sorted(zip(p, y), key=lambda t: t[0], reverse=True)
    n_pos = sum(y)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = sum(i + 1 for i, (_, label) in enumerate(pairs) if label)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _brier(y: Sequence[int], p: Sequence[float]) -> float:
    return sum((p[i] - y[i]) ** 2 for i in range(len(y))) / max(len(y), 1)


def _corr(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    return num / (da * db) if da and db else 0.0


def loo_ablation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    y = [int(r["y"]) for r in rows]
    X_full = [[float(r[m]) for m in METRICS] for r in rows]
    full_coeffs = _logit_fit(X_full, y)
    full_pred = _predict(X_full, full_coeffs)
    base_auc = _auc(y, full_pred)
    base_brier = _brier(y, full_pred)

    results: List[Dict[str, Any]] = []
    for drop_idx, metric in enumerate(METRICS):
        keep = [i for i in range(len(METRICS)) if i != drop_idx]
        X = [[row[i] for i in keep] for row in X_full]
        coeffs = _logit_fit(X, y)
        pred = _predict(X, coeffs)
        delta_auc = _auc(y, pred) - base_auc
        delta_brier = _brier(y, pred) - base_brier
        corrs = {
            other: _corr([r[metric] for r in rows], [r[other] for r in rows])
            for other in METRICS
            if other != metric
        }
        max_corr = max((abs(v) for v in corrs.values()), default=0.0)
        redundant = abs(delta_auc) < 0.005 and max_corr > 0.7
        results.append(
            {
                "removed_metric": metric,
                "delta_auc": round(delta_auc, 6),
                "delta_brier": round(delta_brier, 6),
                "max_abs_corr": round(max_corr, 4),
                "redundant_candidate": redundant,
                "recommendation": "remove" if redundant else "keep",
            }
        )
    return {
        "baseline_auc": round(base_auc, 4),
        "baseline_brier": round(base_brier, 6),
        "loo_results": results,
    }


def policy_module_ablation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Frequency deltas when terminal cause implicates a module."""
    n = len(rows) or 1
    by_cause: Dict[str, int] = {}
    for r in rows:
        tc = str(r.get("terminal_cause") or "unknown")
        by_cause[tc] = by_cause.get(tc, 0) + 1

    modules = {
        "conviction_floor": "conviction",
        "entry_quality_veto": "quality",
        "gate5": "g5",
        "trade_score_hard_veto": "policy",
    }
    module_impact = {}
    for name, cause in modules.items():
        blocked = by_cause.get(cause, 0)
        module_impact[name] = {
            "blocked_count": blocked,
            "blocked_rate": round(blocked / n, 4),
            "note": f"Observed terminal_cause={cause} in telemetry",
        }
    return module_impact


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Metric Ablation Report",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Statistical LOO Ablation",
        "",
        f"- Baseline AUC: {report['statistical']['baseline_auc']}",
        f"- Baseline Brier: {report['statistical']['baseline_brier']}",
        "",
        "| Removed | ΔAUC | ΔBrier | max|corr| | Recommendation |",
        "|---------|------|--------|----------|----------------|",
    ]
    for row in report["statistical"]["loo_results"]:
        lines.append(
            f"| {row['removed_metric']} | {row['delta_auc']} | {row['delta_brier']} | "
            f"{row['max_abs_corr']} | {row['recommendation']} |"
        )
    lines.extend(["", "## Policy Module Impact (telemetry)", ""])
    for name, data in report["policy_modules"].items():
        lines.append(
            f"- **{name}**: blocked {data['blocked_count']} "
            f"({data['blocked_rate']*100:.1f}%) — {data['note']}"
        )
    lines.extend(
        [
            "",
            "## Gate",
            "",
            "Do not proceed to Phase 7 latent policy refactor until this report is reviewed.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "ablation_report.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "ablation_report.md",
    )
    args = parser.parse_args()

    raw_rows = load_telemetry(args.telemetry)
    stat_rows = _rows_from_telemetry(args.telemetry)
    if len(stat_rows) < 20:
        print(f"Warning: only {len(stat_rows)} rows for LOO; results may be noisy", file=sys.stderr)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "telemetry_rows": len(raw_rows),
        "statistical": loo_ablation(stat_rows) if stat_rows else {"loo_results": []},
        "policy_modules": policy_module_ablation(raw_rows),
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.out_md.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
