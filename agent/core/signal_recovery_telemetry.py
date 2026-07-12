"""Append-only NDJSON telemetry for JackSparrow signal-recovery KPI tooling."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

_lock = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Mirrors CORE_THESIS_FEATURES in scripts/signal_recovery/decision_evidence.py.
# Duplicated (not imported) because that module lives under scripts/, which is
# not copied into the agent Docker image (see agent/Dockerfile COPY list) —
# keep both tuples in sync if the thesis engine's core feature set changes.
CORE_THESIS_FEATURES: Tuple[str, ...] = (
    "adx_14",
    "di_spread",
    "vol_regime",
    "hurst_60",
    "h_trend",
    "h1_trend",
    "rsi_14",
    "bb_pos",
)

# Research dual-write (optional). Not part of high-confidence sweep gate.
RESEARCH_THESIS_FEATURES: Tuple[str, ...] = ("hurst_60_v2",)


def extract_core_thesis_features(features: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Pull the CORE_THESIS_FEATURES subset out of a raw features dict.

    Written into telemetry rows as extra["features"] so the offline evidence
    assembler (decision_evidence.py) can classify a row as telemetry_embedded
    (medium confidence) without needing a raw agent-log join. This is the
    Phase 6 hardening tracked in
    data/investigation/decision_observability_program_2026-07-11.md.

    Also embeds RESEARCH_THESIS_FEATURES (e.g. hurst_60_v2) when present —
    these do not affect the high-confidence gate.
    """
    out: Dict[str, float] = {}
    if not isinstance(features, dict):
        return out
    lower = {str(k).lower(): v for k, v in features.items()}
    for key in (*CORE_THESIS_FEATURES, *RESEARCH_THESIS_FEATURES):
        v = lower.get(key)
        if v is None:
            continue
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            continue
    return out


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


def _append_row(row: Dict[str, Any]) -> None:
    path = telemetry_path()
    from agent.core.config import settings as app_settings

    max_bytes = int(
        getattr(app_settings, "signal_recovery_telemetry_max_bytes", 100 * 1024 * 1024)
        or 100 * 1024 * 1024
    )
    backup_count = 3
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > max_bytes:
                for i in range(backup_count - 1, 0, -1):
                    src = path.with_suffix(path.suffix + f".{i}")
                    dst = path.with_suffix(path.suffix + f".{i + 1}")
                    if src.is_file():
                        if dst.is_file():
                            dst.unlink()
                        src.rename(dst)
                rotated = path.with_suffix(path.suffix + ".1")
                if rotated.is_file():
                    rotated.unlink()
                path.rename(rotated)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning("signal_recovery_telemetry_write_failed", error=str(exc), path=str(path))


