"""Advisory entry quality evaluator — replaces fragmented trade_score logic."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.core.config import settings
from agent.core.signal_vocabulary import is_entry_signal, same_direction
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)
from agent.core.v43_signal_gates import (
    gate5_long_edge_metrics,
    gate5_short_edge_metrics,
    round_trip_cost_pct,
)

_DIMENSION_WEIGHTS: Dict[str, float] = {
    "structural": 0.20,
    "ml": 0.20,
    "economic": 0.15,
    "regime": 0.10,
    "position_context": 0.10,
    "microstructure": 0.10,
    "trend_stability": 0.10,
    "signal_freshness": 0.05,
}

# Bounded post-trade calibration offsets (PR7).
_dimension_calibration: Dict[str, float] = {k: 0.0 for k in _DIMENSION_WEIGHTS}


@dataclass
class EntryQualityResult:
    """Advisory quality assessment — policy decides whether to trade."""

    quality_score: float
    passed: bool
    dimensions: Dict[str, float]
    reason_codes: List[str] = field(default_factory=list)
    required_ml_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "passed": self.passed,
            "dimensions": dict(self.dimensions),
            "reason_codes": list(self.reason_codes),
            "required_ml_confirmation": self.required_ml_confirmation,
        }


def _clamp01(value: float, floor: float = 0.0) -> float:
    return max(floor, min(1.0, float(value)))


def _effective_direction(
    strategy: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
) -> str:
    if strategy.direction != "FLAT":
        return strategy.direction
    if ml_validation.final_short and not ml_validation.final_long:
        return "SHORT"
    if ml_validation.final_long and not ml_validation.final_short:
        return "LONG"
    return "FLAT"


def _ml_trust(collapse_rate: Optional[float]) -> float:
    cap = float(getattr(settings, "entry_quality_collapse_trust_cap", 0.95) or 0.95)
    if collapse_rate is None:
        return 1.0
    cr = max(0.0, min(cap, float(collapse_rate)))
    return max(0.05, 1.0 - cr)


def _score_structural(
    strategy: StrategyCandidate,
    direction: str,
    ml_validation: MLValidationSnapshot,
    ml_confirms: bool,
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    if direction == "FLAT":
        return 0.0, ["quality_structural_flat"]
    base = _clamp01(strategy.confidence if strategy.direction != "FLAT" else 0.45)
    if strategy.direction != "FLAT":
        reasons.append("quality_structural_thesis")
    elif direction != "FLAT":
        reasons.append("quality_structural_ml_direction")
        base = 0.4
    if ml_confirms and strategy.direction != "FLAT" and same_direction(
        strategy.signal, "LONG" if direction == "LONG" else "SHORT"
    ):
        base = min(1.0, base + 0.15)
        reasons.append("quality_structural_ml_aligned")
    elif (ml_validation.final_long or ml_validation.final_short) and not ml_confirms:
        base *= 0.7
        reasons.append("quality_structural_ml_unconfirmed")
    return base, reasons


def _score_ml(
    ml_validation: MLValidationSnapshot,
    direction: str,
    collapse_rate: Optional[float],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    trust = _ml_trust(collapse_rate)
    if collapse_rate is not None and collapse_rate > 0.5:
        reasons.append(f"quality_ml_trust={trust:.3f}")
    gated = (
        ml_validation.final_long
        if direction == "LONG"
        else ml_validation.final_short
        if direction == "SHORT"
        else False
    )
    if not gated:
        return 0.35 * trust, reasons + ["quality_ml_gates_failed"]
    thr = (
        ml_validation.threshold
        if direction == "LONG"
        else ml_validation.short_threshold
    )
    edge = abs(ml_validation.expected_return) - thr
    raw = _clamp01(0.45 + edge * 25.0, 0.35)
    reasons.append("quality_ml_gated")
    return raw * trust, reasons


def _score_economic(
    ml_validation: MLValidationSnapshot,
    direction: str,
    market_context: Optional[Dict[str, Any]],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    mc = market_context if isinstance(market_context, dict) else {}
    g5_raw = mc.get("gate5_economic")
    if isinstance(g5_raw, dict) and "pass" in g5_raw:
        if g5_raw.get("pass"):
            return 0.85, ["quality_economic_gate5_pass"]
        return 0.25, ["quality_economic_gate5_fail"]
    proba = float(ml_validation.expected_return or 0.0)
    if direction == "LONG":
        metrics = gate5_long_edge_metrics(proba, ml_validation.threshold)
    elif direction == "SHORT":
        metrics = gate5_short_edge_metrics(proba, ml_validation.short_threshold)
    else:
        return 0.4, ["quality_economic_no_direction"]
    if metrics.passes:
        ratio = metrics.lhs / max(metrics.rhs, 1e-9)
        return _clamp01(0.5 + ratio * 0.3, 0.5), ["quality_economic_edge_ok"]
    reasons.append("quality_economic_edge_insufficient")
    return 0.2, reasons


def _score_regime(
    structure: MarketStructureSnapshot,
    strategy: StrategyCandidate,
    regime: str,
    structural: float,
) -> tuple[float, List[str], bool]:
    reasons: List[str] = []
    reg = str(regime or "").strip().lower()
    need_ml = False
    if reg in ("neutral", ""):
        floor = float(
            getattr(settings, "entry_quality_structural_conf_floor_neutral", 0.65) or 0.65
        )
        if structural < floor:
            need_ml = True
            reasons.append("quality_regime_neutral_needs_ml")
        score = 0.55 if need_ml else 0.7
    elif reg == "trending" and strategy.thesis_type in ("breakout", "trend_continuation"):
        score = 0.85
        reasons.append("quality_regime_trend_fit")
    elif structure.market_type == "RANGING" and strategy.thesis_type == "mean_reversion":
        score = 0.8
        reasons.append("quality_regime_range_mr")
    else:
        score = 0.6
    return score, reasons, need_ml


def _score_position_context(market_context: Optional[Dict[str, Any]]) -> tuple[float, List[str]]:
    mc = market_context if isinstance(market_context, dict) else {}
    reasons: List[str] = []
    if mc.get("has_open_position"):
        return 0.15, ["quality_position_open"]
    recent = mc.get("recent_exit_snapshot")
    if isinstance(recent, dict):
        bars = int(recent.get("bars_since_exit") or 0)
        if bars < 3:
            return 0.35, ["quality_position_recent_exit"]
    return 0.75, ["quality_position_clear"]


def _score_microstructure(
    features: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    spread_max = float(
        getattr(settings, "entry_quality_microstructure_spread_bps_max", 30.0) or 30.0
    )
    spread = float(features.get("spread_bps") or 0.0)
    score = 0.7
    if spread > spread_max:
        score = max(0.2, 0.7 - (spread - spread_max) / max(spread_max, 1.0) * 0.3)
        reasons.append(f"quality_micro_spread_wide={spread:.1f}")
    mc = market_context if isinstance(market_context, dict) else {}
    state = mc.get("market_state")
    if isinstance(state, dict):
        primary = state.get("intraday_30m") or state.get("scalp_10m") or {}
        liq = str(primary.get("liquidity_condition") or "BALANCED").upper()
        liq_map = {"HIGH": 0.9, "BALANCED": 0.7, "LOW": 0.4, "STRESSED": 0.2}
        score = min(score, liq_map.get(liq, 0.5))
        if liq in ("LOW", "STRESSED"):
            reasons.append(f"quality_micro_liquidity_{liq.lower()}")
    vol = float(features.get("vol_regime") or features.get("atr_pct") or 1.0)
    if vol > 2.5:
        score *= 0.85
        reasons.append("quality_micro_vol_spike")
    return _clamp01(score, 0.2), reasons


def _score_trend_stability(
    features: Dict[str, Any],
    market_context: Optional[Dict[str, Any]],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    hurst = float(features.get("hurst_60") or 0.5)
    score = _clamp01(0.4 + (hurst - 0.45) * 1.2, 0.35)
    mc = market_context if isinstance(market_context, dict) else {}
    traj = mc.get("market_state_trajectory")
    if isinstance(traj, dict):
        delta = float(traj.get("trend_strength_delta") or 0.0)
        if delta > 0.05:
            score = min(1.0, score + 0.1)
            reasons.append("quality_trend_accelerating")
        elif delta < -0.08:
            score = max(0.2, score - 0.15)
            reasons.append("quality_trend_degrading")
    adx = float(features.get("adx_14") or features.get("adx") or 0.0)
    if adx > 28:
        score = min(1.0, score + 0.05)
    return score, reasons


def _score_signal_freshness(
    strategy: StrategyCandidate,
    market_context: Optional[Dict[str, Any]],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    half_life = float(
        getattr(settings, "entry_quality_freshness_half_life_bars", 6.0) or 6.0
    )
    mc = market_context if isinstance(market_context, dict) else {}
    bar_idx = int(mc.get("bar_index") or 0)
    fired = mc.get("thesis_fired_at_bar")
    strat_meta = getattr(strategy, "metadata", None)
    if fired is None and isinstance(strat_meta, dict):
        fired = strat_meta.get("thesis_fired_at_bar")
    if fired is None:
        return 0.75, ["quality_freshness_unknown"]
    age = max(0, bar_idx - int(fired))
    freshness = math.exp(-age / max(half_life, 0.5))
    if age > half_life * 2:
        reasons.append(f"quality_freshness_stale_bars={age}")
    else:
        reasons.append("quality_freshness_ok")
    return _clamp01(freshness, 0.2), reasons


def get_dimension_calibration() -> Dict[str, float]:
    return dict(_dimension_calibration)


def apply_dimension_calibration_feedback(
    dimensions_at_entry: Dict[str, float],
    root_cause: str,
    pnl_usd: float,
    *,
    shadow: bool = False,
) -> Dict[str, float]:
    """Bounded adjustment to dimension weight offsets from post-trade reflection (PR7)."""
    step = float(getattr(settings, "reflection_calibration_step_size", 0.02) or 0.02)
    delta = step if pnl_usd > 0 else -step
    targets: List[str] = []
    if root_cause == "poor_entry":
        targets = ["structural", "ml", "regime"]
    elif root_cause == "fee_dominated":
        targets = ["economic", "position_context"]
    elif root_cause == "wrong_trend":
        targets = ["trend_stability", "regime"]
    adjustments: Dict[str, float] = {}
    for key in targets:
        if key not in _dimension_calibration:
            continue
        new_val = _clamp01(_dimension_calibration[key] + delta, -0.1)
        new_val = min(0.1, new_val)
        adjustments[key] = new_val - _dimension_calibration[key]
        if not shadow:
            _dimension_calibration[key] = new_val
    return adjustments


def evaluate_entry_quality(
    *,
    strategy: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
    structure: MarketStructureSnapshot,
    ml_confirms: bool,
    market_context: Optional[Dict[str, Any]] = None,
    collapse_rate: Optional[float] = None,
) -> EntryQualityResult:
    """Compute advisory entry quality score (0–100) across eight dimensions."""
    mc = market_context if isinstance(market_context, dict) else {}
    features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
    regime = str(mc.get("regime") or structure.market_type or "").lower()
    direction = _effective_direction(strategy, ml_validation)
    reasons: List[str] = []

    structural, r1 = _score_structural(strategy, direction, ml_validation, ml_confirms)
    ml_sc, r2 = _score_ml(ml_validation, direction, collapse_rate)
    economic, r3 = _score_economic(ml_validation, direction, mc)
    regime_sc, r4, need_ml = _score_regime(structure, strategy, regime, structural)
    pos_sc, r5 = _score_position_context(mc)
    micro_sc, r6 = _score_microstructure(features, mc)
    trend_sc, r7 = _score_trend_stability(features, mc)
    fresh_sc, r8 = _score_signal_freshness(strategy, mc)

    dimensions = {
        "structural": structural,
        "ml": ml_sc,
        "economic": economic,
        "regime": regime_sc,
        "position_context": pos_sc,
        "microstructure": micro_sc,
        "trend_stability": trend_sc,
        "signal_freshness": fresh_sc,
    }
    for r in (r1, r2, r3, r4, r5, r6, r7, r8):
        reasons.extend(r)

    weights = dict(_DIMENSION_WEIGHTS)
    for key, cal in _dimension_calibration.items():
        if key in weights:
            weights[key] = max(0.01, weights[key] * (1.0 + cal))

    total_w = sum(weights.values()) or 1.0
    weights = {k: v / total_w for k, v in weights.items()}
    composite = sum(dimensions[k] * weights[k] for k in weights if k in dimensions)
    quality_score = round(composite * 100.0, 2)

    min_score = float(getattr(settings, "entry_quality_min_score", 55.0) or 55.0)
    min_score = min(min_score, float(getattr(settings, "agent_trade_score_min", 55.0) or 55.0))
    passed = quality_score >= min_score and direction != "FLAT"
    if not passed and direction != "FLAT":
        reasons.append(f"quality_below_min={quality_score:.1f}<{min_score:.1f}")

    return EntryQualityResult(
        quality_score=quality_score,
        passed=passed,
        dimensions=dimensions,
        reason_codes=reasons,
        required_ml_confirmation=need_ml,
    )


def apply_entry_quality_policy(
    policy_verdict: Any,
    entry_quality: Optional[EntryQualityResult],
    ml_confirms: bool,
) -> Any:
    """Policy consumes advisory quality score — does not duplicate authority."""
    from agent.events.schemas import PolicyVerdict

    if entry_quality is None or not is_entry_signal(str(policy_verdict.signal or "HOLD")):
        return policy_verdict
    reasons = list(policy_verdict.reason_codes or [])
    min_score = float(getattr(settings, "entry_quality_min_score", 55.0) or 55.0)
    if entry_quality.quality_score < min_score:
        return PolicyVerdict(
            signal="HOLD",
            confidence=policy_verdict.confidence,
            position_size=0.0,
            reason_codes=reasons + ["quality_below_floor", f"quality_score={entry_quality.quality_score:.1f}"],
            ml_evidence_id=policy_verdict.ml_evidence_id,
            adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
            memory_size_scale=policy_verdict.memory_size_scale,
            conviction=policy_verdict.conviction,
            size_fraction=0.0,
            evidence=policy_verdict.evidence,
            abstention=policy_verdict.abstention,
        )
    if entry_quality.required_ml_confirmation and not ml_confirms:
        return PolicyVerdict(
            signal="HOLD",
            confidence=policy_verdict.confidence,
            position_size=0.0,
            reason_codes=reasons + ["ml_confirmation_required"],
            ml_evidence_id=policy_verdict.ml_evidence_id,
            adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
            memory_size_scale=policy_verdict.memory_size_scale,
            conviction=policy_verdict.conviction,
            size_fraction=0.0,
            evidence=policy_verdict.evidence,
            abstention=policy_verdict.abstention,
        )
    return policy_verdict
