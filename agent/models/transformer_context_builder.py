"""Map transformer ONNX outputs to v43-compatible MCP prediction context."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

from feature_store.jacksparrow_v43_horizon import forward_bars_to_minutes
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    head_thresholds,
    primary_execution_horizon_bars,
)
from feature_store.transformer_btcusd_15m.contract import (
    HORIZON_KEY_TO_RETURN_COL,
    LEGACY_RETURN_COL,
    PATH_LABEL_HORIZON_BARS,
    REGIME_NAMES,
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
    """Translate transformer volatility regime into v43 gate regime labels."""
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


def horizon_scale_factor(horizon_minutes: int, label_horizon_minutes: int) -> float:
    """Scale legacy single future_return prediction to shorter execution horizons."""
    if label_horizon_minutes <= 0:
        return 1.0
    ratio = float(horizon_minutes) / float(label_horizon_minutes)
    return float(np.sqrt(max(ratio, 1e-6)))


def _uses_legacy_return_mapping(continuous_preds: Mapping[str, float]) -> bool:
    """True when bundle predates multi-horizon return columns."""
    if LEGACY_RETURN_COL in continuous_preds:
        return not any(
            col in continuous_preds for col in HORIZON_KEY_TO_RETURN_COL.values()
        )
    return False


def expected_return_for_horizon(
    hkey: str,
    continuous_preds: Mapping[str, float],
    *,
    label_horizon_bars: int,
    resolution_minutes: int,
) -> float:
    """Resolve expected return for a v43 horizon key."""
    return_col = HORIZON_KEY_TO_RETURN_COL.get(hkey)
    if return_col and return_col in continuous_preds:
        return float(continuous_preds.get(return_col, 0.0))

    if _uses_legacy_return_mapping(continuous_preds):
        fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
        h_minutes = forward_bars_to_minutes(fb)
        label_horizon_minutes = int(label_horizon_bars * resolution_minutes)
        scale = horizon_scale_factor(h_minutes, label_horizon_minutes)
        return float(continuous_preds.get(LEGACY_RETURN_COL, 0.0)) * scale

    return 0.0


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
    expected_return: float,
    edge: float,
    threshold: float,
    unc_scale: float,
) -> Dict[str, float]:
    """Emit buy/sell/hold simplex from signed expected return."""
    thr = max(float(threshold), 1e-6)
    ratio = float(np.tanh(float(edge) / thr))
    hold = max(0.05, min(0.5, 0.35 * max(0.3, min(1.0, float(unc_scale)))))
    rem = max(0.0, 1.0 - hold)
    if expected_return > thr * 0.25:
        buy = rem * (0.55 + 0.45 * min(1.0, abs(ratio)))
        sell = rem - buy
    elif expected_return < -thr * 0.25:
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
    future_return: float,
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
    edge = float(future_return)

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
    short_enabled: bool,
    label_horizon_bars: int = PATH_LABEL_HORIZON_BARS,
    resolution_minutes: int = 15,
) -> Tuple[Dict[str, Any], float, float]:
    """Return (out_ctx, primary_prediction, primary_confidence)."""
    future_vol = float(continuous_preds.get("future_volatility", 0.0))
    mae = float(continuous_preds.get("mae", 0.0))
    mfe = float(continuous_preds.get("mfe", 0.0))
    trend_strength = float(continuous_preds.get("trend_strength", 0.0))

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

    primary_fb = int(primary_execution_horizon_bars(bundle_metadata))
    floor = float(bundle_metadata.get("default_threshold") or 0.005)
    legacy_mapping = _uses_legacy_return_mapping(continuous_preds)

    head_payloads: Dict[str, Dict[str, Any]] = {}
    for hkey in V43_HORIZON_KEYS:
        fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
        thr, short_thr = head_thresholds(bundle_metadata, hkey)
        if thr < floor:
            thr = floor
        if short_thr < floor:
            short_thr = floor
        h_minutes = forward_bars_to_minutes(fb)
        er = expected_return_for_horizon(
            hkey,
            continuous_preds,
            label_horizon_bars=label_horizon_bars,
            resolution_minutes=resolution_minutes,
        )
        if not short_enabled and er < 0:
            er = 0.0
        head_unc = min(1.0, unc + 0.05 * abs(fb - primary_fb) / 24.0)
        head_payloads[hkey] = {
            "horizon_key": hkey,
            "forward_bars": fb,
            "horizon_minutes": h_minutes,
            "expected_return": float(er),
            "threshold": thr,
            "short_threshold": short_thr,
            "regime": regime,
            "uncertainty": head_unc,
            "model_origin": "transformer_btcusd_15m",
            "active_type": "TransformerModelNode",
            "coercion_applied": False,
            "ensemble_fallback": False,
            "transformer_mfe": mfe,
            "transformer_mae": mae,
            "transformer_future_volatility": future_vol,
            "transformer_legacy_horizon_scaling": legacy_mapping,
        }

    gate_head = head_payloads.get("scalp_10m") or next(iter(head_payloads.values()))
    primary_thr = float(gate_head["threshold"])
    edge = float(gate_head["expected_return"]) - primary_thr
    primary_pred_val = float(np.tanh(edge * 80.0))
    primary_conf = _head_confidence(edge, primary_thr, u_scale)
    entry_proba = synthetic_entry_proba_from_transformer(
        float(gate_head["expected_return"]),
        edge,
        primary_thr,
        u_scale,
    )

    out_ctx: Dict[str, Any] = {
        "format": "jacksparrow_transformer_btcusd_15m",
        "entry_proba": entry_proba,
        "entry_confidence": primary_conf,
        "multi_horizon_heads": head_payloads,
        "expected_return": float(gate_head["expected_return"]),
        "threshold": primary_thr,
        "short_threshold": float(gate_head["short_threshold"]),
        "regime": regime,
        "uncertainty": float(unc),
        "uncertainty_score": float(unc),
        "unc_scale": float(u_scale),
        "bar_index_hint": int(bar_index_hint),
        "primary_execution_horizon_bars": primary_fb,
        "training_forward_bars": int(label_horizon_bars),
        "target_horizon_bars": int(label_horizon_bars),
        "path_label_horizon_bars": int(
            bundle_metadata.get("path_label_horizon_bars") or PATH_LABEL_HORIZON_BARS
        ),
        "short_execution_enabled": short_enabled,
        "transformer_continuous_preds": dict(continuous_preds),
        "transformer_vol_regime": str(vol_regime),
        "transformer_regime_probs": dict(regime_probs),
        "transformer_regime_names": dict(REGIME_NAMES),
        "transformer_legacy_horizon_scaling": legacy_mapping,
        "p_regime_favorable": 1.0 - unc if regime == "trending" else max(0.0, 0.5 - unc),
        "p_setup_quality": float(np.clip(mfe / (mae + 1e-6), 0.0, 1.0)),
        "p_vol_expansion": float(np.clip(future_vol / 0.01, 0.0, 1.0)),
    }
    return out_ctx, primary_pred_val, primary_conf
