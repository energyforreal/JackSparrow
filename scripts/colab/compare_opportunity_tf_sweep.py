"""Summarize opportunity ensemble exports across timeframes and horizons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SWEEP_TFS: tuple[str, ...] = ("10m", "5m", "15m", "30m", "1h")


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _folder_name(tf: str, horizon_bars: Optional[int]) -> str:
    if horizon_bars is None:
        return f"opportunity_{tf}"
    return f"opportunity_{tf}_h{int(horizon_bars)}"


def _cell_id(tf: str, horizon_bars: Optional[int]) -> str:
    if horizon_bars is None:
        return tf
    return f"{tf}_h{int(horizon_bars)}"


def _row(export_root: Path, tf: str, horizon_bars: Optional[int] = None) -> Dict[str, Any]:
    folder = export_root / _folder_name(tf, horizon_bars)
    meta = _load(folder / "metadata.json") or {}
    eval_rep = _load(folder / "eval_report.json") or meta.get("eval") or {}
    label = _load(folder / "label_report.json") or meta.get("label_gate") or {}
    promo = meta.get("promotion") or {}
    signals = eval_rep.get("signal_expectancy") or {}
    decision = eval_rep.get("decision_rule") or {}
    resolved_horizon = meta.get("horizon_bars", horizon_bars)
    return {
        "resolution": tf,
        "cell": _cell_id(tf, resolved_horizon if resolved_horizon is not None else horizon_bars),
        "present": bool(eval_rep),
        "label_gate_passed": label.get("passed"),
        "tp_cost_ratio": label.get("tp_cost_ratio"),
        "breakeven_win_rate": label.get("breakeven_win_rate"),
        "best_classifier": eval_rep.get("best_classifier"),
        "wf_mean_score": promo.get("wf_mean_score"),
        "wf_positive_share": promo.get("wf_positive_share"),
        "test_score": eval_rep.get("score"),
        "precision_LONG": eval_rep.get("precision_LONG"),
        "precision_SHORT": eval_rep.get("precision_SHORT"),
        "n_LONG": signals.get("LONG_n"),
        "n_SHORT": signals.get("SHORT_n"),
        "LONG_tstat": signals.get("LONG_tstat"),
        "SHORT_tstat": signals.get("SHORT_tstat"),
        "ready_to_promote": promo.get("ready_to_promote", meta.get("ready_to_promote")),
        "promote_reasons": promo.get("reasons") or [],
        "horizon_bars": resolved_horizon,
        "horizon_minutes": meta.get("horizon_minutes"),
        "thresholds": decision.get("thresholds"),
    }


def _label(row: Dict[str, Any]) -> str:
    return str(row.get("cell") or row.get("resolution") or "")


def recommend_pool(rows: List[Dict[str, Any]]) -> str:
    scored = [r for r in rows if r.get("present") and r.get("test_score") is not None]
    if not scored:
        return "no completed exports"
    positive_wf = [r for r in scored if float(r.get("wf_positive_share") or 0.0) > 0.0]
    pool = positive_wf or scored
    best = max(pool, key=lambda r: float(r["test_score"]))
    if all(float(r["test_score"]) <= 0.0 and float(r.get("wf_positive_share") or 0.0) == 0.0 for r in scored):
        return (
            f"all cells match the 10m failure mode (WF pos_share=0, negative test). "
            f"Least-negative test: {_label(best)} score={best['test_score']}. "
            "Treat as problem-definition, not TF choice."
        )
    return (
        f"focus follow-up on {_label(best)} "
        f"(test_score={best['test_score']}, wf_pos={best.get('wf_positive_share')})"
    )


def recommend(rows: List[Dict[str, Any]]) -> str:
    horizons = sorted(
        {
            int(r["horizon_bars"])
            for r in rows
            if r.get("horizon_bars") is not None
        }
    )
    parts: List[str] = []
    for horizon in horizons:
        subset = [r for r in rows if r.get("horizon_bars") == horizon]
        parts.append(f"h{horizon}: {recommend_pool(subset)}")
    overall = recommend_pool(rows)
    if parts:
        parts.append(f"overall: {overall}")
        return " | ".join(parts)
    return overall


def _iter_cells(
    tfs: Iterable[str], horizons: Optional[List[int]]
) -> List[tuple[str, Optional[int]]]:
    if horizons:
        return [(tf, int(h)) for tf in tfs for h in horizons]
    return [(tf, None) for tf in tfs]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=Path("export"),
        help="Directory containing opportunity_{tf}/ or opportunity_{tf}_h{bars}/ folders",
    )
    parser.add_argument(
        "--tfs",
        nargs="*",
        default=list(SWEEP_TFS),
    )
    parser.add_argument(
        "--horizons",
        nargs="*",
        type=int,
        default=None,
        help="If set, read opportunity_{tf}_h{bars} for each TF x horizon",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Summary JSON path (default: export-dir/opportunity_tf_sweep_summary.json)",
    )
    args = parser.parse_args()
    cells = _iter_cells(args.tfs, args.horizons)
    rows = [_row(args.export_dir, tf, horizon) for tf, horizon in cells]
    out_path = args.output or (args.export_dir / "opportunity_tf_sweep_summary.json")
    payload = {
        "rows": rows,
        "recommendation": recommend(rows),
        "recommendations_by_horizon": {
            str(h): recommend_pool([r for r in rows if r.get("horizon_bars") == h])
            for h in sorted({int(r["horizon_bars"]) for r in rows if r.get("horizon_bars") is not None})
        },
    }
    args.export_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    headers = (
        "cell",
        "gate",
        "tp/cost",
        "best",
        "wf_mean",
        "wf_pos",
        "test",
        "pL",
        "pS",
        "promote",
    )
    print("  ".join(f"{h:>12s}" for h in headers))
    for row in rows:
        name = _label(row)
        if not row["present"]:
            print(f"{name:>12s}  missing")
            continue
        print(
            f"{name:>12s}  "
            f"{str(row['label_gate_passed']):>12s}  "
            f"{float(row['tp_cost_ratio'] or 0):>12.2f}  "
            f"{str(row['best_classifier'] or ''):>12s}  "
            f"{float(row['wf_mean_score'] or 0):>+12.6f}  "
            f"{float(row['wf_positive_share'] or 0):>12.2f}  "
            f"{float(row['test_score'] or 0):>+12.6f}  "
            f"{float(row['precision_LONG'] or 0):>12.3f}  "
            f"{float(row['precision_SHORT'] or 0):>12.3f}  "
            f"{str(row['ready_to_promote']):>12s}"
        )
    print(payload["recommendation"])
    print("wrote", out_path)


if __name__ == "__main__":
    main()
