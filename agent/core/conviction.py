"""Conviction scoring and position-size fraction from evidence."""

from __future__ import annotations

from typing import Dict, Optional

from agent.core.config import settings
from agent.core.evidence_types import ConvictionResult, EvidenceBundle, EvidenceDimension
from agent.core.signal_vocabulary import is_long_signal, is_short_signal, normalize_signal

_DEFAULT_WEIGHTS: Dict[str, float] = {
    EvidenceDimension.TREND.value: 0.15,
    EvidenceDimension.LIQUIDITY.value: 0.10,
    EvidenceDimension.BREAKOUT.value: 0.12,
    EvidenceDimension.MOMENTUM.value: 0.10,
    EvidenceDimension.FUNDING.value: 0.08,
    EvidenceDimension.REGIME.value: 0.12,
    EvidenceDimension.STRUCTURE.value: 0.10,
    EvidenceDimension.ML_EDGE.value: 0.13,
    EvidenceDimension.MODEL_CERTAINTY.value: 0.10,
    EvidenceDimension.HORIZON_ALIGNMENT.value: 0.10,
}


def _conviction_weights() -> Dict[str, float]:
    weights = dict(_DEFAULT_WEIGHTS)
    override = getattr(settings, "conviction_dimension_weights", None)
    if isinstance(override, dict):
        for k, v in override.items():
            try:
                weights[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def compute_conviction(
    bundle: EvidenceBundle,
    direction: Optional[str] = None,
    *,
    dominant_thesis_type: Optional[str] = None,
    collapse_rate: Optional[float] = None,
) -> ConvictionResult:
    """Aggregate evidence into conviction and size_fraction (no multi-gate HOLD)."""
    weights = _conviction_weights()
    if collapse_rate is not None:
        cap = float(getattr(settings, "entry_quality_collapse_trust_cap", 0.95) or 0.95)
        ml_trust = max(0.05, 1.0 - min(cap, float(collapse_rate)))
        for key in (
            EvidenceDimension.ML_EDGE.value,
            EvidenceDimension.MODEL_CERTAINTY.value,
        ):
            if key in weights:
                weights[key] *= ml_trust
    dtype = str(dominant_thesis_type or "").strip().lower()
    if dtype == "breakout":
        weights[EvidenceDimension.BREAKOUT.value] = weights.get(
            EvidenceDimension.BREAKOUT.value, 0.12
        ) * 1.15
    elif dtype in ("trend_continuation", "basis_crowding", "funding_crowding"):
        weights[EvidenceDimension.TREND.value] = weights.get(
            EvidenceDimension.TREND.value, 0.15
        ) * 1.15
    elif dtype == "mean_reversion":
        weights[EvidenceDimension.MOMENTUM.value] = weights.get(
            EvidenceDimension.MOMENTUM.value, 0.10
        ) * 1.15
    total_w = sum(weights.values()) or 1.0
    weights = {k: v / total_w for k, v in weights.items()}
    dim_scores: Dict[str, float] = {}
    weighted_sum = 0.0
    weight_used = 0.0
    for key, w in weights.items():
        score = bundle.get(key, 0.5)
        dim_scores[key] = score
        weighted_sum += score * w
        weight_used += w
    conviction = weighted_sum / weight_used if weight_used > 0 else 0.5

    entry_floor = float(getattr(settings, "conviction_entry_floor", 0.35) or 0.35)
    size_floor = float(getattr(settings, "conviction_size_floor", 0.25) or 0.25)
    size_ceil = float(getattr(settings, "conviction_size_ceil", 1.0) or 1.0)

    dir_norm = normalize_signal(direction) if direction else "HOLD"
    reasons: list[str] = []
    below_floor = conviction < entry_floor
    if below_floor:
        reasons.append(f"conviction_below_entry_floor={conviction:.3f}<{entry_floor:.2f}")

    if below_floor or not (is_long_signal(dir_norm) or is_short_signal(dir_norm)):
        return ConvictionResult(
            conviction=conviction,
            direction=dir_norm if dir_norm != "HOLD" else None,
            size_fraction=0.0,
            dimensions=dim_scores,
            reason_codes=reasons + (["no_direction"] if dir_norm == "HOLD" else []),
            below_entry_floor=below_floor,
        )

    raw_frac = size_floor + (size_ceil - size_floor) * conviction
    size_fraction = max(size_floor, min(size_ceil, raw_frac))
    reasons.append(f"conviction_sizing={conviction:.3f}->size_fraction={size_fraction:.3f}")

    return ConvictionResult(
        conviction=conviction,
        direction=dir_norm,
        size_fraction=size_fraction,
        dimensions=dim_scores,
        reason_codes=reasons,
        below_entry_floor=False,
    )


def confluence_score_to_size_multiplier(score_0_100: float) -> float:
    """Map legacy 0–100 trade score to size multiplier (no hard veto)."""
    size_floor = float(getattr(settings, "conviction_size_floor", 0.25) or 0.25)
    try:
        s = max(0.0, min(100.0, float(score_0_100)))
    except (TypeError, ValueError):
        return size_floor
    ref_min = float(getattr(settings, "agent_trade_score_min", 35.0) or 35.0)
    if s >= ref_min:
        return min(1.0, size_floor + (1.0 - size_floor) * (s - ref_min) / max(100.0 - ref_min, 1.0))
    span = max(ref_min, 1.0)
    return max(size_floor, size_floor * (s / span))


def structural_confidence_to_fraction(
    structural_confidence: float,
    entry_signal: str,
) -> float:
    """Map rule-based structural confidence (0–1) to position size fraction."""
    dir_norm = normalize_signal(entry_signal) if entry_signal else "HOLD"
    if not (is_long_signal(dir_norm) or is_short_signal(dir_norm)):
        return 0.0
    size_floor = float(getattr(settings, "conviction_size_floor", 0.25) or 0.25)
    size_ceil = float(getattr(settings, "conviction_size_ceil", 1.0) or 1.0)
    try:
        conf = max(0.0, min(1.0, float(structural_confidence)))
    except (TypeError, ValueError):
        conf = 0.5
    entry_floor = float(getattr(settings, "conviction_entry_floor", 0.35) or 0.35)
    if conf < entry_floor:
        return 0.0
    return max(size_floor, min(size_ceil, size_floor + (size_ceil - size_floor) * conf))
