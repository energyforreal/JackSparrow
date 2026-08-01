"""Layered cross-timeframe decision policy for per-TF transformer ensemble."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from agent.core.config import settings
from agent.models.transformer_context_builder import (
    _head_confidence,
    _uncertainty_scale,
    estimate_uncertainty,
    map_prediction_to_signal,
    map_vol_regime_to_agent_regime,
)

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_BULLISH = frozenset({"BUY", "STRONG_BUY"})
_BEARISH = frozenset({"SELL", "STRONG_SELL"})

TF_RESOLUTION_MAP: Dict[str, str] = {
    "tf_5m": "5m",
    "tf_15m": "15m",
    "tf_30m": "30m",
    "tf_1h": "1h",
    "tf_2h": "2h",
}

DEFAULT_TF_WEIGHTS: Dict[str, float] = {
    "tf_5m": 0.10,
    "tf_15m": 0.25,
    "tf_30m": 0.25,
    "tf_1h": 0.20,
    "tf_2h": 0.20,
}


@dataclass
class TfLocalStance:
    """Per-timeframe interpretation of one transformer model output."""

    tf_key: str
    resolution: str
    local_signal: str
    direction: str
    future_return: float
    threshold: float
    vol_regime: str
    regime: str
    confidence: float
    quality: str
    risk: str
    trend_strength: float
    mfe: float
    mae: float
    future_volatility: float
    reason_codes: List[str] = field(default_factory=list)
    model_name: str = ""


@dataclass
class MtfPolicyResult:
    """Final aggregated decision from multi-TF transformer ensemble."""

    signal: str
    confidence: float
    reason_codes: List[str]
    multi_tf_stances: Dict[str, TfLocalStance]
    cross_tf_summary: Dict[str, Any]
    primary_future_return: float
    primary_threshold: float
    primary_regime: str


def _parse_tf_list(raw: str) -> List[str]:
    keys: List[str] = []
    for part in (raw or "").split(","):
        token = part.strip().lower()
        if not token:
            continue
        if token.startswith("tf_"):
            keys.append(token)
        else:
            keys.append(f"tf_{token}")
    return keys


def _direction_from_signal(signal: str) -> str:
    if signal in _BULLISH:
        return "bullish"
    if signal in _BEARISH:
        return "bearish"
    return "neutral"


def _quality_label(trend_strength: float, mfe: float, mae: float) -> str:
    ratio = mfe / (mae + 1e-6)
    if trend_strength >= 1.5 and ratio >= 1.5:
        return "high"
    if trend_strength >= 0.8 or ratio >= 1.0:
        return "medium"
    return "low"


def _risk_label(vol_regime: str) -> str:
    label = str(vol_regime or "NORMAL").upper()
    if label == "EXTREME":
        return "extreme"
    if label == "HIGH":
        return "elevated"
    return "normal"


def _resolve_threshold(bundle_metadata: Mapping[str, Any]) -> float:
    override = getattr(settings, "transformer_signal_threshold", None)
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    return float(bundle_metadata.get("default_threshold") or 0.005)


def _confidence_from_prediction(
    continuous: Mapping[str, float],
    vol_regime: str,
    future_return: float,
    threshold: float,
) -> float:
    future_vol = float(continuous.get("future_volatility", 0.0))
    mae = float(continuous.get("mae", 0.0))
    unc = estimate_uncertainty(
        future_volatility=future_vol,
        mae=mae,
        vol_regime=vol_regime,
    )
    u_scale = _uncertainty_scale(unc)
    edge = float(future_return) - float(threshold)
    return _head_confidence(edge, threshold, u_scale)


def interpret_tf_prediction(
    *,
    tf_key: str,
    prediction_context: Mapping[str, Any],
    bundle_metadata: Mapping[str, Any],
    model_name: str = "",
) -> TfLocalStance:
    """Map a single TF model output to a local stance."""
    resolution = TF_RESOLUTION_MAP.get(tf_key, tf_key.replace("tf_", ""))
    continuous = prediction_context.get("transformer_continuous_preds") or {}
    future_return = float(
        continuous.get("future_return")
        or prediction_context.get("expected_return", 0.0)
        or 0.0
    )
    vol_regime = str(
        prediction_context.get("transformer_vol_regime") or "NORMAL"
    )
    trend_strength = float(continuous.get("trend_strength", 0.0))
    mfe = float(continuous.get("mfe", 0.0))
    mae = float(continuous.get("mae", 0.0))
    future_vol = float(continuous.get("future_volatility", 0.0))
    regime = str(
        prediction_context.get("regime")
        or map_vol_regime_to_agent_regime(
            vol_regime,
            trend_strength=trend_strength,
            future_volatility=future_vol,
        )
    )
    threshold = _resolve_threshold(bundle_metadata)
    confidence = float(
        prediction_context.get("entry_confidence", 0.0)
        or _confidence_from_prediction(continuous, vol_regime, future_return, threshold)
    )
    local_signal, conf, reason_codes = map_prediction_to_signal(
        future_return=future_return,
        threshold=threshold,
        vol_regime=vol_regime,
        confidence=confidence,
        strong_edge_multiplier=float(
            getattr(settings, "transformer_strong_edge_multiplier", 1.5) or 1.5
        ),
        extreme_regime_veto=bool(
            getattr(settings, "transformer_extreme_regime_veto", True)
        ),
        min_confidence=float(getattr(settings, "transformer_min_confidence", 0.55) or 0.55),
    )
    return TfLocalStance(
        tf_key=tf_key,
        resolution=resolution,
        local_signal=local_signal,
        direction=_direction_from_signal(local_signal),
        future_return=future_return,
        threshold=threshold,
        vol_regime=vol_regime,
        regime=regime,
        confidence=conf,
        quality=_quality_label(trend_strength, mfe, mae),
        risk=_risk_label(vol_regime),
        trend_strength=trend_strength,
        mfe=mfe,
        mae=mae,
        future_volatility=future_vol,
        reason_codes=list(reason_codes),
        model_name=model_name,
    )


def _bias_allows(signal: str, bias_tfs: Sequence[str], stances: Mapping[str, TfLocalStance]) -> bool:
    if signal in _BULLISH:
        for key in bias_tfs:
            stance = stances.get(key)
            if stance and stance.direction == "bearish":
                return False
        return True
    if signal in _BEARISH:
        for key in bias_tfs:
            stance = stances.get(key)
            if stance and stance.direction == "bullish":
                return False
        return True
    return True


def _count_aligned(stances: Mapping[str, TfLocalStance], direction: str) -> int:
    return sum(1 for s in stances.values() if s.direction == direction)


def _downgrade_signal(signal: str) -> str:
    if signal == "STRONG_BUY":
        return "BUY"
    if signal == "STRONG_SELL":
        return "SELL"
    return "HOLD"


def _upgrade_signal(signal: str) -> str:
    if signal == "BUY":
        return "STRONG_BUY"
    if signal == "SELL":
        return "STRONG_SELL"
    return signal


def evaluate_mtf_policy(
    stances: Mapping[str, TfLocalStance],
  *,
  execution_tfs: Optional[Sequence[str]] = None,
  bias_tfs: Optional[Sequence[str]] = None,
  timing_tf: Optional[str] = None,
  extreme_veto_tfs: Optional[Sequence[str]] = None,
  min_tf_alignment: Optional[int] = None,
) -> MtfPolicyResult:
    """Apply layered cross-TF rules to per-TF local stances."""
    exec_keys = list(execution_tfs or _parse_tf_list(
        getattr(settings, "transformer_execution_tfs", "15m,30m")
    ))
    bias_keys = list(bias_tfs or _parse_tf_list(
        getattr(settings, "transformer_bias_tfs", "1h,2h")
    ))
    timing_key = timing_tf or f"tf_{getattr(settings, 'transformer_timing_tf', '5m')}"
    if not timing_key.startswith("tf_"):
        timing_key = f"tf_{timing_key}"
    veto_keys = list(extreme_veto_tfs or _parse_tf_list(
        getattr(settings, "transformer_extreme_veto_tfs", "1h,2h")
    ))
    min_align = int(
        min_tf_alignment
        if min_tf_alignment is not None
        else getattr(settings, "transformer_min_tf_alignment", 3) or 3
    )

    reason_codes: List[str] = []
    weights = DEFAULT_TF_WEIGHTS

    # Layer 4/5 early: extreme veto on bias TFs
    for key in veto_keys:
        stance = stances.get(key)
        if stance and stance.vol_regime.upper() == "EXTREME":
            reason_codes.append(f"mtf_{stance.resolution}_extreme_veto")
            summary = _build_summary(stances, signal="HOLD", alignment=0, trend_filter="veto")
            return MtfPolicyResult(
                signal="HOLD",
                confidence=0.0,
                reason_codes=reason_codes,
                multi_tf_stances=dict(stances),
                cross_tf_summary=summary,
                primary_future_return=0.0,
                primary_threshold=0.005,
                primary_regime="crisis",
            )

    # Layer 2: execution anchor from 15m/30m
    exec_signal = "HOLD"
    exec_stance: Optional[TfLocalStance] = None
    for key in exec_keys:
        stance = stances.get(key)
        if stance and stance.local_signal in _ENTRY_SIGNALS:
            exec_signal = stance.local_signal
            exec_stance = stance
            reason_codes.append(f"mtf_{stance.resolution}_execution_{stance.direction}")
            break

    if exec_signal == "HOLD":
        reason_codes.append("mtf_no_execution_signal")
        conf = _weighted_confidence(stances, weights)
        summary = _build_summary(stances, signal="HOLD", alignment=0, trend_filter="none")
        return MtfPolicyResult(
            signal="HOLD",
            confidence=conf,
            reason_codes=reason_codes,
            multi_tf_stances=dict(stances),
            cross_tf_summary=summary,
            primary_future_return=0.0,
            primary_threshold=0.005,
            primary_regime="neutral",
        )

    proposed = exec_signal
    direction = _direction_from_signal(proposed)

    # Layer 1: bias filter
    if not _bias_allows(proposed, bias_keys, stances):
        reason_codes.append("mtf_bias_veto")
        conf = _weighted_confidence(stances, weights)
        summary = _build_summary(stances, signal="HOLD", alignment=0, trend_filter="opposed")
        return MtfPolicyResult(
            signal="HOLD",
            confidence=conf,
            reason_codes=reason_codes,
            multi_tf_stances=dict(stances),
            cross_tf_summary=summary,
            primary_future_return=float(exec_stance.future_return if exec_stance else 0.0),
            primary_threshold=float(exec_stance.threshold if exec_stance else 0.005),
            primary_regime=str(exec_stance.regime if exec_stance else "neutral"),
        )

    trend_filter = "bullish" if direction == "bullish" else "bearish"

    # Layer 3: cross-TF alignment for STRONG signals
    aligned = _count_aligned(stances, direction)
    if proposed in ("STRONG_BUY", "STRONG_SELL"):
        if aligned < min_align:
            proposed = _downgrade_signal(proposed)
            reason_codes.append("mtf_insufficient_alignment_downgrade")
    elif aligned >= min_align:
        proposed = _upgrade_signal(proposed)
        reason_codes.append("mtf_alignment_upgrade")

    # Layer 4: 5m timing modifier
    timing = stances.get(timing_key)
    if timing:
        if timing.direction == direction:
            reason_codes.append("mtf_5m_timing_aligned")
        elif timing.direction != "neutral" and timing.direction != direction:
            proposed = _downgrade_signal(proposed)
            reason_codes.append("mtf_5m_timing_opposed_downgrade")

    # Layer 5: execution TF risk downgrade
    if exec_stance and exec_stance.risk == "elevated":
        proposed = _downgrade_signal(proposed)
        reason_codes.append(f"mtf_{exec_stance.resolution}_high_risk_downgrade")

    confidence = _weighted_confidence(stances, weights)
    if exec_stance:
        confidence = float(min(1.0, max(confidence, exec_stance.confidence * 0.85)))

    summary = _build_summary(
        stances,
        signal=proposed,
        alignment=aligned / max(len(stances), 1),
        trend_filter=trend_filter,
        dominant_tf=exec_stance.tf_key if exec_stance else "",
    )
    return MtfPolicyResult(
        signal=proposed,
        confidence=confidence,
        reason_codes=reason_codes,
        multi_tf_stances=dict(stances),
        cross_tf_summary=summary,
        primary_future_return=float(exec_stance.future_return if exec_stance else 0.0),
        primary_threshold=float(exec_stance.threshold if exec_stance else 0.005),
        primary_regime=str(exec_stance.regime if exec_stance else "neutral"),
    )


def _weighted_confidence(
    stances: Mapping[str, TfLocalStance],
    weights: Mapping[str, float],
) -> float:
    total_w = 0.0
    acc = 0.0
    for key, stance in stances.items():
        w = float(weights.get(key, 0.1))
        acc += w * float(stance.confidence)
        total_w += w
    if total_w <= 0:
        return 0.0
    return float(acc / total_w)


def _build_summary(
    stances: Mapping[str, TfLocalStance],
    *,
    signal: str,
    alignment: float,
    trend_filter: str,
    dominant_tf: str = "",
) -> Dict[str, Any]:
    any_extreme = any(s.vol_regime.upper() == "EXTREME" for s in stances.values())
    timing_tf = f"tf_{getattr(settings, 'transformer_timing_tf', '5m')}"
    if not timing_tf.startswith("tf_"):
        timing_tf = f"tf_{timing_tf}"
    timing = stances.get(timing_tf)
    entry_timing = "aligned" if timing and timing.direction == _direction_from_signal(signal) else "neutral"
    if timing and timing.direction not in ("neutral", _direction_from_signal(signal)):
        entry_timing = "opposed"
    return {
        "alignment_score": round(float(alignment), 4),
        "dominant_tf": dominant_tf or "tf_15m",
        "trend_filter": trend_filter,
        "entry_timing": entry_timing,
        "any_extreme_veto": any_extreme,
        "primary_execution_tf": f"tf_{getattr(settings, 'transformer_primary_execution_tf', '15m')}",
        "per_tf_direction": {k: v.direction for k, v in stances.items()},
    }


def resolution_to_tf_key(resolution: str) -> str:
    res = resolution.strip().lower()
    return f"tf_{res}"


def resolution_to_ctx_key(resolution: str) -> str:
    res = resolution.strip().lower()
    return f"v43_df{res}"
