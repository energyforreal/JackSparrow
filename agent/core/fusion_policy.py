"""Deterministic Layer-2 gates: validated multi-horizon forecast → trade duration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_NAMES,
    FUSION_DURATION_ATR_MULT,
    FUSION_GRADE_HIGH,
    FUSION_GRADE_LOW,
    FUSION_GRADE_MEDIUM,
    FUSION_HORIZON_KEYS,
    FUSION_HORIZON_MINUTES,
    FUSION_MIN_PROBABILITY,
    FUSION_POSITION_HOLD,
    FUSION_POSITION_LONG,
    FUSION_POSITION_SHORT,
)

_DECISION_PATH = "mtf_fusion"
_ENTRY = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_ACCEPTED_GRADES = frozenset({FUSION_GRADE_HIGH, FUSION_GRADE_MEDIUM})


@dataclass
class HorizonRung:
    """One Layer-2 head after calibration and frozen OOS gates."""

    key: str
    position: str
    probability: float
    validation_confidence: str
    accepted: bool
    dir_id: int
    dir_name: str
    probs: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FusionVerdict:
    signal: str
    confidence: float
    duration_key: str
    duration_minutes: int
    reason_codes: List[str]
    size_fraction: float
    sl_atr_mult: float
    tp_atr_mult: float
    fusion_weights: Dict[str, float]
    horizons: Dict[str, HorizonRung]
    thesis: str

    def to_horizon_forecast(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, rung in self.horizons.items():
            minutes = int(FUSION_HORIZON_MINUTES.get(key, 0))
            label = f"{minutes}m" if minutes < 60 else ("1h" if minutes == 60 else "2h")
            out[label] = {
                "Position": rung.position,
                "Probability": round(float(rung.probability) * 100.0, 1),
                "Validation confidence": rung.validation_confidence,
                "accepted": rung.accepted,
            }
        return out


def _softmax_weights(raw: Sequence[float], names: Sequence[str]) -> Dict[str, float]:
    import math

    xs = [float(x) for x in raw]
    m = max(xs) if xs else 0.0
    exps = [math.exp(x - m) for x in xs]
    s = sum(exps) or 1.0
    return {str(n): float(e / s) for n, e in zip(names, exps)}


def decode_dir_probs(logits: Sequence[float]) -> Dict[str, float]:
    import math

    xs = [float(x) for x in logits]
    m = max(xs) if xs else 0.0
    exps = [math.exp(x - m) for x in xs]
    s = sum(exps) or 1.0
    probs = [e / s for e in exps]
    return {FUSION_DIRECTION_NAMES[i]: float(p) for i, p in enumerate(probs)}


def apply_temperature(logits: Sequence[float], temperature: float) -> List[float]:
    t = max(float(temperature), 1e-6)
    return [float(x) / t for x in logits]


def rung_from_logits(
    key: str,
    logits: Sequence[float],
    *,
    temperature: float,
    min_probability: float,
    validation_confidence: str,
    accepted_grades: Sequence[str] | None = None,
) -> HorizonRung:
    scaled = apply_temperature(logits, temperature)
    probs = decode_dir_probs(scaled)
    dir_id = int(max(range(len(scaled)), key=lambda i: scaled[i]))
    dir_name = FUSION_DIRECTION_NAMES.get(dir_id, "NEUTRAL")
    probability = float(probs.get(dir_name, 0.0))
    if dir_name == "BULL":
        position = FUSION_POSITION_LONG
    elif dir_name == "BEAR":
        position = FUSION_POSITION_SHORT
    else:
        position = FUSION_POSITION_HOLD
    grades = set(accepted_grades or _ACCEPTED_GRADES)
    grade = str(validation_confidence or FUSION_GRADE_LOW).upper()
    accepted = (
        position != FUSION_POSITION_HOLD
        and probability >= float(min_probability)
        and grade in grades
        and grade != FUSION_GRADE_LOW
    )
    return HorizonRung(
        key=key,
        position=position,
        probability=probability,
        validation_confidence=grade,
        accepted=accepted,
        dir_id=dir_id,
        dir_name=dir_name,
        probs=probs,
    )


def evaluate_horizon_forecast(
    horizon_logits: Mapping[str, Sequence[float]],
    *,
    gates: Mapping[str, Any],
    fusion_logits: Sequence[float] | None = None,
    fusion_tf_names: Sequence[str] = ("5m", "10m", "30m", "1h", "2h"),
    min_probability: float = FUSION_MIN_PROBABILITY,
    size_floor: float = 0.35,
    max_position_size: float = 0.1,
) -> FusionVerdict:
    """Apply frozen per-horizon gates. Do not pick the highest probability."""
    horizons: Dict[str, HorizonRung] = {}
    gate_map = dict(gates.get("horizons") or gates)
    reasons: List[str] = []
    for key in FUSION_HORIZON_KEYS:
        raw = horizon_logits.get(key) or [0.0, 1.0, 0.0]
        meta = dict(gate_map.get(key) or {})
        rung = rung_from_logits(
            key,
            raw,
            temperature=float(meta.get("temperature") or 1.0),
            min_probability=float(meta.get("min_probability") or min_probability),
            validation_confidence=str(
                meta.get("validation_confidence") or FUSION_GRADE_LOW
            ),
            accepted_grades=meta.get("accepted_grades"),
        )
        horizons[key] = rung
        if not rung.accepted:
            reasons.append(f"{key}_rejected_{rung.validation_confidence.lower()}")

    longs = [k for k, r in horizons.items() if r.accepted and r.position == FUSION_POSITION_LONG]
    shorts = [k for k, r in horizons.items() if r.accepted and r.position == FUSION_POSITION_SHORT]
    order = list(FUSION_HORIZON_KEYS)

    signal = "HOLD"
    duration_key = ""
    thesis = "flat"
    confidence = 0.0
    sl_mult, tp_mult = 1.0, 1.5

    if longs and shorts:
        reasons.append("horizon_conflict")
        thesis = "conflicted"
    elif not longs and not shorts:
        reasons.append("no_accepted_horizon")
        thesis = "flat"
    else:
        side_keys = longs or shorts
        duration_key = max(side_keys, key=lambda k: order.index(k))
        rung = horizons[duration_key]
        thesis = "long" if rung.position == FUSION_POSITION_LONG else "short"
        signal = "BUY" if thesis == "long" else "SELL"
        if rung.validation_confidence == FUSION_GRADE_HIGH:
            signal = "STRONG_BUY" if thesis == "long" else "STRONG_SELL"
        confidence = float(rung.probability)
        sl_mult, tp_mult = FUSION_DURATION_ATR_MULT.get(duration_key, (1.0, 1.5))
        reasons.append(f"duration_{duration_key}")

    duration_minutes = int(FUSION_HORIZON_MINUTES.get(duration_key, 0)) if duration_key else 0
    size = 0.0
    if signal in _ENTRY:
        size = float(max(size_floor, min(max_position_size, max_position_size * confidence)))
    weights = _softmax_weights(fusion_logits or [0.0] * 5, fusion_tf_names)
    return FusionVerdict(
        signal=signal,
        confidence=confidence,
        duration_key=duration_key,
        duration_minutes=duration_minutes,
        reason_codes=reasons,
        size_fraction=size,
        sl_atr_mult=float(sl_mult),
        tp_atr_mult=float(tp_mult),
        fusion_weights=weights,
        horizons=horizons,
        thesis=thesis,
    )


def build_fusion_execution_plan(verdict: FusionVerdict) -> Dict[str, Any]:
    """ATR-scaled brackets for the chosen duration. No MFE/MAE path heads."""
    if verdict.signal not in _ENTRY:
        return {}
    return {
        "signal": verdict.signal,
        "primary_tf": verdict.duration_key,
        "duration_key": verdict.duration_key,
        "duration_minutes": verdict.duration_minutes,
        "max_hold_minutes": verdict.duration_minutes,
        "size_fraction": verdict.size_fraction,
        "size_scale": 1.0,
        "sl_tp_source": "atr",
        "sl_atr_mult": verdict.sl_atr_mult,
        "tp_atr_mult": verdict.tp_atr_mult,
        "reason_codes": list(verdict.reason_codes),
        "confidence": verdict.confidence,
    }


def multi_tf_from_horizons(verdict: FusionVerdict) -> Dict[str, Any]:
    """UI payload keyed by horizon, not by independently trained models."""
    out: Dict[str, Any] = {}
    for key, rung in verdict.horizons.items():
        local = "HOLD"
        direction = "neutral"
        if rung.position == FUSION_POSITION_LONG:
            local = "BUY"
            direction = "bullish"
        elif rung.position == FUSION_POSITION_SHORT:
            local = "SELL"
            direction = "bearish"
        out[key] = {
            "tf_key": key,
            "resolution": key,
            "local_signal": local if rung.accepted else "HOLD",
            "direction": direction,
            "position": rung.position,
            "confidence": rung.probability,
            "validation_confidence": rung.validation_confidence,
            "accepted": rung.accepted,
            "dir_probs": rung.probs,
        }
    return out