def record_decision_cycle(
    *,
    symbol: str,
    signal: str,
    confidence: float,
    expected_return: Optional[float] = None,
    trade_score: Optional[float] = None,
    thesis_signal: Optional[str] = None,
    hypothesis_dominant: Optional[str] = None,
    aggregate_confidence: Optional[float] = None,
    hypothesis_margin: Optional[float] = None,
    policy_reason_codes: Optional[List[str]] = None,
    v43_collapse_rate: Optional[float] = None,
    proba: Optional[float] = None,
    threshold: Optional[float] = None,
    inference_stack: Optional[str] = None,
    event: str = "decision_cycle",
    extra: Optional[Dict[str, Any]] = None,
    bar_index: Optional[int] = None,
    latent: Optional[Dict[str, Any]] = None,
    gates: Optional[Dict[str, Any]] = None,
    scores: Optional[Dict[str, Any]] = None,
    signals: Optional[Dict[str, Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
    terminal_cause: Optional[str] = None,
    policy_snapshot: Optional[Dict[str, Any]] = None,
    core_features: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one JSON line for baseline / promotion / attribution scripts.

    core_features: raw features dict (e.g. mcp_orchestrator's features_dict /
    market_context["features"]) — the CORE_THESIS_FEATURES subset is extracted
    and stored at extra["features"] so decision_evidence.py can source
    telemetry_embedded provenance for every row, not just rows covered by a
    raw agent-log export.
    """
    if not _enabled():
        return
    row: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "symbol": symbol,
        "signal": signal,
        "confidence": float(confidence),
    }
    if bar_index is not None:
        row["bar_index"] = int(bar_index)
    if expected_return is not None:
        row["expected_return"] = float(expected_return)
    if trade_score is not None:
        row["trade_score"] = float(trade_score)
    if thesis_signal is not None:
        row["thesis_signal"] = thesis_signal
    if hypothesis_dominant is not None:
        row["hypothesis_dominant"] = hypothesis_dominant
    if aggregate_confidence is not None:
        row["aggregate_confidence"] = float(aggregate_confidence)
    if hypothesis_margin is not None:
        row["hypothesis_margin"] = float(hypothesis_margin)
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
    if latent:
        row["latent"] = dict(latent)
    if gates:
        row["gates"] = dict(gates)
    if scores:
        row["scores"] = dict(scores)
    if signals:
        row["signals"] = dict(signals)
    if constraints:
        row["constraints"] = dict(constraints)
    if terminal_cause:
        row["terminal_cause"] = str(terminal_cause)
    if policy_snapshot:
        row["policy_snapshot"] = dict(policy_snapshot)
    if extra:
        row["extra"] = dict(extra)
    if core_features:
        feats = extract_core_thesis_features(core_features)
        if feats:
            row.setdefault("extra", {})
            existing_features = row["extra"].get("features")
            if isinstance(existing_features, dict):
                merged = dict(existing_features)
                merged.update(feats)
                row["extra"]["features"] = merged
            else:
                row["extra"]["features"] = feats
    _append_row(row)


def record_handler_outcome(
    *,
    symbol: str,
    policy_signal: str,
    handler_reject_reason: Optional[str] = None,
    executed: bool = False,
    bar_index: Optional[int] = None,
    effective_margin_fraction: Optional[float] = None,
    entry_lots: Optional[int] = None,
) -> None:
    """Follow-up telemetry line after trading handler processes DECISION_READY."""
    if not _enabled():
        return
    from agent.core.decision_telemetry import classify_terminal_cause

    terminal = classify_terminal_cause(
        policy_signal=policy_signal,
        gate_reject=None,
        final_long=False,
        final_short=False,
        raw_long=False,
        raw_short=False,
        handler_reject_reason=handler_reject_reason,
        executed=executed,
    )
    row: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "handler_outcome",
        "symbol": symbol,
        "signal": policy_signal,
        "terminal_cause": terminal,
        "signals": {
            "policy": policy_signal,
            "handler_rejected": bool(handler_reject_reason),
            "executed": executed,
        },
    }
    if bar_index is not None:
        row["bar_index"] = int(bar_index)
    if handler_reject_reason:
        row["handler_reject_reason"] = str(handler_reject_reason)
    if effective_margin_fraction is not None:
        row["scores"] = {"effective_margin_fraction": float(effective_margin_fraction)}
    if entry_lots is not None:
        row.setdefault("scores", {})["entry_lots"] = int(entry_lots)
    _append_row(row)


def check_over_gating_regression(
    *,
    lookback_days: int = 7,
    min_raw_signals: int = 10,
) -> Optional[Dict[str, Any]]:
    """Alert when raw signals exist but zero executions (over-gating regression)."""
    path = telemetry_path()
    if not path.is_file():
        return None
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    raw_signals = 0
    executions = 0
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_raw = row.get("ts")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
                gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
                extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
                if gates.get("g1_raw_long") or gates.get("g1_raw_short"):
                    raw_signals += 1
                elif extra.get("final_long") or extra.get("final_short"):
                    raw_signals += 1
                sig = str(row.get("signal") or "HOLD").upper()
                if row.get("event") == "handler_outcome" and row.get("signals", {}).get(
                    "executed"
                ):
                    executions += 1
                elif sig in ("LONG", "SHORT", "STRONG_LONG", "STRONG_SHORT") and row.get(
                    "terminal_cause"
                ) == "executed":
                    executions += 1
    except OSError:
        return None
    if raw_signals >= min_raw_signals and executions == 0:
        alert = {
            "alert": "over_gating_regression",
            "lookback_days": lookback_days,
            "raw_signals": raw_signals,
            "executed_trades": executions,
        }
        logger.warning("over_gating_regression_alert", **alert)
        return alert
    return None
