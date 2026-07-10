#!/usr/bin/env python3
"""Fit confidence calibrator (Beta / Platt / Isotonic) with Brier, ECE, AUC."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _brier(y: Sequence[int], p: Sequence[float]) -> float:
    n = min(len(y), len(p))
    if n == 0:
        return 0.0
    return sum((float(p[i]) - float(y[i])) ** 2 for i in range(n)) / n


def _auc(y: Sequence[int], p: Sequence[float]) -> Optional[float]:
    pairs = sorted(zip(p[: len(y)], y[: len(p)]), key=lambda t: t[0], reverse=True)
    n_pos = sum(y)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    rank_sum = 0.0
    for i, (_, label) in enumerate(pairs, start=1):
        if label:
            rank_sum += i
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _ece(y: Sequence[int], p: Sequence[float], n_bins: int = 10) -> Tuple[float, List[Dict[str, Any]]]:
    n = min(len(y), len(p))
    if n == 0:
        return 0.0, []
    bins: List[List[Tuple[int, float]]] = [[] for _ in range(n_bins)]
    for i in range(n):
        b = min(n_bins - 1, int(float(p[i]) * n_bins))
        bins[b].append((int(y[i]), float(p[i])))
    ece = 0.0
    diagram: List[Dict[str, Any]] = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        mean_p = sum(x[1] for x in bucket) / len(bucket)
        acc = sum(x[0] for x in bucket) / len(bucket)
        weight = len(bucket) / n
        ece += weight * abs(acc - mean_p)
        diagram.append(
            {
                "bin": i,
                "count": len(bucket),
                "mean_predicted": round(mean_p, 4),
                "empirical_rate": round(acc, 4),
            }
        )
    return ece, diagram


def _platt_fit(scores: Sequence[float], y: Sequence[int]) -> Tuple[float, float]:
    """Logistic regression via simple gradient descent."""
    a, b = 0.0, 0.0
    lr = 0.1
    for _ in range(500):
        for i in range(min(len(scores), len(y))):
            z = a * scores[i] + b
            p = 1.0 / (1.0 + math.exp(-max(-20, min(20, z))))
            err = p - y[i]
            a -= lr * err * scores[i]
            b -= lr * err
    return a, b


def _platt_predict(scores: Sequence[float], a: float, b: float) -> List[float]:
    out: List[float] = []
    for s in scores:
        z = a * s + b
        out.append(1.0 / (1.0 + math.exp(-max(-20, min(20, z)))))
    return out


def _beta_mean(scores: Sequence[float], y: Sequence[int]) -> List[float]:
    pos = sum(y)
    neg = len(y) - pos
    alpha = pos + 1
    beta = neg + 1
    denom = alpha + beta
    base = alpha / denom
    return [max(0.01, min(0.99, 0.5 * base + 0.5 * float(s))) for s in scores]


def _pick_method(n: int) -> str:
    if n < 200:
        return "beta"
    if n < 2000:
        return "platt"
    return "isotonic"


def fit_group(
    rows: List[Dict[str, Any]],
    *,
    method: Optional[str] = None,
) -> Dict[str, Any]:
    y = [int(r["y"]) for r in rows]
    raw = [float(r["kappa_raw"]) for r in rows]
    n = len(rows)
    chosen = method or _pick_method(n)

    if chosen == "beta":
        calibrated = _beta_mean(raw, y)
        params: Dict[str, Any] = {"method": "beta"}
    elif chosen == "platt":
        a, b = _platt_fit(raw, y)
        calibrated = _platt_predict(raw, a, b)
        params = {"method": "platt", "a": a, "b": b}
    else:
        try:
            from sklearn.isotonic import IsotonicRegression

            iso = IsotonicRegression(out_of_bounds="clip")
            calibrated = iso.fit_transform(raw, y).tolist()
            params = {"method": "isotonic"}
        except ImportError:
            a, b = _platt_fit(raw, y)
            calibrated = _platt_predict(raw, a, b)
            params = {"method": "platt_fallback", "a": a, "b": b}

    brier_raw = _brier(y, raw)
    brier_cal = _brier(y, calibrated)
    ece, diagram = _ece(y, calibrated)
    auc_raw = _auc(y, raw)
    auc_cal = _auc(y, calibrated)
    improvement = (brier_raw - brier_cal) / brier_raw if brier_raw > 0 else 0.0

    return {
        "method": params["method"],
        "params": params,
        "sample_count": n,
        "brier_raw": round(brier_raw, 6),
        "brier_calibrated": round(brier_cal, 6),
        "brier_improvement_pct": round(improvement * 100, 2),
        "ece": round(ece, 6),
        "auc_raw": round(auc_raw, 4) if auc_raw is not None else None,
        "auc_calibrated": round(auc_cal, 4) if auc_cal is not None else None,
        "reliability_diagram": diagram,
        "acceptance": {
            "ece_lt_0_05": ece < 0.05,
            "brier_improvement_gte_10pct": improvement >= 0.10,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "calibration_dataset.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs" / "signal_recovery" / "calibration_report.json",
    )
    parser.add_argument("--method", choices=["beta", "platt", "isotonic"], default=None)
    args = parser.parse_args()

    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if not rows:
        print("No calibration rows; run build_calibration_dataset.py first", file=sys.stderr)
        return 1

    by_stratum: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = f"{r.get('regime', 'unknown')}|{r.get('thesis_type', 'unknown')}"
        by_stratum[key].append(r)

    strata_reports = {k: fit_group(v, method=args.method) for k, v in by_stratum.items()}
    overall = fit_group(rows, method=args.method)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "strata": strata_reports,
        "frozen_pi0": data.get("frozen_pi0"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(overall, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
