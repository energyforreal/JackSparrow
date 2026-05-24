"""Parse agent structlog NDJSON and signal-recovery telemetry files."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, TextIO


def iter_json_lines(stream: TextIO) -> Iterator[Dict[str, Any]]:
    for raw in stream:
        line = raw.strip()
        if not line or line[0] not in "{[":
            continue
        if line.startswith("docker :"):
            line = line.removeprefix("docker :").strip()
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _parse_ts(obj: Dict[str, Any]) -> Optional[datetime]:
    for key in ("ts", "timestamp", "time"):
        v = obj.get(key)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            try:
                return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc)
            except (OSError, ValueError):
                continue
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def filter_since(rows: List[Dict[str, Any]], hours: float) -> List[Dict[str, Any]]:
    if hours <= 0:
        return rows
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: List[Dict[str, Any]] = []
    for r in rows:
        ts = _parse_ts(r)
        if ts is None or ts >= cutoff:
            out.append(r)
    return out


def load_telemetry(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for obj in iter_json_lines(f):
            rows.append(obj)
    return rows


def load_agent_log_decisions(path: Path) -> List[Dict[str, Any]]:
    """Extract decision rows from agent.log structlog events."""
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for obj in iter_json_lines(f):
            ev = obj.get("event")
            if ev == "mcp_orchestrator_decision_ready_emitted":
                rows.append(
                    {
                        "ts": obj.get("timestamp"),
                        "event": ev,
                        "symbol": obj.get("symbol"),
                        "signal": obj.get("signal"),
                        "confidence": obj.get("confidence"),
                    }
                )
            elif ev == "mcp_orchestrator_v43_prediction_complete":
                rows.append(
                    {
                        "ts": obj.get("timestamp"),
                        "event": ev,
                        "symbol": obj.get("symbol"),
                        "signal": obj.get("policy_signal"),
                        "confidence": obj.get("confidence"),
                        "expected_return": obj.get("proba"),
                        "threshold": obj.get("thr"),
                        "thesis_signal": obj.get("thesis_signal"),
                        "trade_score": obj.get("trade_score"),
                        "v43_collapse_rate": obj.get("v43_collapse_rate"),
                    }
                )
    return rows


def merge_decision_sources(
    *,
    telemetry_path: Path,
    agent_log_path: Path,
    hours: float,
) -> List[Dict[str, Any]]:
    """Prefer dedicated telemetry; fall back to agent.log parsing."""
    rows = load_telemetry(telemetry_path)
    if not rows:
        rows = load_agent_log_decisions(agent_log_path)
    return filter_since(rows, hours)
