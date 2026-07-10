#!/usr/bin/env python3
"""Parse agent structlog JSON and produce rejection / hold-cause forensics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iter_json_objects(text: str) -> Iterator[Dict[str, Any]]:
    """Yield JSON objects from log text (handles PowerShell/docker line wrapping)."""
    dec = json.JSONDecoder()
    # PowerShell Out-File wraps long structlog lines; flatten whitespace so objects
    # parse as `{...}{...}` sequences.
    flat = re.sub(r"\s+", "", text)
    pos = 0
    length = len(flat)
    while pos < length:
        if flat[pos] != "{":
            pos += 1
            continue
        try:
            obj, end = dec.raw_decode(flat, pos)
            if isinstance(obj, dict):
                yield obj
            pos = end
        except json.JSONDecodeError:
            pos += 1


def _nested_get(obj: Dict[str, Any], *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _reason_codes_from_context(ctx: Dict[str, Any]) -> List[str]:
    codes: List[str] = []
    pv = ctx.get("policy_verdict")
    if isinstance(pv, dict):
        for c in pv.get("reason_codes") or []:
            codes.append(str(c))
    hyp = ctx.get("hypothesis_snapshot")
    if isinstance(hyp, dict):
        for c in hyp.get("reason_codes") or []:
            codes.append(str(c))
    mc = ctx.get("market_context")
    if isinstance(mc, dict):
        hyp2 = mc.get("hypothesis_snapshot")
        if isinstance(hyp2, dict):
            for c in hyp2.get("reason_codes") or []:
                codes.append(str(c))
        pv2 = mc.get("policy_verdict")
        if isinstance(pv2, dict):
            for c in pv2.get("reason_codes") or []:
                codes.append(str(c))
    # Some reject payloads nest policy under decision_context.
    dc = ctx.get("decision_context")
    if isinstance(dc, dict):
        for c in _reason_codes_from_context(dc):
            codes.append(c)
    return codes


def _primary_hold_cause(codes: List[str]) -> str:
    """Pick dominant semantic cause from policy/hypothesis reason codes."""
    priority = (
        "hypothesis_no_rule_fired",
        "thesis_no_rule_fired",
        "hypothesis_margin_below_min",
        "thesis_direction_conflict",
        "fusion_ml_or_thesis_blocked",
        "thesis_blocks_ml_adoption",
        "fusion_ml_or_thesis_thesis_blocked",
        "thesis_neutral_no_ml_confirm",
        "thesis_squeeze_veto",
        "thesis_crisis_regime_veto",
        "thesis_liquidity_veto",
        "thesis_atr_too_low",
        "thesis_open_position",
    )
    code_set = set(codes)
    for p in priority:
        if p in code_set:
            return p
    for c in codes:
        if c.startswith("hypothesis_") or c.startswith("thesis_") or c.startswith("fusion_"):
            return c
    return "unknown_hold_cause"


@dataclass
class ForensicsReport:
    """Aggregated forensics from agent logs."""

    parsed_events: int = 0
    handler_reject_by_reason: Counter = field(default_factory=Counter)
    handler_reject_by_signal: Counter = field(default_factory=Counter)
    hold_at_synthesis_causes: Counter = field(default_factory=Counter)
    hold_policy_reason_codes: Counter = field(default_factory=Counter)
    v43_prediction_complete: int = 0
    v43_policy_signals: Counter = field(default_factory=Counter)
    v43_reject_tags: Counter = field(default_factory=Counter)
    terminal_cause_v3: Counter = field(default_factory=Counter)
    latest_v43_counters: Dict[str, Any] = field(default_factory=dict)
    decisions_emitted: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confidence_cascades: List[Dict[str, Any]] = field(default_factory=list)
    risk_approved_count: int = 0
    fill_count: int = 0


def analyze_log_content(content: str) -> ForensicsReport:
    """Analyze log content and return forensics report."""
    report = ForensicsReport()

    for obj in _iter_json_objects(content):
        report.parsed_events += 1
        event = str(obj.get("event") or obj.get("message") or "")

        if event == "trading_entry_rejected":
            reason = str(obj.get("reason") or "unknown")
            signal = str(obj.get("signal") or "UNKNOWN").upper()
            report.handler_reject_by_reason[reason] += 1
            report.handler_reject_by_signal[signal] += 1

            if reason == "hold_at_synthesis":
                codes = _reason_codes_from_context(obj)
                for c in codes:
                    report.hold_policy_reason_codes[c] += 1
                report.hold_at_synthesis_causes[_primary_hold_cause(codes)] += 1

            if signal in ("LONG", "SHORT"):
                mc = obj.get("market_context") if isinstance(obj.get("market_context"), dict) else {}
                features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
                pv = obj.get("policy_verdict") if isinstance(obj.get("policy_verdict"), dict) else {}
                thesis_type = None
                for code in pv.get("reason_codes") or []:
                    if str(code).startswith("thesis_type="):
                        thesis_type = str(code).replace("thesis_type=", "")
                        break
                cascade = {
                    "event_id": obj.get("event_id"),
                    "timestamp": obj.get("timestamp"),
                    "symbol": obj.get("symbol"),
                    "signal": signal,
                    "reject_reason": reason,
                    "trade_score": obj.get("trade_score") or mc.get("trade_score"),
                    "v43_proba": _nested_get(mc, "ml_validation", "proba"),
                    "policy_signal": pv.get("signal"),
                    "policy_confidence": pv.get("confidence"),
                    "thesis_type": thesis_type,
                    "raw_ai_signal_confidence": obj.get("raw_ai_signal_confidence"),
                    "calibrated_confidence": obj.get("calibrated_confidence"),
                    "reasoning_final_confidence": obj.get("reasoning_final_confidence"),
                    "adx_14": features.get("adx_14") or obj.get("adx"),
                    "policy_reason_codes": (pv.get("reason_codes") or [])[:8],
                }
                report.confidence_cascades.append(cascade)

        if event == "mcp_orchestrator_decision_ready_emitted":
            eid = str(obj.get("event_id") or "")
            if eid:
                report.decisions_emitted[eid] = {
                    "signal": obj.get("signal"),
                    "confidence": obj.get("confidence"),
                    "position_size": obj.get("position_size"),
                    "timestamp": obj.get("timestamp"),
                    "correlation_id": obj.get("correlation_id"),
                }

        if event == "mcp_orchestrator_v43_prediction_complete":
            report.v43_prediction_complete += 1
            ps = str(obj.get("policy_signal") or "HOLD").upper()
            report.v43_policy_signals[ps] += 1
            report.v43_reject_tags[str(obj.get("reject") or "unknown")] += 1
            report.latest_v43_counters = {
                "signals_raw": obj.get("v43_cnt_signals_raw"),
                "trades_executed": obj.get("v43_cnt_trades_executed"),
                "rejected_pos_open": obj.get("v43_cnt_rejected_pos_open"),
                "collapse_rate": obj.get("v43_collapse_rate"),
                "timestamp": obj.get("timestamp"),
            }

        if event in ("risk_approved", "trading_handler_risk_approved_published"):
            report.risk_approved_count += 1
        if event in ("order_filled", "execution_fill", "trade_filled", "execution_order_fill_published"):
            report.fill_count += 1

    return report


def analyze_telemetry_ndjson(content: str) -> Dict[str, Any]:
    """Aggregate v3 terminal_cause histogram from decision_telemetry.ndjson."""
    terminal: Counter = Counter()
    gate_layers: Counter = Counter()
    rows = 0
    for line in content.splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows += 1
        tc = str(row.get("terminal_cause") or "unknown")
        terminal[tc] += 1
        gates = row.get("gates")
        if isinstance(gates, dict) and gates.get("gate_reject"):
            gate_layers[str(gates["gate_reject"])] += 1
    return {
        "telemetry_rows": rows,
        "terminal_cause_histogram": dict(terminal.most_common()),
        "gate_reject_tags": dict(gate_layers.most_common(20)),
    }


def merge_telemetry_into_report(report: ForensicsReport, telemetry_stats: Dict[str, Any]) -> None:
    """Merge NDJSON v3 stats into forensics report counters."""
    for cause, count in (telemetry_stats.get("terminal_cause_histogram") or {}).items():
        report.terminal_cause_v3[cause] += int(count)


def _pct(counter: Counter, key: str) -> float:
    total = sum(counter.values()) or 1
    return round(counter.get(key, 0) / total * 100.0, 2)


def build_output(
    report: ForensicsReport,
    *,
    baseline: Optional[Dict[str, Any]] = None,
    redis_gate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build JSON-serializable investigation output."""
    hold_total = sum(report.hold_at_synthesis_causes.values()) or 1
    hold_causes = [
        {
            "cause": k,
            "count": v,
            "pct": round(v / hold_total * 100.0, 2),
        }
        for k, v in report.hold_at_synthesis_causes.most_common(20)
    ]

    reject_hist = [
        {"reason": k, "count": v, "pct": _pct(report.handler_reject_by_reason, k)}
        for k, v in report.handler_reject_by_reason.most_common(30)
    ]

    counter_reconcile: Dict[str, Any] = {
        "postgres_trades_executed": _nested_get(baseline or {}, "postgres", "trades_executed_count"),
        "postgres_last_trade_at": _nested_get(baseline or {}, "postgres", "last_trade_at"),
        "redis_trades_executed": _nested_get(redis_gate or {}, "counters", "trades_executed"),
        "redis_signals_raw": _nested_get(redis_gate or {}, "counters", "signals_raw"),
        "log_latest_v43_trades_executed": report.latest_v43_counters.get("trades_executed"),
        "log_latest_collapse_rate": report.latest_v43_counters.get("collapse_rate"),
        "gap_db_minus_v43": None,
        "interpretation": (
            "v43 counter increments only on fills with v43_closed_bar_index; "
            "Postgres trades table counts all EXECUTED rows regardless of v43 path."
        ),
    }
    pg = counter_reconcile.get("postgres_trades_executed")
    v43 = counter_reconcile.get("redis_trades_executed") or counter_reconcile.get(
        "log_latest_v43_trades_executed"
    )
    if pg is not None and v43 is not None:
        counter_reconcile["gap_db_minus_v43"] = int(pg) - int(v43)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parsed_events": report.parsed_events,
        "handler_reject_histogram": reject_hist,
        "handler_reject_by_signal": dict(report.handler_reject_by_signal),
        "hold_at_synthesis": {
            "total": sum(report.hold_at_synthesis_causes.values()),
            "primary_causes": hold_causes,
            "top_policy_reason_codes": [
                {"code": k, "count": v}
                for k, v in report.hold_policy_reason_codes.most_common(25)
            ],
        },
        "v43_prediction": {
            "cycles": report.v43_prediction_complete,
            "policy_signals": dict(report.v43_policy_signals),
            "reject_tags": dict(report.v43_reject_tags),
            "latest_counters": report.latest_v43_counters,
        },
        "execution_path": {
            "risk_approved_count": report.risk_approved_count,
            "fill_count": report.fill_count,
        },
        "v3_terminal_cause": dict(report.terminal_cause_v3),
        "confidence_cascades_non_hold": report.confidence_cascades[-50:],
        "counter_reconciliation": counter_reconcile,
        "semantic_notes": {
            "thesis_type_flat_vs_regime_neutral": (
                "thesis_type=flat is a ThesisVerdict label; regime=neutral is market "
                "classification. AGENT_POLICY_ADOPT_GATED_ML_WHEN_THESIS_NEUTRAL does not "
                "apply when hypothesis_no_rule_fired is present."
            ),
            "hold_at_synthesis": (
                "Handler label when policy already emitted HOLD before entry gates."
            ),
        },
    }


