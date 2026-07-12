#!/usr/bin/env python3
"""Nearest-miss thesis rule diagnostics with provenance-aware enrichment."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.agent_thesis_engine import AgentThesisEngine  # noqa: E402
from scripts.signal_recovery.decision_evidence import (  # noqa: E402
    EnrichedDecisionRecord,
    enrich_from_sources,
    feature_dict_for_engine,
    filter_high_confidence,
    load_enriched_ndjson,
    provenance_report,
)
from scripts.signal_recovery.log_parser import filter_since, load_telemetry  # noqa: E402

import re

_CODE_VALUE_RE = re.compile(r"^([a-z0-9_]+)=(-?\d+(?:\.\d+)?)$", re.I)


def _ml_direction_from_reject(reject: Optional[str]) -> str:
    """Map handler/gate reject tag to the ML side that passed gates."""
    tag = str(reject or "").lower()
    if "gates_passed_short" in tag or tag.endswith("_short"):
        return "SHORT"
    return "LONG"


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
    """Legacy telemetry-only analysis (may bias via missing defaults)."""
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
        "legacy_warning": (
            "Telemetry-only analysis may bias misses via default feature values."
        ),
    }


def analyze_b4_misses_enriched(
    records: List[EnrichedDecisionRecord],
    *,
    engine: Optional[AgentThesisEngine] = None,
    high_confidence_only: bool = True,
) -> Dict[str, Any]:
    """Phase B: threshold diagnostics on enriched records."""
    eng = engine or AgentThesisEngine()
    b4_all = [r for r in records if r.bucket == "B4"]
    b4_work = filter_high_confidence(b4_all) if high_confidence_only else b4_all
    coverage = provenance_report(records)

    by_regime: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "b4_count": 0,
            "nearest_rule": Counter(),
            "nearest_blocker": Counter(),
            "blocker_observed": Counter(),
            "samples": [],
        }
    )
    global_nearest_rule = Counter()
    global_nearest_blocker = Counter()
    global_blocker_observed = Counter()
    blocker_feature_hits: Dict[str, int] = defaultdict(int)
    blocker_feature_observed: Dict[str, int] = defaultdict(int)

    for rec in b4_work:
        regime = rec.regime
        features = feature_dict_for_engine(rec)
        if not features:
            continue
        ml_dir = _ml_direction_from_reject(rec.reject)
        # Diagnose both sides for coverage, but rank nearest only on the ML side
        # so SHORT h_trend sign-gaps do not swamp LONG thesis research.
        misses = eng.diagnose_rule_miss(features, regime, short_enabled=True)
        side_misses = [m for m in misses if str(m.direction).upper() == ml_dir]
        nearest = (
            min(side_misses, key=lambda m: m.gap) if side_misses else None
        )
        bucket = by_regime[regime]
        bucket["b4_count"] += 1

        for miss in side_misses:
            key = f"{miss.rule}:{miss.blocker}"
            global_blocker_observed[key] += 1
            blocker_feature_hits[miss.blocker] += 1
            blocker_feature_observed[miss.blocker] += 1

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
                        "ts": rec.ts,
                        "ml_direction": ml_dir,
                        "nearest_rule": rule_key,
                        "nearest_blocker": nearest.blocker,
                        "gap": round(nearest.gap, 4),
                        "value": round(nearest.value, 4),
                        "threshold": round(nearest.threshold, 4),
                        "provenance": {
                            k: v.source for k, v in rec.features.items() if v.observed
                        },
                    }
                )

    n_work = len(b4_work)
    n_all = len(b4_all)
    blocker_coverage_rows = []
    for blocker, hits in global_blocker_observed.most_common(20):
        obs = blocker_feature_observed.get(blocker, hits)
        blocker_coverage_rows.append(
            {
                "blocker": blocker,
                "miss_count": hits,
                "miss_pct_of_analyzed": round(hits / max(n_work, 1) * 100.0, 2),
                "coverage_observed": f"{obs}/{n_all}",
            }
        )

    regime_summary = {}
    for regime, data in sorted(by_regime.items()):
        regime_summary[regime] = {
            "b4_count": data["b4_count"],
            "nearest_rule": dict(data["nearest_rule"].most_common(10)),
            "nearest_blocker": dict(data["nearest_blocker"].most_common(10)),
            "samples": data["samples"],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "B_threshold_diagnostics",
        "high_confidence_only": high_confidence_only,
        "b4_total": n_all,
        "b4_analyzed": n_work,
        "coverage": coverage,
        "nearest_rule": dict(global_nearest_rule.most_common(10)),
        "nearest_blocker": dict(global_nearest_blocker.most_common(10)),
        "blocker_coverage": blocker_coverage_rows,
        "by_regime": regime_summary,
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    cov = report.get("coverage") or {}
    lines = [
        "# Thesis Rule Miss Analysis (Provenance-Aware)",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Phase: {report.get('phase', 'legacy')}",
        "",
        "## Coverage",
        "",
        f"- Total B4: {cov.get('total_b4', report.get('b4_total'))}",
        f"- High-confidence analyzed: {report.get('b4_analyzed', report.get('b4_total'))}",
        f"- High-confidence fraction: {cov.get('high_confidence_fraction_pct')}%",
        f"- Sweep gate: **{cov.get('sweep_gate', 'N/A')}**",
        "",
        "## Blocker coverage",
        "",
        "| Blocker | Miss % (analyzed) | Coverage (obs/total) |",
        "|---------|------------------:|---------------------:|",
    ]
    for row in report.get("blocker_coverage") or []:
        lines.append(
            f"| {row.get('blocker')} | {row.get('miss_pct_of_analyzed')} | "
            f"{row.get('coverage_observed')} |"
        )
    lines.extend(["", "## Nearest rule", ""])
    for rule, count in (report.get("nearest_rule") or {}).items():
        lines.append(f"- {rule}: {count}")
    if report.get("legacy_warning"):
        lines.extend(["", f"**Warning:** {report['legacy_warning']}"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument("--evidence-json", type=Path, default=None)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument(
        "--telemetry",
        type=Path,
        default=ROOT / "logs" / "agent" / "signal_recovery" / "decision_telemetry.ndjson",
    )
    parser.add_argument("--legacy-telemetry-only", action="store_true")
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_json = args.out_json or (
        ROOT / "data" / "investigation" / f"thesis_rule_miss_{date_tag}.json"
    )
    out_md = args.out_md or (
        ROOT / "data" / "investigation" / f"thesis_rule_miss_{date_tag}.md"
    )

    if args.legacy_telemetry_only:
        rows = filter_since(load_telemetry(args.telemetry), args.hours)
        report = {
            "window_hours": args.hours,
            "telemetry_path": str(args.telemetry),
            "phase": "legacy",
            **analyze_b4_misses(rows),
        }
    else:
        if args.evidence_json and args.evidence_json.is_file():
            records = load_enriched_ndjson(args.evidence_json)
        else:
            log_path = args.log
            if log_path is None:
                inv = ROOT / "data" / "investigation"
                cands = sorted(inv.glob("agent_exp_shadow_*.log"), reverse=True)
                log_path = cands[0] if cands else None
            if log_path is None or not log_path.is_file():
                print("Provide --evidence-json or --log for enriched analysis", file=sys.stderr)
                return 1
            records = enrich_from_sources(
                telemetry_path=args.telemetry,
                log_path=log_path,
                hours=args.hours,
            )
        report = {
            "window_hours": args.hours,
            "phase_a_records": len(records),
            **analyze_b4_misses_enriched(records),
        }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(_render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "b4_total": report.get("b4_total"),
                "b4_analyzed": report.get("b4_analyzed"),
                "sweep_gate": (report.get("coverage") or {}).get("sweep_gate"),
                "out_json": str(out_json),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
