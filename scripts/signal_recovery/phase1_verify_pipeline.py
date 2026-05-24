"""Phase 1: runtime pipeline health + Delta IP whitelist checklist."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from scripts.signal_recovery.log_parser import load_agent_log_decisions

DELTA_WHITELIST_IP = "115.96.12.44"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _http_get(url: str, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)


def _count_recent_events(agent_log: Path, event: str, limit: int = 5000) -> int:
    if not agent_log.is_file():
        return 0
    n = 0
    tail: List[str] = []
    with agent_log.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            tail.append(line)
            if len(tail) > limit:
                tail.pop(0)
    for line in tail:
        if f'"event": "{event}"' in line or f'"event":"{event}"' in line:
            n += 1
    return n


def run_phase1(
    *,
    backend_base: str = "http://127.0.0.1:8000",
    agent_log: Path,
    out_dir: Path,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    checks: List[Dict[str, Any]] = []

    code, body = _http_get(f"{backend_base.rstrip('/')}/api/v1/health")
    checks.append(
        {
            "name": "backend_health",
            "ok": 200 <= code < 300,
            "detail": {"http_code": code, "body_preview": body[:300]},
        }
    )

    code2, _ = _http_get(f"{backend_base.rstrip('/')}/api/v1/signal/edge-history?symbol=BTCUSD&limit=3")
    checks.append(
        {
            "name": "backend_signal_history",
            "ok": 200 <= code2 < 300,
            "detail": {"http_code": code2},
        }
    )

    pred_failed = 0
    if agent_log.is_file():
        with agent_log.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "mcp_orchestrator_prediction_failed" in line:
                    pred_failed += 1

    decision_emitted = _count_recent_events(
        agent_log, "mcp_orchestrator_decision_ready_emitted"
    )
    v43_complete = _count_recent_events(
        agent_log, "mcp_orchestrator_v43_prediction_complete"
    )

    checks.append(
        {
            "name": "agent_v43_predictions",
            "ok": v43_complete > 0 and pred_failed == 0,
            "detail": {
                "v43_prediction_complete_tail": v43_complete,
                "prediction_failed_total": pred_failed,
            },
        }
    )
    checks.append(
        {
            "name": "agent_decision_ready_emitted",
            "ok": decision_emitted > 0,
            "detail": {"decision_ready_emitted_tail": decision_emitted},
        }
    )

    delta_note = (
        f"Whitelist outbound IP {DELTA_WHITELIST_IP} on Delta Exchange API key settings "
        "(portfolio/reconcile/execution). This is a manual exchange-console step."
    )
    checks.append(
        {
            "name": "delta_ip_whitelist",
            "ok": None,
            "manual": True,
            "detail": {"ip": DELTA_WHITELIST_IP, "instruction": delta_note},
        }
    )

    safety = {
        "policy_gates": "unchanged (default production thresholds)",
        "short_execution": os.environ.get("JACKSPARROW_V43_SHORT_EXECUTION_ENABLED", "true"),
        "agent_start_mode": os.environ.get("AGENT_START_MODE", "MONITORING"),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": 1,
        "checks": checks,
        "safety_frozen": safety,
        "all_automated_pass": all(c.get("ok") is True for c in checks if c.get("ok") is not None),
    }
    out_path = out_dir / "phase1_pipeline_health.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
