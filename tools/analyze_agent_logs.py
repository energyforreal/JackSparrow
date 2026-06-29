#!/usr/bin/env python3
"""Parse jacksparrow-agent structlog JSON and report decision-pipeline metrics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


@dataclass
class AgentLogMetrics:
    """Aggregated metrics from agent decision logs."""

    total_lines: int = 0
    parsed_events: int = 0
    decision_cycles: int = 0
    policy_signals: Counter = field(default_factory=Counter)
    thesis_signals: Counter = field(default_factory=Counter)
    gated_ml_neutral_entries: int = 0
    risk_approved: int = 0
    fills: int = 0
    execution_failed: int = 0
    hold_same_bar_skips: int = 0
    buy_to_hold_flips: int = 0
    rule_based_shadow_cycles: int = 0
    structural_shadow_blocks: int = 0
    fsm_shadow_disagreements: int = 0
    entry_reason_codes: Counter = field(default_factory=Counter)


def _iter_json_objects(text: str) -> Iterator[Dict[str, Any]]:
    """Yield JSON objects from log text (single-line or wrapped)."""
    dec = json.JSONDecoder()
    pos = 0
    length = len(text)
    while pos < length:
        while pos < length and text[pos] in " \t\r\n":
            pos += 1
        if pos >= length:
            break
        if text[pos] != "{":
            nl = text.find("\n", pos)
            if nl < 0:
                break
            pos = nl + 1
            continue
        try:
            obj, end = dec.raw_decode(text, pos)
            if isinstance(obj, dict):
                yield obj
            pos = end
        except json.JSONDecodeError:
            nl = text.find("\n", pos)
            if nl < 0:
                break
            pos = nl + 1


def _parse_timestamp(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    s = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def analyze_log_content(content: str) -> AgentLogMetrics:
    """Analyze log file content and return metrics."""
    metrics = AgentLogMetrics()
    metrics.total_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    last_long_ts: Optional[datetime] = None
    last_long_symbol: Optional[str] = None

    for obj in _iter_json_objects(content):
        metrics.parsed_events += 1
        event = str(obj.get("event") or obj.get("message") or "")

        if event == "mcp_orchestrator_decision_ready_emitted":
            metrics.decision_cycles += 1
            sig = str(obj.get("signal") or "HOLD").upper()
            metrics.policy_signals[sig] += 1
            ts = _parse_timestamp(obj.get("timestamp"))
            sym = str(obj.get("symbol") or "")
            if sig in ("LONG", "STRONG_LONG", "BUY", "STRONG_BUY"):
                last_long_ts = ts
                last_long_symbol = sym
            elif sig == "HOLD" and last_long_ts and last_long_symbol == sym:
                if ts and (ts - last_long_ts).total_seconds() < 600:
                    metrics.buy_to_hold_flips += 1
                last_long_ts = None
                last_long_symbol = None

        if event == "evidence_conviction_cycle":
            metrics.thesis_signals[str(obj.get("policy_signal") or "HOLD")] += 1

        if event == "v43_decision_emit_skipped_hold_same_bar":
            metrics.hold_same_bar_skips += 1

        if event == "rule_based_pipeline_shadow":
            metrics.rule_based_shadow_cycles += 1
            if obj.get("would_block_live_entry"):
                metrics.structural_shadow_blocks += 1
            if obj.get("fsm_disagrees_with_live"):
                metrics.fsm_shadow_disagreements += 1

        if event == "structural_gate_shadow":
            metrics.rule_based_shadow_cycles += 1
            if not obj.get("trade_allowed"):
                metrics.structural_shadow_blocks += 1

        if event == "fsm_shadow_decision":
            metrics.fsm_shadow_disagreements += 0  # counted via pipeline_shadow

        conclusion = str(obj.get("conclusion") or obj.get("reasoning") or "")
        if "gated ML adoption" in conclusion or "gated_ml" in conclusion.lower():
            metrics.gated_ml_neutral_entries += 1

        for code in obj.get("policy_reason_codes") or obj.get("reason_codes") or []:
            c = str(code)
            if "gated" in c.lower() and "neutral" in c.lower():
                metrics.gated_ml_neutral_entries += 1
            if "fusion_ml_gated_thesis_neutral" in c:
                metrics.entry_reason_codes[c] += 1

        if event in ("risk_approved", "trading_handler_risk_approved"):
            metrics.risk_approved += 1
        if "fill" in event.lower() and "failed" not in event.lower():
            if event in ("order_filled", "execution_fill", "trade_filled"):
                metrics.fills += 1
        if "execution_risk_approved_trade_failed" in event:
            metrics.execution_failed += 1

    return metrics


def format_report(metrics: AgentLogMetrics) -> str:
    """Format metrics as human-readable report."""
    lines = [
        "=== JackSparrow Agent Log Analysis ===",
        f"Total lines: {metrics.total_lines}",
        f"Parsed JSON events: {metrics.parsed_events}",
        f"Decision cycles: {metrics.decision_cycles}",
        "",
        "Policy signals:",
    ]
    for sig, count in metrics.policy_signals.most_common():
        lines.append(f"  {sig}: {count}")

    lines.extend(
        [
            "",
            f"Gated ML neutral entries: {metrics.gated_ml_neutral_entries}",
            f"Risk approved: {metrics.risk_approved}",
            f"Fills: {metrics.fills}",
            f"Execution failed after risk: {metrics.execution_failed}",
            f"BUY->HOLD flips (<10m): {metrics.buy_to_hold_flips}",
            f"hold_same_bar skips: {metrics.hold_same_bar_skips}",
            "",
            "Rule-based shadow (if enabled):",
            f"  Shadow cycles: {metrics.rule_based_shadow_cycles}",
            f"  Would block live entry: {metrics.structural_shadow_blocks}",
            f"  FSM disagrees with live: {metrics.fsm_shadow_disagreements}",
        ]
    )
    if metrics.entry_reason_codes:
        lines.append("")
        lines.append("Entry reason codes:")
        for code, count in metrics.entry_reason_codes.most_common(10):
            lines.append(f"  {code}: {count}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze jacksparrow-agent Docker logs")
    parser.add_argument(
        "log_file",
        nargs="?",
        type=Path,
        help="Path to log file (stdin if omitted)",
    )
    args = parser.parse_args()

    if args.log_file:
        content = args.log_file.read_text(encoding="utf-8", errors="replace")
    else:
        content = sys.stdin.read()

    metrics = analyze_log_content(content)
    print(format_report(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
