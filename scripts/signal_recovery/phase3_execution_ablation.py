"""Phase 3.3: execution-path realism snapshot (config only, gates unchanged)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def run_execution_ablation(*, out_dir: Path) -> Dict[str, Any]:
    """Record short-execution and monitoring flags for replay/paper-forward planning."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "3.3",
        "note": "No production thresholds changed; use these flags for controlled replay runs.",
        "current_env": {
            "JACKSPARROW_V43_SHORT_EXECUTION_ENABLED": os.environ.get(
                "JACKSPARROW_V43_SHORT_EXECUTION_ENABLED", "false"
            ),
            "AGENT_START_MODE": os.environ.get("AGENT_START_MODE", "MONITORING"),
            "AI_SIGNAL_MIN_ENTRY_CONFIDENCE": os.environ.get(
                "AI_SIGNAL_MIN_ENTRY_CONFIDENCE", ""
            ),
            "AI_SIGNAL_MINIMAL_ENTRY_GATES": os.environ.get(
                "AI_SIGNAL_MINIMAL_ENTRY_GATES", "false"
            ),
            "JACKSPARROW_V43_INFERENCE_STACK": os.environ.get(
                "JACKSPARROW_V43_INFERENCE_STACK", "meta_calibrator"
            ),
        },
        "suggested_ablation_matrix": [
            {
                "variant": "A_baseline",
                "short_execution": False,
                "inference_stack": "meta_calibrator",
            },
            {
                "variant": "B_short_enabled",
                "short_execution": True,
                "inference_stack": "meta_calibrator",
            },
            {
                "variant": "C_regressor_mean",
                "short_execution": False,
                "inference_stack": "regressor_mean",
            },
        ],
    }
    path = out_dir / "execution_ablation_plan.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
