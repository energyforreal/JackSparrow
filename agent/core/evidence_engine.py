"""Unified evidence aggregation — continuous scores, no passed/reject bool."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.core.config import settings
from agent.core.evidence_types import EvidenceBundle, EvidenceDimension, MarketForecastBundle
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)
from agent.core.trade_scorer import score_trade_setup
from agent.core.v43_signal_gates import round_trip_cost_pct


def _clamp01(val: Any, default: float = 0.5) -> float:
    if val is None:
        return default
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return default


def liquidity_score_from_structure(structure: MarketStructureSnapshot) -> float:
    return 1.0 if structure.liquidity_ok else 0.35


def structure_quality_from_structure(structure: MarketStructureSnapshot) -> float:
    return 0.35 if structure.chop_market else 0.75


def volatility_score_from_features(features: Dict[str, Any]) -> float:
    atr = float(features.get("atr_pct") or 0.0)
    vol_reg = float(features.get("vol_regime") or 1.0)
    atr_min = float(getattr(settings, "agent_thesis_min_atr_pct", 0.0) or 0.0)
    if atr_min > 0 and atr > 0:
        return _clamp01(atr / max(atr_min, 1e-9), 0.5)
    return _clamp01(min(1.0, vol_reg / 2.5), 0.5)


def funding_pressure_score(features: Dict[str, Any]) -> float:
    funding = abs(float(features.get("funding_pressure") or 0.0))
    fund_max = float(getattr(settings, "agent_thesis_funding_pressure_max", 2.0) or 2.0)
    if fund_max <= 0:
        return 0.5
    return _clamp01(1.0 - funding / fund_max, 0.5)


def squeeze_risk_score(features: Dict[str, Any], market_context: Dict[str, Any]) -> float:
    squeeze = max(
        float(features.get("long_squeeze_risk") or 0.0),
        float(features.get("short_squeeze_risk") or 0.0),
        float(market_context.get("squeeze_risk") or 0.0),
    )
    thr = float(getattr(settings, "agent_thesis_squeeze_veto_threshold", 0.5) or 0.5)
    return _clamp01(1.0 - squeeze / max(thr, 1e-9), 0.5)


def crisis_risk_score(regime: str) -> float:
    """Higher score = lower crisis risk (more favorable)."""
    r = str(regime or "neutral").strip().lower()
    if r == "crisis":
        return 0.18
    if r == "trending":
        return 0.82
    if r == "ranging":
        return 0.65
    return 0.72


def trend_strength_score(structure: MarketStructureSnapshot, features: Dict[str, Any]) -> float:
    """Trend strength from structure and ADX (inverse of chop penalty)."""
    if structure.chop_market:
        return 0.29
    adx = float(features.get("adx_14") or 0.0)
    trending_min = float(getattr(settings, "agent_structure_trending_adx_min", 22.0) or 22.0)
    if adx >= trending_min:
        return _clamp01(0.55 + (adx - trending_min) / 40.0, 0.55)
    return 0.45


def build_environment_scores(
    features: Dict[str, Any],
    structure: MarketStructureSnapshot,
    market_context: Dict[str, Any],
    *,
    regime: Optional[str] = None,
) -> Dict[str, float]:
    """Canonical continuous environment scores for hypothesis and evidence layers."""
    mc = market_context if isinstance(market_context, dict) else {}
    reg = str(regime or mc.get("regime") or mc.get("v43_regime") or "neutral").lower()
    liq = liquidity_score_from_structure(structure)
    vol = volatility_score_from_features(features)
    funding_risk = 1.0 - funding_pressure_score(features)
    squeeze_prob = 1.0 - squeeze_risk_score(features, mc)
    return {
        "liquidity": liq,
        "volatility": vol,
        "funding_risk": _clamp01(funding_risk),
        "squeeze_prob": _clamp01(squeeze_prob),
        "trend_strength": trend_strength_score(structure, features),
        "crisis_risk": crisis_risk_score(reg),
        "structure": structure_quality_from_structure(structure),
    }


def ml_edge_score(ml_validation: MLValidationSnapshot) -> float:
    rtc = round_trip_cost_pct()
    if ml_validation.final_long or ml_validation.final_short:
        thr = ml_validation.threshold if ml_validation.final_long else ml_validation.short_threshold
        edge = abs(ml_validation.expected_return) - thr - rtc
        return _clamp01(0.5 + edge * 20.0, 0.5)
    proba = ml_validation.expected_return
    thr = ml_validation.threshold
    if proba > thr:
        edge = (proba - thr) - rtc
        return _clamp01(0.4 + edge * 15.0, 0.4)
    if proba < -ml_validation.short_threshold:
        edge = (abs(proba) - ml_validation.short_threshold) - rtc
        return _clamp01(0.4 + edge * 15.0, 0.4)
    return 0.35


def model_certainty_score(ml_validation: MLValidationSnapshot) -> float:
    unc = ml_validation.uncertainty
    unc_max = float(getattr(settings, "jacksparrow_v43_uncertainty_max", 0.08) or 0.08)
    if unc_max <= 0:
        return 0.7
    return _clamp01(1.0 - float(unc) / unc_max, 0.5)


def horizon_alignment_score(market_context: Dict[str, Any]) -> float:
    raw = market_context.get("multi_horizon_evidence")
    if not isinstance(raw, dict):
        return 0.5
    try:
        align = float(raw.get("alignment_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        align = 0.0
    return _clamp01(0.5 + align * 0.5, 0.5)


def mso_evidence_scores(market_context: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    state = market_context.get("market_state")
    if not isinstance(state, dict):
        return out
    primary = state.get("intraday_30m") or state.get("scalp_10m") or {}
    liq = str(primary.get("liquidity_condition") or "BALANCED").upper()
    liq_map = {"HIGH": 0.9, "BALANCED": 0.65, "LOW": 0.35, "STRESSED": 0.2}
    out[EvidenceDimension.LIQUIDITY.value] = liq_map.get(liq, 0.5)
    br_proba = primary.get("breakout_state_proba")
    br = 0.0
    if isinstance(br_proba, dict):
        br = float(br_proba.get("BREAKOUT_FORMING", 0)) + float(
            br_proba.get("BREAKOUT_CONFIRMED", 0)
        )
    out[EvidenceDimension.BREAKOUT.value] = _clamp01(br, 0.4)
    trend = str(primary.get("trend_regime") or "RANGE").upper()
    if "BULL" in trend:
        out[EvidenceDimension.REGIME.value] = 0.75
        out.setdefault("regime_bull", 0.75)
    elif "BEAR" in trend:
        out[EvidenceDimension.REGIME.value] = 0.25
        out.setdefault("regime_bear", 0.75)
    else:
        out[EvidenceDimension.REGIME.value] = 0.5
        out.setdefault("regime_range", 0.6)
    return out


def thesis_evidence_contributions(thesis_verdict: Any) -> Dict[str, float]:
    if thesis_verdict is None:
        return {}
    raw = getattr(thesis_verdict, "evidence_contributions", None)
    if isinstance(raw, dict):
        return {str(k): _clamp01(v) for k, v in raw.items()}
    if isinstance(thesis_verdict, dict):
        ec = thesis_verdict.get("evidence_contributions")
        if isinstance(ec, dict):
            return {str(k): _clamp01(v) for k, v in ec.items()}
    return {}


def market_forecast_from_context(
    market_context: Dict[str, Any],
    ml_validation: Optional[MLValidationSnapshot] = None,
) -> MarketForecastBundle:
    mc = market_context or {}
    ml = ml_validation
    if ml is None:
        ml_raw = mc.get("ml_validation")
        if isinstance(ml_raw, dict):
            try:
                from agent.core.strategy_types import MLValidationSnapshot

                ml = MLValidationSnapshot(**{k: ml_raw[k] for k in ml_raw if k != "multi_horizon_evidence"})
            except (TypeError, ValueError):
                ml = None
    regime_dist: Dict[str, float] = {}
    regime = str(mc.get("regime") or mc.get("v43_regime") or "neutral").lower()
    if regime == "trending":
        regime_dist = {"trending": 0.7, "ranging": 0.2, "crisis": 0.05, "vol_expansion": 0.05}
    elif regime == "crisis":
        regime_dist = {"crisis": 0.8, "ranging": 0.1, "trending": 0.05, "vol_expansion": 0.05}
    elif regime == "ranging":
        regime_dist = {"ranging": 0.7, "trending": 0.15, "crisis": 0.05, "vol_expansion": 0.1}
    else:
        regime_dist = {"neutral": 0.5, "trending": 0.25, "ranging": 0.25}
    return MarketForecastBundle(
        regime_distribution=regime_dist,
        liquidity_forecast=mc.get("p_regime_favorable"),
        breakout_probability=None,
        vol_expansion_prob=_clamp01(mc.get("p_vol_expansion"), None) if mc.get("p_vol_expansion") is not None else None,
        momentum_score=None,
        expected_edge=float(ml.expected_return) if ml else None,
        uncertainty_score=float(ml.uncertainty) if ml else _clamp01(mc.get("uncertainty_score"), None),
        p_setup_quality=_clamp01(mc.get("p_setup_quality"), None) if mc.get("p_setup_quality") is not None else None,
        p_regime_favorable=_clamp01(mc.get("p_regime_favorable"), None) if mc.get("p_regime_favorable") is not None else None,
    )


def build_evidence_bundle(
    *,
    market_context: Dict[str, Any],
    ml_validation: MLValidationSnapshot,
    structure: MarketStructureSnapshot,
    strategy: Optional[StrategyCandidate] = None,
    thesis_verdict: Any = None,
    ml_confirms: bool = False,
) -> EvidenceBundle:
    """Build continuous evidence from market context (no passed boolean)."""
    mc = market_context if isinstance(market_context, dict) else {}
    features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
    scores: Dict[str, float] = {}

    scores[EvidenceDimension.LIQUIDITY.value] = liquidity_score_from_structure(structure)
    scores[EvidenceDimension.STRUCTURE.value] = structure_quality_from_structure(structure)
    scores[EvidenceDimension.VOLATILITY.value] = volatility_score_from_features(features)
    scores[EvidenceDimension.FUNDING.value] = funding_pressure_score(features)
    scores[EvidenceDimension.SQUEEZE_RISK.value] = squeeze_risk_score(features, mc)
    scores[EvidenceDimension.ML_EDGE.value] = ml_edge_score(ml_validation)
    scores[EvidenceDimension.MODEL_CERTAINTY.value] = model_certainty_score(ml_validation)
    scores[EvidenceDimension.HORIZON_ALIGNMENT.value] = horizon_alignment_score(mc)

    if mc.get("p_regime_favorable") is not None:
        scores[EvidenceDimension.REGIME.value] = _clamp01(mc.get("p_regime_favorable"))
    else:
        scores[EvidenceDimension.REGIME.value] = 0.55

    if strategy and strategy.direction != "FLAT":
        scores[EvidenceDimension.TREND.value] = _clamp01(
            0.5 + float(strategy.strength or 0.0) * 0.4
        )
        scores[EvidenceDimension.MOMENTUM.value] = _clamp01(
            float(strategy.confidence or 0.5)
        )
    else:
        scores[EvidenceDimension.TREND.value] = 0.45
        scores[EvidenceDimension.MOMENTUM.value] = 0.45

    if mc.get("p_setup_quality") is not None:
        scores["setup_quality"] = _clamp01(mc.get("p_setup_quality"))
    if mc.get("p_vol_expansion") is not None:
        scores[EvidenceDimension.VOLATILITY.value] = max(
            scores[EvidenceDimension.VOLATILITY.value],
            _clamp01(mc.get("p_vol_expansion")),
        )

    scores.update(mso_evidence_scores(mc))
    scores.update(thesis_evidence_contributions(thesis_verdict))

    env_block = mc.get("environment_scores")
    if isinstance(env_block, dict):
        for k, v in env_block.items():
            scores[f"env_{k}"] = _clamp01(v)

    ts = score_trade_setup(
        strategy=strategy or StrategyCandidate(),
        ml_validation=ml_validation,
        structure=structure,
        ml_confirms=ml_confirms,
    )
    norm_score = _clamp01(float(ts.score) / 100.0, 0.5)
    scores["legacy_trade_score_norm"] = norm_score

    regime_dist = market_forecast_from_context(mc, ml_validation).regime_distribution

    metadata: Dict[str, Any] = {
        "legacy_trade_score": ts.score,
        "trade_score_components": ts.components,
        "trade_score_reasons": ts.reason_codes,
    }
    if isinstance(mc.get("environment_scores"), dict):
        metadata["environment"] = dict(mc["environment_scores"])
    hyp_raw = mc.get("hypothesis_snapshot")
    if isinstance(hyp_raw, dict):
        metadata["hypothesis_snapshot"] = hyp_raw

    return EvidenceBundle(
        scores=scores,
        metadata=metadata,
        regime_distribution=regime_dist,
    )
