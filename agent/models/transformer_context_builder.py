"""Map per-TF transformer ONNX outputs to MCP prediction context."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

import numpy as np

from feature_store.transformer_btcusd.contract import (
    PATH_LABEL_HORIZON_BARS,
    REGIME_NAMES,
    compute_path_edge,
)


def _uncertainty_scale(uncertainty: float) -> float:
    return float(np.clip(1.0 - (float(uncertainty) - 0.05) * 5.0, 0.3, 1.0))


def _head_confidence(edge: float, threshold: float, unc_scale: float) -> float:
    thr = max(float(threshold), 1e-6)
    edge_ratio = min(1.0, abs(float(edge)) / thr)
    base = 0.25 + 0.75 * edge_ratio
    return float(min(1.0, max(0.0, base * float(unc_scale))))


def map_vol_regime_to_agent_regime(
    vol_regime: str,
    *,
    trend_strength: float,
    future_volatility: float,
) -> str:
    """Translate transformer volatility regime into agent gate regime labels."""
    label = str(vol_regime or "NORMAL").upper()
    if label == "EXTREME":
        return "crisis"
    if label == "HIGH" and future_volatility > 0.004:
        return "crisis"
    if label in ("LOW", "NORMAL") and trend_strength >= 1.5:
        return "trending"
    if label == "LOW" and trend_strength < 0.8:
        return "ranging"
    return "neutral"


def estimate_uncertainty(
    *,
    future_volatility: float,
    mae: float,
    vol_regime: str,
) -> float:
    """Higher predicted vol / adverse excursion => higher uncertainty."""
    vol_component = float(np.clip(future_volatility / 0.01, 0.0, 1.0))
    mae_component = float(np.clip(mae / 0.02, 0.0, 1.0))
    regime_boost = {"LOW": 0.0, "NORMAL": 0.05, "HIGH": 0.15, "EXTREME": 0.25}.get(
        str(vol_regime).upper(),
        0.1,
    )
    return float(np.clip(0.2 * vol_component + 0.35 * mae_component + regime_boost, 0.05, 0.95))


def synthetic_entry_proba_from_transformer(
    path_edge: float,
    edge: float,
    threshold: float,
    unc_scale: float,
) -> Dict[str, float]:
    """Emit buy/sell/hold simplex from signed path edge (mfe - mae)."""
    thr = max(float(threshold), 1e-6)
    ratio = float(np.tanh(float(edge) / thr))
    hold = max(0.05, min(0.5, 0.35 * max(0.3, min(1.0, float(unc_scale)))))
    rem = max(0.0, 1.0 - hold)
    if path_edge > thr * 0.25:
        buy = rem * (0.55 + 0.45 * min(1.0, abs(ratio)))
        sell = rem - buy
    elif path_edge < -thr * 0.25:
        sell = rem * (0.55 + 0.45 * min(1.0, abs(ratio)))
        buy = rem - sell
    else:
        buy = rem * 0.5
        sell = rem * 0.5
    total = buy + sell + hold
    if total <= 0:
        return {"buy": 0.33, "sell": 0.33, "hold": 0.34}
    return {"buy": buy / total, "sell": sell / total, "hold": hold / total}


def map_prediction_to_signal(
    *,
    path_edge: float,
    threshold: float,
    vol_regime: str,
    confidence: float,
    strong_edge_multiplier: float = 1.5,
    extreme_regime_veto: bool = True,
    min_confidence: float = 0.55,
) -> tuple[str, float, list[str]]:
    """Map transformer outputs to trading signal, confidence, and reason codes."""
    reason_codes: list[str] = []
    thr = max(float(threshold), 1e-6)
    edge = float(path_edge)

    if extreme_regime_veto and str(vol_regime or "").upper() == "EXTREME":
        reason_codes.append("transformer_extreme_regime_veto")
        return "HOLD", 0.0, reason_codes

    strong_mult = max(float(strong_edge_multiplier), 1.0)
    conf = float(confidence)
    if conf < float(min_confidence):
        reason_codes.append("transformer_below_min_confidence")
        return "HOLD", conf, reason_codes

    if edge > thr:
        signal = "STRONG_BUY" if edge > thr * strong_mult else "BUY"
        reason_codes.append("transformer_long_edge")
        return signal, conf, reason_codes
    if edge < -thr:
        signal = "STRONG_SELL" if edge < -thr * strong_mult else "SELL"
        reason_codes.append("transformer_short_edge")
        return signal, conf, reason_codes

    reason_codes.append("transformer_below_threshold")
    return "HOLD", conf, reason_codes


def build_transformer_prediction_context(
    *,
    bundle_metadata: Mapping[str, Any],
    continuous_preds: Mapping[str, float],
    vol_regime: str,
    regime_probs: Mapping[str, float],
    bar_index_hint: int,
    resolution_minutes: int = 15,
) -> Tuple[Dict[str, Any], float, float]:
    """Return (out_ctx, primary_prediction, primary_confidence) for one TF model."""
    future_vol = float(continuous_preds.get("future_volatility", 0.0))
    mae = float(continuous_preds.get("mae", 0.0))
    mfe = float(continuous_preds.get("mfe", 0.0))
    trend_strength = float(continuous_preds.get("trend_strength", 0.0))
    path_edge = compute_path_edge(mfe, mae)

    regime = map_vol_regime_to_agent_regime(
        vol_regime,
        trend_strength=trend_strength,
        future_volatility=future_vol,
    )
    unc = estimate_uncertainty(
        future_volatility=future_vol,
        mae=mae,
        vol_regime=vol_regime,
    )
    u_scale = _uncertainty_scale(unc)

    primary_thr = float(bundle_metadata.get("default_threshold") or 0.005)
    edge = path_edge - primary_thr
    primary_pred_val = float(np.tanh(edge * 80.0))
    primary_conf = _head_confidence(edge, primary_thr, u_scale)
    entry_proba = synthetic_entry_proba_from_transformer(
        path_edge,
        edge,
        primary_thr,
        u_scale,
    )

    resolution = str(bundle_metadata.get("resolution") or f"{resolution_minutes}m")
    out_ctx: Dict[str, Any] = {
        "format": "jacksparrow_transformer_btcusd_per_tf",
        "resolution": resolution,
        "resolution_minutes": int(resolution_minutes),
        "entry_proba": entry_proba,
        "entry_confidence": primary_conf,
        "path_edge": path_edge,
        "threshold": primary_thr,
        "regime": regime,
        "uncertainty": float(unc),
        "uncertainty_score": float(unc),
        "unc_scale": float(u_scale),
        "bar_index_hint": int(bar_index_hint),
        "path_label_horizon_bars": int(
            bundle_metadata.get("path_label_horizon_bars") or PATH_LABEL_HORIZON_BARS
        ),
        "transformer_continuous_preds": dict(continuous_preds),
        "transformer_vol_regime": str(vol_regime),
        "transformer_regime_probs": dict(regime_probs),
        "transformer_regime_names": dict(REGIME_NAMES),
        "p_regime_favorable": 1.0 - unc if regime == "trending" else max(0.0, 0.5 - unc),
        "p_setup_quality": float(np.clip(mfe / (mae + 1e-6), 0.0, 1.0)),
        "p_vol_expansion": float(np.clip(future_vol / 0.01, 0.0, 1.0)),
    }
    return out_ctx, primary_pred_val, primary_conf


def build_mtf_aggregation_context(
    *,
    per_tf_contexts: Mapping[str, Dict[str, Any]],
    policy_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Assemble multi-TF contexts and policy summary for market_context."""
    return {
        "format": "jacksparrow_transformer_btcusd_mtf",
        "multi_tf_heads": {
            key: {
                "path_edge": ctx.get("path_edge"),
                "regime": ctx.get("regime"),
                "vol_regime": ctx.get("transformer_vol_regime"),
                "confidence": ctx.get("entry_confidence"),
                "resolution": ctx.get("resolution"),
            }
            for key, ctx in per_tf_contexts.items()
        },
        "cross_tf_summary": dict(policy_result.get("cross_tf_summary") or {}),
        "transformer_signal": policy_result.get("signal"),
        "transformer_reason_codes": list(policy_result.get("reason_codes") or []),
    }
