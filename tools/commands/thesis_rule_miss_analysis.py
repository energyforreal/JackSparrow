#!/usr/bin/env python3
"""Nearest-miss thesis rule diagnostics for B4 (ML pass, flat hypothesis) cycles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.agent_thesis_engine import AgentThesisEngine  # noqa: E402
from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402

_CODE_VALUE_RE = re.compile(r"^([a-z0-9_]+)=(-?\d+(?:\.\d+)?)$", re.I)


def _parse_code_features(codes: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for raw in codes:
        m = _CODE_VALUE_RE.match(str(raw).strip())
        if m:
            try:
                out[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                continue
    return out


def _regime_from_row(row: Dict[str, Any]) -> str:
    codes = row.get("policy_reason_codes") or []
    if isinstance(codes, list):
        for c in codes:
            if str(c).startswith("regime="):
                return str(c).split("=", 1)[1].lower()
    for key in ("regime", "market_type"):
        v = row.get(key)
        if v:
            return str(v).lower()
    return "unknown"


def _is_b4_row(row: Dict[str, Any]) -> bool:
    codes = row.get("policy_reason_codes") or []
    if not isinstance(codes, list):
        return False
    code_set = {str(c) for c in codes}
    reject = str(row.get("reject") or "")
    ml_pass = reject in ("gates_passed_long", "gates_passed_short")
    flat = "hypothesis_no_rule_fired" in code_set or "thesis_no_rule_fired" in code_set
    policy_hold = str(row.get("signal") or "HOLD").upper() == "HOLD"
    return ml_pass and flat and policy_hold


def _features_for_row(row: Dict[str, Any]) -> Dict[str, float]:
    features: Dict[str, float] = {}
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    raw_feat = extra.get("features") or row.get("features")
    if isinstance(raw_feat, dict):
        for k, v in raw_feat.items():
            try:
                features[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    codes = row.get("policy_reason_codes") or []
    if isinstance(codes, list):
        features.update(_parse_code_features([str(c) for c in codes]))
    return features


def analyze_b4_misses(
    rows: List[Dict[str, Any]],
    *,
    engine: Optional[AgentThesisEngine] = None,
) -> Dict[str, Any]:
    """Aggregate nearest-miss diagnostics for B4 telemetry rows."""
    eng = engine or AgentThesisEngine()
    by_regime: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "b4_count": 0,
            "nearest_rule": Counter(),
            "nearest_blocker": Counter(),
            "blocker_totals": Counter(),
            "samples": [],
        }
    )
    global_nearest_rule = Counter()
    global_nearest_blocker = Counter()
    global_blocker_totals = Counter()
    b4_total = 0

    for row in rows:
        if not _is_b4_row(row):
            continue
        b4_total += 1
        regime = _regime_from_row(row)
        features = _features_for_row(row)
        if not features:
            continue

        misses = eng.diagnose_rule_miss(features, regime, short_enabled=True)
        nearest = eng.nearest_rule_miss(features, regime, short_enabled=True)
        bucket = by_regime[regime]
        bucket["b4_count"] += 1

        for miss in misses:
            key = f"{miss.rule}:{miss.blocker}"
            bucket["blocker_totals"][key] += 1
            global_blocker_totals[key] += 1

        if nearest:
            rule_key = f"{nearest.rule}:{nearest.direction}"
            blocker_key = f"{nearest.rule}:{nearest.blocker}"
            bucket["nearest_rule"][rule_key] += 1
            bucket["nearest_blocker"][blocker_key] += 1
            global_nearest_rule[rule_key] += 1
            global_nearest_blocker[blocker_key] += 1
            if len(bucket["samples"]) < 10:
                bucket["samples"].append(
                    {
                        "ts": row.get("ts"),
                        "nearest_rule": rule_key,
                        "nearest_blocker": nearest.blocker,
                        "gap": round(nearest.gap, 4),
                        "value": round(nearest.value, 4),
                        "threshold": round(nearest.threshold, 4),
                        "adx_14": features.get("adx_14"),
                        "h_trend": features.get("h_trend"),
                        "h1_trend": features.get("h1_trend"),
                    }
                )

    regime_summary = {}
    for regime, data in sorted(by_regime.items()):
        regime_summary[regime] = {
            "b4_count": data["b4_count"],
            "nearest_rule": dict(data["nearest_rule"].most_common(10)),
            "nearest_blocker": dict(data["nearest_blocker"].most_common(10)),
            "blocker_totals": dict(data["blocker_totals"].most_common(15)),
            "samples": data["samples"],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "b4_total": b4_total,
        "nearest_rule": dict(global_nearest_rule.most_common(10)),
        "nearest_blocker": dict(global_nearest_blocker.most_common(10)),
        "blocker_totals": dict(global_blocker_totals.most_common(20)),
        "by_regime": regime_summary,
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Thesis Rule Miss Analysis",
        "",
        f"Generated: {report.get('generated_at')}",
        f"B4 cycles analyzed: **{report.get('b4_total')}**",
        "",
        "## Global nearest miss",
        "",
        "| Rule | Count |",
        "|------|------:|",
    ]
    for rule, count in (report.get("nearest_rule") or {}).items():
        lines.append(f"| {rule} | {count} |")

    lines.extend(["", "## Top blockers", "", "| Blocker | Count |", "|---------|------:|"])
    for blocker, count in (report.get("nearest_blocker") or {}).items():
        lines.append(f"| {blocker} | {count} |")

    for regime, data in (report.get("by_regime") or {}).items():
        lines.extend(
            [
                "",
                f"## Regime: {regime}",
                "",
                f"B4 count: {data.get('b4_count')}",
                "",
                "### Nearest rule",
                "",
            ]
        )
        for rule, count in (data.get("nearest_rule") or {}).items():
            lines.append(f"- {rule}: {count}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Default: data/investigation/thesis_rule_miss_<date>.json",
    )
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_json = args.out_json or (
        ROOT / "data" / "investigation" / f"thesis_rule_miss_{date_tag}.json"
    )
    out_md = args.out_md or (
        ROOT / "data" / "investigation" / f"thesis_rule_miss_{date_tag}.md"
    )

    rows = filter_since(load_telemetry(args.telemetry), args.hours)
    report = {
        "window_hours": args.hours,
        "telemetry_path": str(args.telemetry),
        **analyze_b4_misses(rows),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({"b4_total": report["b4_total"], "out_json": str(out_json)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
