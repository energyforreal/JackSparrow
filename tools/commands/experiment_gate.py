#!/usr/bin/env python3
"""Gate experiment deploys (Phases C–E) on prerequisite readiness checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
for candidate in Path(__file__).resolve().parents:
    if (candidate / "agent").is_dir() and (candidate / "backend").is_dir():
        ROOT = candidate
        break
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.commands.phase_readiness_gate import evaluate_gate

EXPERIMENT_GATES: Dict[str, List[str]] = {
    "entry_tune_v1": [
        "p1_data_integrity",
        "v2_reject_labels",
        "v1_to_v2_snapshot",
    ],
    "exit_tune_v1": [
        "p1_data_integrity",
        "2b_to_3",
        "v2_mfe_mae",
    ],
    "tle_live_v1": [
        "2b_to_3",
        "3_to_4",
        "4_to_5",
        "p2_tle_observe",
    ],
}


def evaluate_experiment(
    experiment_id: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> Dict[str, Any]:
    """Return pass/fail for an experiment's prerequisite gates."""
    required = EXPERIMENT_GATES.get(experiment_id)
    if not required:
        return {
            "experiment_id": experiment_id,
            "pass": False,
            "error": "unknown_experiment",
        }

    gate_results: List[Dict[str, Any]] = []
    passed = True
    for gate_id in required:
        result = evaluate_gate(gate_id, start=start, end=end)
        gate_results.append(result)
        if not result.get("pass"):
            passed = False

    registry_path = ROOT / "data" / "experiments" / "registry.json"
    experiment_meta: Dict[str, Any] = {}
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for exp in registry.get("experiments") or []:
            if exp.get("experiment_id") == experiment_id:
                experiment_meta = exp
                break

    return {
        "experiment_id": experiment_id,
        "pass": passed,
        "required_gates": required,
        "gate_results": gate_results,
        "env_overrides": experiment_meta.get("env_overrides") or {},
        "notes": experiment_meta.get("notes"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Experiment deploy readiness gate")
    parser.add_argument(
        "--experiment",
        required=True,
        choices=list(EXPERIMENT_GATES.keys()),
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    result = evaluate_experiment(args.experiment, start=args.start, end=args.end)
    text = json.dumps(result, indent=2)
    print(text)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")

    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
