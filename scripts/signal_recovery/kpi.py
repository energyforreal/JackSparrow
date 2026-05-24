"""KPI helpers for JackSparrow signal-recovery plan."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence


ACTIONABLE_SIGNALS = frozenset(
    {
        "BUY",
        "STRONG_BUY",
        "SELL",
        "STRONG_SELL",
        "WEAK_BUY",
        "WEAK_SELL",
    }
)


def decision_entropy(signals: Sequence[str]) -> float:
    """Shannon entropy (nats) over signal labels."""
    if not signals:
        return 0.0
    counts = Counter(str(s).upper() for s in signals)
    total = float(sum(counts.values()))
    ent = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            ent -= p * math.log(p)
    return float(ent)


def hold_ratio(signals: Sequence[str]) -> float:
    if not signals:
        return 0.0
    holds = sum(1 for s in signals if str(s).upper() == "HOLD")
    return holds / len(signals)


def actionable_rate(signals: Sequence[str]) -> float:
    if not signals:
        return 0.0
    n = sum(1 for s in signals if str(s).upper() in ACTIONABLE_SIGNALS)
    return n / len(signals)


def std_or_zero(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    var = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return float(math.sqrt(max(0.0, var)))


def compute_baseline_kpis(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate KPIs from telemetry or parsed log rows."""
    signals = [str(r.get("signal", "HOLD")) for r in rows]
    confs = [float(r["confidence"]) for r in rows if r.get("confidence") is not None]
    er = [float(r["expected_return"]) for r in rows if r.get("expected_return") is not None]
    collapse = [
        float(r["v43_collapse_rate"]) for r in rows if r.get("v43_collapse_rate") is not None
    ]
    trade_scores = [float(r["trade_score"]) for r in rows if r.get("trade_score") is not None]
    return {
        "sample_count": len(rows),
        "decision_entropy": decision_entropy(signals),
        "hold_ratio": hold_ratio(signals),
        "actionable_rate": actionable_rate(signals),
        "confidence_std": std_or_zero(confs),
        "expected_return_std": std_or_zero(er),
        "confidence_mean": float(sum(confs) / len(confs)) if confs else None,
        "expected_return_mean": float(sum(er) / len(er)) if er else None,
        "v43_collapse_rate_mean": float(sum(collapse) / len(collapse)) if collapse else None,
        "trade_score_mean": float(sum(trade_scores) / len(trade_scores))
        if trade_scores
        else None,
        "signal_histogram": dict(Counter(signals)),
    }


def compare_kpis(
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """Delta table for ablation / promotion review."""
    keys = (
        "decision_entropy",
        "hold_ratio",
        "actionable_rate",
        "confidence_std",
        "expected_return_std",
    )

    def _delta(k: str) -> Optional[float]:
        b, c = baseline.get(k), candidate.get(k)
        if b is None or c is None:
            return None
        try:
            return float(c) - float(b)
        except (TypeError, ValueError):
            return None

    return {k: {"baseline": baseline.get(k), "candidate": candidate.get(k), "delta": _delta(k)} for k in keys}
