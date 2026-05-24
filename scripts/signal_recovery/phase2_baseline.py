"""Phase 2: baseline decision telemetry KPIs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.signal_recovery.kpi import compute_baseline_kpis
from scripts.signal_recovery.log_parser import merge_decision_sources


def run_phase2(
    *,
    telemetry_path: Path,
    agent_log: Path,
    out_dir: Path,
    hours: float = 24.0,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = merge_decision_sources(
        telemetry_path=telemetry_path,
        agent_log_path=agent_log,
        hours=hours,
    )
    kpis = compute_baseline_kpis(rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": 2,
        "window_hours": hours,
        "source_telemetry": str(telemetry_path),
        "source_agent_log": str(agent_log),
        "kpis": kpis,
    }
    out_path = out_dir / "baseline_kpis.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
