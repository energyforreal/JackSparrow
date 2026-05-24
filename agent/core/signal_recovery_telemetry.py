"""Append-only NDJSON telemetry for JackSparrow signal-recovery KPI tooling."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

_lock = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _logs_root() -> Path:
    return Path(os.environ.get("LOGS_ROOT", str(_PROJECT_ROOT / "logs")))


def telemetry_path() -> Path:
    from agent.core.config import settings

    sub = (
        getattr(settings, "signal_recovery_telemetry_subpath", None)
        or "signal_recovery/decision_telemetry.ndjson"
    ).strip()
    return _logs_root() / sub


def _enabled() -> bool:
    try:
        from agent.core.config import settings

        return bool(getattr(settings, "signal_recovery_telemetry_enabled", True))
    except Exception:
        return True


def record_decision_cycle(
    *,
    symbol: str,
    signal: str,
    confidence: float,
    expected_return: Optional[float] = None,
    trade_score: Optional[float] = None,
    thesis_signal: Optional[str] = None,
    policy_reason_codes: Optional[List[str]] = None,
    v43_collapse_rate: Optional[float] = None,
    proba: Optional[float] = None,
    threshold: Optional[float] = None,
    inference_stack: Optional[str] = None,
    event: str = "decision_cycle",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one JSON line for baseline / promotion scripts (no safety gate changes)."""
    if not _enabled():
        return
    row: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "symbol": symbol,
        "signal": signal,
        "confidence": float(confidence),
    }
    if expected_return is not None:
        row["expected_return"] = float(expected_return)
    if trade_score is not None:
        row["trade_score"] = float(trade_score)
    if thesis_signal is not None:
        row["thesis_signal"] = thesis_signal
    if policy_reason_codes:
        row["policy_reason_codes"] = list(policy_reason_codes)
    if v43_collapse_rate is not None:
        row["v43_collapse_rate"] = float(v43_collapse_rate)
    if proba is not None:
        row["proba"] = float(proba)
    if threshold is not None:
        row["threshold"] = float(threshold)
    if inference_stack:
        row["inference_stack"] = inference_stack
    if extra:
        row.update(extra)
    path = telemetry_path()
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning("signal_recovery_telemetry_write_failed", error=str(exc), path=str(path))
