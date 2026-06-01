"""Build v43-compatible prediction context from rule-based IC outputs."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

import numpy as np

from agent.core.agent_thesis_engine import AgentThesisEngine, ThesisVerdict
from agent.intelligence.direction_signal import compute_direction_signal
from agent.intelligence.mtf_synthesizer import compute_mtf_alignment
from agent.intelligence.regime_classifier import classify_regime
from agent.intelligence.setup_quality import estimate_setup_quality
from agent.intelligence.uncertainty import estimate_uncertainty
from agent.intelligence.vol_estimator import estimate_vol_expansion
from feature_store.jacksparrow_v43_horizon import forward_bars_to_minutes
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    head_thresholds,
    primary_execution_horizon_bars,
)

_thesis_engine = AgentThesisEngine()


def uncertainty_scale(uncertainty: float) -> float:
    """Match legacy v43: clip(1 - (u - 0.05) * 5, 0.3, 1.0)."""
    return float(np.clip(1.0 - (float(uncertainty) - 0.05) * 5.0, 0.3, 1.0))


def head_confidence(edge: float, threshold: float, unc_scale: float) -> float:
    thr = max(float(threshold), 1e-6)
    edge_ratio = min(1.0, abs(float(edge)) / thr)
    base = 0.25 + 0.75 * edge_ratio
    return float(min(1.0, max(0.0, base * float(unc_scale))))


def _thesis_from_htf_bias(features: Dict[str, Any], prefix: str) -> ThesisVerdict:
    """Lightweight HTF bias thesis for MTF alignment (no full rule stack)."""
    if prefix == "h1":
        trend = float(features.get("h1_trend", 0.0) or 0.0)
        rsi = float(features.get("h1_rsi_14", 50.0) or 50.0)
        adx = float(features.get("h1_adx", 0.0) or 0.0)
    else:
        trend = float(features.get("h_trend", 0.0) or 0.0)
        rsi = float(features.get("h_rsi_14", 50.0) or 50.0)
        adx = float(features.get("adx_14", 0.0) or 0.0)

    if adx < 15:
        return ThesisVerdict(signal="HOLD", confidence=0.2, position_size=0.0, reason_codes=["ic_htf_flat"])
    if trend > 0.002 and rsi > 52:
        return ThesisVerdict(signal="BUY", confidence=0.55, position_size=0.03, reason_codes=["ic_htf_bull"])
    if trend < -0.002 and rsi < 48:
        return ThesisVerdict(signal="SELL", confidence=0.55, position_size=0.03, reason_codes=["ic_htf_bear"])
    return ThesisVerdict(signal="HOLD", confidence=0.25, position_size=0.0, reason_codes=["ic_htf_neutral"])


def build_ic_prediction_context(
    *,
    bundle_metadata: Mapping[str, Any],
    closed_feats: Dict[str, float],
    market_context: Dict[str, Any],
    bar_index_hint: int,
    short_enabled: bool,
) -> Tuple[Dict[str, Any], float, float]:
    """Return (out_ctx, primary_prediction, primary_confidence)."""
    regime = classify_regime(closed_feats)
    if "regime_label" in closed_feats:
        regime = str(closed_feats.get("regime_label", regime))

    mctx = {
        **market_context,
        "features": closed_feats,
        "v43_regime": regime,
        "regime": regime,
    }
    thesis_5m = _thesis_engine.evaluate(regime, mctx)
    thesis_15m = _thesis_from_htf_bias(closed_feats, "h")
    thesis_1h = _thesis_from_htf_bias(closed_feats, "h1")
    alignment = compute_mtf_alignment(thesis_5m, thesis_15m, thesis_1h)

    primary_er = compute_direction_signal(thesis_5m)
    if alignment >= 0.6 and primary_er != 0.0:
        primary_er *= 1.0 + 0.15 * alignment

    p_vol = estimate_vol_expansion(closed_feats)
    p_quality = estimate_setup_quality(closed_feats, thesis_5m)
    unc = estimate_uncertainty(closed_feats, regime)
    u_scale = uncertainty_scale(unc)

    primary_fb = int(primary_execution_horizon_bars(bundle_metadata))
    floor = float(bundle_metadata.get("default_threshold") or 0.005)

    head_payloads: Dict[str, Dict[str, Any]] = {}
    for hkey in V43_HORIZON_KEYS:
        fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
        thr, short_thr = head_thresholds(bundle_metadata, hkey)
        if thr < floor:
            thr = floor
        if short_thr < floor:
            short_thr = floor
        scale = 1.0 + (fb / max(primary_fb, 1) - 1.0) * 0.15
        er = float(primary_er) * scale
        head_unc = min(1.0, unc + 0.05 * abs(fb - primary_fb) / 24.0)
        head_payloads[hkey] = {
            "horizon_key": hkey,
            "forward_bars": fb,
            "horizon_minutes": forward_bars_to_minutes(fb),
            "expected_return": er,
            "threshold": thr,
            "short_threshold": short_thr,
            "regime": regime,
            "uncertainty": head_unc,
            "model_origin": "rule_based_ic",
            "active_type": "RuleBasedIntelligenceNode",
            "coercion_applied": False,
            "ensemble_fallback": False,
        }

    gate_head = head_payloads.get("scalp_10m") or next(iter(head_payloads.values()))
    primary_thr = float(gate_head["threshold"])
    edge = float(gate_head["expected_return"]) - primary_thr
    primary_pred_val = float(np.tanh(edge * 80.0))
    primary_conf = head_confidence(edge, primary_thr, u_scale)

    out_ctx: Dict[str, Any] = {
        "format": "jacksparrow_ic_rule_based",
        "multi_horizon_heads": head_payloads,
        "expected_return": float(gate_head["expected_return"]),
        "threshold": primary_thr,
        "short_threshold": float(gate_head["short_threshold"]),
        "regime": regime,
        "uncertainty": float(unc),
        "uncertainty_score": float(unc),
        "unc_scale": float(u_scale),
        "bar_index_hint": int(bar_index_hint),
        "closed_bar_features": closed_feats,
        "primary_execution_horizon_bars": primary_fb,
        "training_forward_bars": primary_fb,
        "target_horizon_bars": primary_fb,
        "short_execution_enabled": short_enabled,
        "p_regime_favorable": 1.0 - unc if regime == "trending" else max(0.0, 0.5 - unc),
        "p_setup_quality": p_quality,
        "p_vol_expansion": p_vol,
        "ic_alignment_score": alignment,
        "ic_thesis_signal": thesis_5m.signal,
        "ic_reason_codes": list(thesis_5m.reason_codes),
    }
    return out_ctx, primary_pred_val, primary_conf
