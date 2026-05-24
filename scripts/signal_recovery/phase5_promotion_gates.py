"""Phase 5: strict promotion gates vs baseline KPI report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_GATES = {
    "hold_ratio_max_delta": -0.05,
    "confidence_std_min_delta": 0.02,
    "expected_return_std_min_delta": 0.0005,
    "actionable_rate_min_delta": 0.01,
    "max_collapse_rate": 0.95,
}


def evaluate_promotion(
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    gates: Optional[Dict[str, float]] = None,
    prediction_failed_count: int = 0,
) -> Dict[str, Any]:
    g = {**DEFAULT_GATES, **(gates or {})}
    b = baseline.get("kpis") or baseline
    c = candidate.get("kpis") or candidate

    def _f(k: str) -> float:
        try:
            return float(c.get(k, 0.0)) - float(b.get(k, 0.0))
        except (TypeError, ValueError):
            return 0.0

    checks: List[Dict[str, Any]] = []

    hold_delta = _f("hold_ratio")
    checks.append(
        {
            "gate": "hold_ratio_reduced",
            "pass": hold_delta <= float(g["hold_ratio_max_delta"]),
            "delta": hold_delta,
            "threshold": g["hold_ratio_max_delta"],
        }
    )
    conf_delta = _f("confidence_std")
    checks.append(
        {
            "gate": "confidence_variance_improved",
            "pass": conf_delta >= float(g["confidence_std_min_delta"]),
            "delta": conf_delta,
            "threshold": g["confidence_std_min_delta"],
        }
    )
    er_delta = _f("expected_return_std")
    checks.append(
        {
            "gate": "expected_return_variance_improved",
            "pass": er_delta >= float(g["expected_return_std_min_delta"]),
            "delta": er_delta,
            "threshold": g["expected_return_std_min_delta"],
        }
    )
    act_delta = _f("actionable_rate")
    checks.append(
        {
            "gate": "actionable_rate_improved",
            "pass": act_delta >= float(g["actionable_rate_min_delta"]),
            "delta": act_delta,
            "threshold": g["actionable_rate_min_delta"],
        }
    )
    collapse = c.get("v43_collapse_rate_mean")
    collapse_ok = collapse is None or float(collapse) <= float(g["max_collapse_rate"])
    checks.append(
        {
            "gate": "collapse_rate_bounded",
            "pass": collapse_ok,
            "value": collapse,
            "threshold": g["max_collapse_rate"],
        }
    )
    checks.append(
        {
            "gate": "no_prediction_failed",
            "pass": prediction_failed_count == 0,
            "count": prediction_failed_count,
        }
    )

    promotable = all(ch["pass"] for ch in checks)
    return {
        "promotable": promotable,
        "decision": "promote" if promotable else "iterate",
        "checks": checks,
    }


def run_promotion_gates(
    *,
    baseline_path: Path,
    candidate_path: Path,
    out_dir: Path,
    agent_log: Optional[Path] = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))

    pred_failed = 0
    if agent_log and agent_log.is_file():
        text = agent_log.read_text(encoding="utf-8", errors="replace")
        pred_failed = text.count("mcp_orchestrator_prediction_failed")

    verdict = evaluate_promotion(baseline, candidate, prediction_failed_count=pred_failed)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": 5,
        "baseline_path": str(baseline_path),
        "candidate_path": str(candidate_path),
        **verdict,
    }
    out_path = out_dir / "promotion_gate_verdict.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
