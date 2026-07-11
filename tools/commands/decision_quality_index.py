#!/usr/bin/env python3
"""Decision Quality Index (DQI) — composite program health score."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.signal_recovery.decision_evidence import provenance_report  # noqa: E402
from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402

BASELINE_COMMIT = "0503847"
WEIGHTS = {
    "thesis_ml_agreement": 0.20,
    "replay_ev": 0.25,
    "shadow_disagreement_ev": 0.15,
    "no_rule_fired_rate": 0.20,
    "regime_stability": 0.10,
    "calibration": 0.10,
}
MIN_CALIBRATION_SAMPLES = 100


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, score))


def _score_agreement(rate: Optional[float]) -> Dict[str, Any]:
    if rate is None:
        return {"score": None, "raw": None, "status": "missing"}
    # 100% agreement on HOLD-heavy windows is expected; score high when stable.
    score = _clamp(rate * 100.0)
    return {"score": round(score, 2), "raw": rate, "status": "ok"}


def _score_replay_ev(ev_pct: Optional[float]) -> Dict[str, Any]:
    if ev_pct is None:
        return {"score": None, "raw": None, "status": "missing"}
    # Map EV: +0.5% -> 100, 0% -> 50, -0.5% -> 0
    score = _clamp(50.0 + float(ev_pct) * 100.0)
    return {"score": round(score, 2), "raw": ev_pct, "status": "ok"}


def _score_shadow_ev(shadow_pnl: Optional[float], prod_pnl: Optional[float]) -> Dict[str, Any]:
    if shadow_pnl is None or prod_pnl is None:
        return {"score": None, "raw": None, "status": "missing"}
    delta = float(shadow_pnl) - float(prod_pnl)
    score = _clamp(50.0 + delta * 500.0)
    return {
        "score": round(score, 2),
        "raw": {"shadow_pnl_proxy": shadow_pnl, "production_pnl_proxy": prod_pnl, "delta": delta},
        "status": "ok",
    }


def _score_no_rule_fired(b4_rate: Optional[float]) -> Dict[str, Any]:
    if b4_rate is None:
        return {"score": None, "raw": None, "status": "missing"}
    # Lower B4 rate among ML-pass cycles is better.
    score = _clamp((1.0 - float(b4_rate)) * 100.0)
    return {"score": round(score, 2), "raw": b4_rate, "status": "ok"}


def _score_regime_stability(flip_rate: Optional[float]) -> Dict[str, Any]:
    if flip_rate is None:
        return {"score": None, "raw": None, "status": "missing"}
    # Lower flip rate -> higher stability score.
    score = _clamp((1.0 - min(1.0, float(flip_rate) * 5.0)) * 100.0)
    return {"score": round(score, 2), "raw": flip_rate, "status": "ok"}


def _score_measurement_coverage(frac: Optional[float]) -> Dict[str, Any]:
    if frac is None:
        return {"score": None, "raw": None, "status": "missing", "blended": False}
    score = _clamp(float(frac) * 100.0)
    return {"score": round(score, 2), "raw": frac, "status": "ok", "blended": False}


def _score_calibration(ece: Optional[float], n: int) -> Dict[str, Any]:
    if n < MIN_CALIBRATION_SAMPLES or ece is None:
        return {
            "score": None,
            "raw": {"ece": ece, "n": n},
            "status": "insufficient_data",
        }
    score = _clamp((1.0 - min(1.0, float(ece) * 10.0)) * 100.0)
    return {"score": round(score, 2), "raw": {"ece": ece, "n": n}, "status": "ok"}


def _load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_rolling_replay() -> Optional[Dict[str, Any]]:
    rolling_root = ROOT / "data" / "investigation" / "rolling"
    if not rolling_root.is_dir():
        return None
    dates = sorted([p for p in rolling_root.iterdir() if p.is_dir()], reverse=True)
    for d in dates:
        candidate = d / "counterfactual_replay_168h.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


def compute_dqi(
    *,
    shadow_report: Optional[Dict[str, Any]] = None,
    replay_report: Optional[Dict[str, Any]] = None,
    stability_report: Optional[Dict[str, Any]] = None,
    calibration_report: Optional[Dict[str, Any]] = None,
    thesis_miss_report: Optional[Dict[str, Any]] = None,
    coverage_report: Optional[Dict[str, Any]] = None,
    telemetry_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    components: Dict[str, Dict[str, Any]] = {}

    shadow = shadow_report or {}
    components["thesis_ml_agreement"] = _score_agreement(shadow.get("agreement_rate"))

    replay = replay_report or {}
    current_ev = (replay.get("scenario_table") or {}).get("current") or {}
    components["replay_ev"] = _score_replay_ev(current_ev.get("ev_pct"))

    components["shadow_disagreement_ev"] = _score_shadow_ev(
        shadow.get("shadow_pnl_proxy"),
        shadow.get("production_pnl_proxy"),
    )

    miss = thesis_miss_report
    cov = coverage_report or (miss or {}).get("coverage") or {}
    b4 = int(cov.get("total_b4") or (miss or {}).get("b4_total") or 0)
    hi = int(cov.get("high_confidence") or (miss or {}).get("b4_analyzed") or 0)
    hi_frac = (hi / b4) if b4 > 0 else None
    components["measurement_coverage"] = _score_measurement_coverage(hi_frac)

    ml_pass = 0
    if telemetry_rows:
        for r in telemetry_rows:
            reject = str(r.get("reject") or "")
            if reject in ("gates_passed_long", "gates_passed_short"):
                ml_pass += 1
    b4_rate = (b4 / ml_pass) if ml_pass > 0 else None
    components["no_rule_fired_rate"] = _score_no_rule_fired(b4_rate)

    stability = stability_report or replay.get("directional_stability") or {}
    components["regime_stability"] = _score_regime_stability(stability.get("flip_rate"))

    cal = calibration_report or {}
    cal_overall = cal.get("overall") if isinstance(cal.get("overall"), dict) else cal
    cal_n = int(
        cal_overall.get("sample_count")
        or cal.get("sample_count")
        or len(cal.get("rows") or [])
    )
    ece_raw = cal_overall.get("ece")
    if ece_raw is None:
        ece_raw = cal.get("ece")
    components["calibration"] = _score_calibration(ece_raw, cal_n)

    weighted_sum = 0.0
    weight_used = 0.0
    for key, weight in WEIGHTS.items():
        comp = components[key]
        if comp.get("score") is not None:
            weighted_sum += float(comp["score"]) * weight
            weight_used += weight

    composite = round(weighted_sum / weight_used, 2) if weight_used > 0 else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "composite_dqi": composite,
        "weight_coverage": round(weight_used, 2),
        "components": components,
        "inputs": {
            "b4_total": b4,
            "high_confidence": hi,
            "ml_pass_cycles": ml_pass,
            "b4_rate": round(b4_rate, 4) if b4_rate is not None else None,
            "sweep_gate": cov.get("sweep_gate"),
        },
        "appendix": {
            "measurement_coverage": components.get("measurement_coverage"),
        },
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Decision Quality Index (DQI)",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Baseline: `{report.get('baseline_commit')}`",
        f"**Composite DQI:** {report.get('composite_dqi')} (weight coverage {report.get('weight_coverage')})",
        "",
        "## Components",
        "",
        "| Component | Weight | Score | Status |",
        "|-----------|-------:|------:|--------|",
    ]
    for key, weight in WEIGHTS.items():
        comp = (report.get("components") or {}).get(key) or {}
        lines.append(
            f"| {key} | {weight:.0%} | {comp.get('score')} | {comp.get('status')} |"
        )
    appendix = (report.get("appendix") or {}).get("measurement_coverage") or {}
    lines.extend(
        [
            "",
            "## Appendix (not blended)",
            "",
            f"| measurement_coverage | — | {appendix.get('score')} | {appendix.get('status')} |",
            f"| sweep_gate | — | — | {report.get('inputs', {}).get('sweep_gate')} |",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument("--shadow-json", type=Path, default=None)
    parser.add_argument("--replay-json", type=Path, default=None)
    parser.add_argument("--stability-json", type=Path, default=None)
    parser.add_argument("--calibration-json", type=Path, default=None)
    parser.add_argument("--thesis-miss-json", type=Path, default=None)
    parser.add_argument("--coverage-json", type=Path, default=None)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_json = args.out_json or (ROOT / "data" / "investigation" / f"dqi_{date_tag}.json")
    out_md = args.out_md or (ROOT / "data" / "investigation" / f"dqi_{date_tag}.md")

    rows = filter_since(load_telemetry(args.telemetry), args.hours)
    shadow = _load_json(args.shadow_json)
    if shadow is None:
        default_shadow = ROOT / "data" / "investigation" / "shadow_eval_report_48h.json"
        shadow = _load_json(default_shadow)

    replay = _load_json(args.replay_json) or _latest_rolling_replay()
    stability = _load_json(args.stability_json)
    if stability is None and replay:
        stability = {"flip_rate": (replay.get("directional_stability") or {}).get("flip_rate")}

    calibration = _load_json(args.calibration_json)
    if calibration is None:
        default_cal = ROOT / "data" / "investigation" / f"calibration_replay_{date_tag}.json"
        calibration = _load_json(default_cal)
    thesis_miss = _load_json(args.thesis_miss_json)
    coverage = _load_json(args.coverage_json)
    if coverage is None:
        default_cov = (
            ROOT / "data" / "investigation" / "decision_evidence" / date_tag / "coverage.json"
        )
        coverage = _load_json(default_cov)

    report = compute_dqi(
        shadow_report=shadow,
        replay_report=replay,
        stability_report=stability,
        calibration_report=calibration,
        thesis_miss_report=thesis_miss,
        coverage_report=coverage,
        telemetry_rows=rows,
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({"composite_dqi": report["composite_dqi"], "out_json": str(out_json)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
