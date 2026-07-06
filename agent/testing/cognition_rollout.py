"""Cognition authority rollout: regression dataset and replay summary metrics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Pinned regression set — all built-in scenarios for comparable stage diffs.
REGRESSION_SCENARIOS: tuple[str, ...] = (
    "strong_breakout",
    "fake_breakout",
    "chop_market",
    "liquidation_spike",
    "high_drawdown",
    "thesis_ml_disagreement",
    "high_confidence_bad_portfolio",
)

DEFAULT_SYMBOL = "BTCUSD"


@dataclass
class BarDecisionRecord:
    """Per-bar (or per-scenario) decision snapshot for rollout diffing."""

    bar_id: str
    policy_signal: str = "HOLD"
    thesis_signal: str = "HOLD"
    thesis_type: str = "flat"
    dominant_hypothesis: Optional[str] = None
    aggregate_direction: str = "FLAT"
    trade_score: float = 0.0
    ml_confirms: bool = False
    entry_quality_pass: bool = False
    expectation_dominant: Optional[str] = None
    expectation_confidence: float = 0.0
    eligible_profiles: List[str] = field(default_factory=list)
    decision_latency_ms: float = 0.0
    cognition_attach_failed: bool = False


@dataclass
class RolloutSummary:
    """Replay Summary artifact per rollout stage."""

    stage: str
    generated_at: str
    symbol: str
    bars_processed: int
    signals_changed: int = 0
    entries_changed: int = 0
    policy_changed: int = 0
    hypothesis_changed: int = 0
    trade_score_mean_delta: float = 0.0
    ml_confirms_delta: int = 0
    entry_quality_delta: int = 0
    decision_latency_p50_ms: float = 0.0
    decision_latency_p95_ms: float = 0.0
    avg_expectation_confidence: float = 0.0
    cognition_attach_failures: int = 0
    records: List[Dict[str, Any]] = field(default_factory=list)
    flags: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def record_from_scenario_trace(trace: Any) -> BarDecisionRecord:
    """Build a decision record from a ScenarioTrace."""
    policy_layer = trace.layer("policy_engine") or trace.layer("final_decision")
    thesis_layer = trace.layer("thesis")
    cognition_layer = trace.layer("cognition_cycle")
    trade_layer = trace.layer("trade_scorer")

    policy_out = policy_layer.output if policy_layer else {}
    thesis_out = thesis_layer.output if thesis_layer else {}
    cog_out = cognition_layer.output if cognition_layer else {}
    trade_out = trade_layer.output if trade_layer else {}

    ctx_obj = cog_out.get("_obj")
    dc = cog_out.get("decision_context_v3")
    if dc is None and ctx_obj is not None and hasattr(ctx_obj, "to_dict"):
        dc = ctx_obj.to_dict()
    if not isinstance(dc, dict):
        dc = {}
    exp = dc.get("expectation") if isinstance(dc.get("expectation"), dict) else {}
    if not exp and isinstance(cog_out.get("expectation"), dict):
        exp = cog_out["expectation"]
    hyp = thesis_out.get("hypothesis_snapshot") if isinstance(thesis_out.get("hypothesis_snapshot"), dict) else {}
    dom = hyp.get("dominant") if isinstance(hyp.get("dominant"), dict) else {}

    eq_pass = bool(
        policy_out.get("entry_quality_pass")
        or policy_out.get("passed")
        or trade_out.get("passed", False)
    )
    eligible = list(cog_out.get("eligible_strategy_profiles") or [])
    if not eligible and ctx_obj is not None and getattr(ctx_obj, "strategy_selection", None):
        eligible = list(ctx_obj.strategy_selection.eligible_ids())
    return BarDecisionRecord(
        bar_id=str(getattr(trace, "scenario_name", "unknown")),
        policy_signal=str(policy_out.get("signal") or "HOLD"),
        thesis_signal=str(thesis_out.get("signal") or thesis_out.get("thesis_signal") or "HOLD"),
        thesis_type=str(thesis_out.get("thesis_type") or "flat"),
        dominant_hypothesis=str(dom.get("thesis_type")) if dom.get("thesis_type") else None,
        aggregate_direction=str(hyp.get("aggregate_direction") or "FLAT"),
        trade_score=float(trade_out.get("score") or trade_out.get("trade_score") or 0.0),
        ml_confirms=bool(thesis_out.get("ml_confirms", False)),
        entry_quality_pass=eq_pass,
        expectation_dominant=exp.get("dominant_expectation"),
        expectation_confidence=float(exp.get("confidence") or 0.0),
        eligible_profiles=eligible,
        decision_latency_ms=float(getattr(trace, "total_ms", 0.0) or 0.0),
        cognition_attach_failed=bool(
            cog_out.get("attach_failed", False)
            or (cognition_layer is not None and not cognition_layer.ok)
        ),
    )


def build_summary_from_records(
    records: List[BarDecisionRecord],
    *,
    stage: str,
    symbol: str,
    flags: Optional[Dict[str, bool]] = None,
) -> RolloutSummary:
    latencies = [r.decision_latency_ms for r in records]
    exp_confs = [r.expectation_confidence for r in records if r.expectation_confidence > 0]
    return RolloutSummary(
        stage=stage,
        generated_at=datetime.now(timezone.utc).isoformat(),
        symbol=symbol,
        bars_processed=len(records),
        decision_latency_p50_ms=round(_percentile(latencies, 50), 2),
        decision_latency_p95_ms=round(_percentile(latencies, 95), 2),
        avg_expectation_confidence=round(sum(exp_confs) / len(exp_confs), 4) if exp_confs else 0.0,
        cognition_attach_failures=sum(1 for r in records if r.cognition_attach_failed),
        records=[asdict(r) for r in records],
        flags=dict(flags or {}),
    )


def diff_summaries(
    current: RolloutSummary,
    baseline: RolloutSummary,
) -> RolloutSummary:
    """Compute delta metrics vs a prior stage baseline."""
    base_by_id = {r["bar_id"]: r for r in baseline.records if isinstance(r, dict)}
    cur_by_id = {r["bar_id"]: r for r in current.records if isinstance(r, dict)}

    signals_changed = 0
    entries_changed = 0
    policy_changed = 0
    hypothesis_changed = 0
    ml_confirms_delta = 0
    entry_quality_delta = 0
    score_deltas: List[float] = []

    entry_signals = frozenset({"BUY", "SELL", "LONG", "SHORT"})

    for bar_id, cur in cur_by_id.items():
        base = base_by_id.get(bar_id)
        if not base:
            continue
        if cur.get("policy_signal") != base.get("policy_signal"):
            signals_changed += 1
            policy_changed += 1
            if cur.get("policy_signal") in entry_signals or base.get("policy_signal") in entry_signals:
                entries_changed += 1
        if cur.get("dominant_hypothesis") != base.get("dominant_hypothesis") or (
            cur.get("aggregate_direction") != base.get("aggregate_direction")
        ):
            hypothesis_changed += 1
        if bool(cur.get("ml_confirms")) != bool(base.get("ml_confirms")):
            ml_confirms_delta += 1
        if bool(cur.get("entry_quality_pass")) != bool(base.get("entry_quality_pass")):
            entry_quality_delta += 1
        try:
            score_deltas.append(float(cur.get("trade_score") or 0) - float(base.get("trade_score") or 0))
        except (TypeError, ValueError):
            pass

    mean_delta = sum(score_deltas) / len(score_deltas) if score_deltas else 0.0
    out = RolloutSummary(
        stage=current.stage,
        generated_at=current.generated_at,
        symbol=current.symbol,
        bars_processed=current.bars_processed,
        signals_changed=signals_changed,
        entries_changed=entries_changed,
        policy_changed=policy_changed,
        hypothesis_changed=hypothesis_changed,
        trade_score_mean_delta=round(mean_delta, 4),
        ml_confirms_delta=ml_confirms_delta,
        entry_quality_delta=entry_quality_delta,
        decision_latency_p50_ms=current.decision_latency_p50_ms,
        decision_latency_p95_ms=current.decision_latency_p95_ms,
        avg_expectation_confidence=current.avg_expectation_confidence,
        cognition_attach_failures=current.cognition_attach_failures,
        records=current.records,
        flags=current.flags,
    )
    return out


def write_summary(path: Path, summary: RolloutSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")


def load_summary(path: Path) -> RolloutSummary:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RolloutSummary(**{k: raw[k] for k in RolloutSummary.__dataclass_fields__ if k in raw})