def format_summary(data: Dict[str, Any]) -> str:
    """Human-readable summary."""
    lines = [
        "=== Rejection Forensics Summary ===",
        f"Parsed events: {data.get('parsed_events', 0)}",
        "",
        "Handler reject histogram:",
    ]
    for row in data.get("handler_reject_histogram") or []:
        lines.append(f"  {row['reason']}: {row['count']} ({row['pct']}%)")

    hold = data.get("hold_at_synthesis") or {}
    lines.extend(["", f"Hold at synthesis total: {hold.get('total', 0)}", "Primary causes:"])
    for row in hold.get("primary_causes") or []:
        lines.append(f"  {row['cause']}: {row['count']} ({row['pct']}%)")

    lines.extend(["", "V43 latest counters:", json.dumps(data.get("v43_prediction", {}).get("latest_counters"), indent=2)])
    lines.extend(["", "Counter reconciliation:", json.dumps(data.get("counter_reconciliation"), indent=2)])

    cascades = data.get("confidence_cascades_non_hold") or []
    if cascades:
        lines.extend(["", f"Non-HOLD reject cascades (last {len(cascades)}):"])
        for c in cascades[-10:]:
            lines.append(
                f"  {c.get('timestamp')} {c.get('signal')} score={c.get('trade_score')} "
                f"policy_conf={c.get('policy_confidence')} adx={c.get('adx_14')} "
                f"-> {c.get('reject_reason')}"
            )
    return "\n".join(lines)


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_redis_gate(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path, help="Agent log file path")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "investigation" / "rejection_forensics_2026-07-09.json",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "data" / "investigation" / "baseline_export_2026-07-09.json",
    )
    parser.add_argument(
        "--redis-gate",
        type=Path,
        default=ROOT / "data" / "investigation" / "redis_gate_state_BTCUSD.txt",
    )
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=None,
        help="Optional decision_telemetry.ndjson for v3 terminal_cause histogram",
    )
    args = parser.parse_args()

    content = args.log_file.read_text(encoding="utf-8", errors="replace")
    report = analyze_log_content(content)
    telemetry_stats: Optional[Dict[str, Any]] = None
    if args.telemetry and args.telemetry.is_file():
        telemetry_stats = analyze_telemetry_ndjson(
            args.telemetry.read_text(encoding="utf-8", errors="replace")
        )
        merge_telemetry_into_report(report, telemetry_stats)
    output = build_output(
        report,
        baseline=_load_json_file(args.baseline),
        redis_gate=_load_redis_gate(args.redis_gate),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(format_summary(output))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
