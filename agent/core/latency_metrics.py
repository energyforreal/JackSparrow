"""Lightweight latency histograms for trading pipeline SLO monitoring."""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional

_lock_samples: Deque[float] = deque(maxlen=500)
_risk_to_fill_ms: Deque[float] = deque(maxlen=500)


def record_risk_to_fill_ms(duration_ms: float) -> None:
    if duration_ms >= 0:
        _risk_to_fill_ms.append(float(duration_ms))


def _percentile(samples: List[float], pct: float) -> Optional[float]:
    if not samples:
        return None
    ordered = sorted(samples)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def latency_snapshot() -> Dict[str, Any]:
    risk_samples = list(_risk_to_fill_ms)
    return {
        "risk_approved_to_fill_ms": {
            "count": len(risk_samples),
            "p50": _percentile(risk_samples, 50),
            "p95": _percentile(risk_samples, 95),
            "p99": _percentile(risk_samples, 99),
            "max": max(risk_samples) if risk_samples else None,
        },
    }
