"""Map per-TF transformer ONNX outputs to MCP prediction context."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

from feature_store.transformer_btcusd.contract import (
    PATH_LABEL_HORIZON_BARS,
    REGIME_NAMES,
    compute_long_edge,
    compute_path_edge,
    compute_short_edge,
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
    """Emit buy/sell/hold simplex from path imbalance vs typical scale.

    ``threshold`` is the per-TF typical abs edge (label scale), not a hard
    0.5% BUY cliff. ``edge`` is path_edge (mfe - mae).
    """
    thr = max(float(threshold), 1e-6)
    imbalance_z = float(edge) / thr
    hold = max(0.05, min(0.5, 0.35 * max(0.3, min(1.0, float(unc_scale)))))
    rem = max(0.0, 1.0 - hold)
    # Soft lean: |z| < 0.25 → balanced; stronger z tilts buy/sell
    lean = float(np.clip(imbalance_z / 1.25, -1.0, 1.0))
    if lean > 0.25:
        buy = rem * (0.55 + 0.45 * lean)
        sell = rem - buy
    elif lean < -0.25:
        sell = rem * (0.55 + 0.45 * abs(lean))
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
    confidence_hold_floor: float = 0.40,
    size_floor: float = 0.35,
    long_edge: Optional[float] = None,
    short_edge: Optional[float] = None,
    long_threshold: Optional[float] = None,
    short_threshold: Optional[float] = None,
) -> tuple[str, float, list[str], float]:
    """Deprecated leftover mapping; live path uses agent synthesis.

    Kept for unit tests of edge arithmetic only. Prefer climate/setup/timing.
    """
    reason_codes: list[str] = []
    thr_default = max(float(threshold), 1e-6)
    thr_long = max(float(long_threshold if long_threshold is not None else thr_default), 1e-6)
    thr_short = max(
        float(short_threshold if short_threshold is not None else thr_default),
        1e-6,
    )
    le = float(long_edge if long_edge is not None else path_edge)
    se = float(short_edge if short_edge is not None else -float(path_edge))

    if extreme_regime_veto and str(vol_regime or "").upper() == "EXTREME":
        reason_codes.append("transformer_extreme_regime_veto")
        return "HOLD", 0.0, reason_codes, 0.0

    conf = float(confidence)
    hold_floor = float(confidence_hold_floor)
    full_band = float(min_confidence)
    if hold_floor > full_band:
        hold_floor = full_band

    if conf < hold_floor:
        reason_codes.append("transformer_below_confidence_hold_floor")
        return "HOLD", conf, reason_codes, 0.0

    reduced_band = conf < full_band
    if reduced_band:
        reason_codes.append("transformer_reduced_size_confidence_band")
        size_scale = float(
            max(float(size_floor), min(1.0, conf / max(full_band, 1e-6)))
        )
    else:
        size_scale = 1.0

    strong_mult = max(float(strong_edge_multiplier), 1.0)
    if le > thr_long and le >= se:
        if reduced_band:
            signal = "BUY"
        else:
            signal = "STRONG_BUY" if le > thr_long * strong_mult else "BUY"
        reason_codes.append("transformer_long_edge")
        return signal, conf, reason_codes, size_scale
    if se > thr_short and se > le:
        if reduced_band:
            signal = "SELL"
        else:
            signal = "STRONG_SELL" if se > thr_short * strong_mult else "SELL"
        reason_codes.append("transformer_short_edge")
        return signal, conf, reason_codes, size_scale

    reason_codes.append("transformer_below_threshold")
    return "HOLD", conf, reason_codes, 0.0


def _typical_abs_edge_from_bundle(bundle_metadata: Mapping[str, Any]) -> float:
    """Match market_understanding.typical_abs_edge_from_metadata without cycle import."""
    from feature_store.transformer_btcusd.contract import CONTINUOUS_LABEL_COLS

    mfe_idx = CONTINUOUS_LABEL_COLS.index("mfe")
    mae_idx = CONTINUOUS_LABEL_COLS.index("mae")
    means = bundle_metadata.get("label_mean")
    stds = bundle_metadata.get("label_std")
    typical = 0.005
    if isinstance(means, (list, tuple)) and len(means) > max(mfe_idx, mae_idx):
        try:
            typical = abs(float(means[mfe_idx]) - float(means[mae_idx]))
        except (TypeError, ValueError):
            typical = 0.0
    if typical < 1e-4 and isinstance(stds, (list, tuple)) and len(stds) > max(mfe_idx, mae_idx):
        try:
            typical = 0.5 * (float(stds[mfe_idx]) + float(stds[mae_idx]))
        except (TypeError, ValueError):
            typical = 0.005
    if typical < 1e-4:
        thr = bundle_metadata.get("default_threshold")
        try:
            typical = float(thr) if thr is not None else 0.005
        except (TypeError, ValueError):
            typical = 0.005
    return float(max(typical, 1e-4))


def build_transformer_prediction_context(
    *,
    bundle_metadata: Mapping[str, Any],
    continuous_preds: Mapping[str, float],
    vol_regime: str,
    regime_probs: Mapping[str, float],
    bar_index_hint: int,
    resolution_minutes: int = 15,
    structure_outcome: str = "",
    structure_outcome_id: int = -1,
    structure_outcome_probs: Optional[Mapping[str, float]] = None,
    future_candle_class: int = -1,
    future_candle_name: str = "",
    future_candle_probs: Optional[Mapping[str, float]] = None,
    next_direction: int = -1,
    next_wick: int = -1,
    volume_state: int = -1,
    pattern_validates: float = 1.0,
    volume_confirms: float = 1.0,
    horizon_t24_dir: int = -1,
    horizon_ladder: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], float, float]:
    """Return (out_ctx, primary_prediction, primary_confidence) for one TF model."""
    future_vol = float(
        continuous_preds.get("future_volatility", continuous_preds.get("h5m_vol", 0.0))
        or 0.0
    )
    mae = float(continuous_preds.get("mae", continuous_preds.get("h5m_mae", 0.0)) or 0.0)
    mfe = float(continuous_preds.get("mfe", continuous_preds.get("h5m_mfe", 0.0)) or 0.0)
    trend_strength = float(
        continuous_preds.get(
            "trend_strength", continuous_preds.get("h5m_trend_strength", 0.0)
        )
        or 0.0
    )
    follow = float(continuous_preds.get("candle_follow_through_atr", 0.0) or 0.0)
    struct_delta = float(continuous_preds.get("structure_delta", 0.0) or 0.0)
    long_edge = compute_long_edge(mfe, mae)
    short_edge = compute_short_edge(mfe, mae)
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

    typical = _typical_abs_edge_from_bundle(bundle_metadata)
    winning = long_edge if long_edge >= short_edge else short_edge
    imbalance_z = float(path_edge) / max(typical, 1e-6)
    # Signed imbalance in (-1, 1) — not tanh vs a 0.5% BUY cliff
    primary_pred_val = float(np.tanh(imbalance_z))
    primary_conf = _head_confidence(winning - typical, typical, u_scale)
    entry_proba = synthetic_entry_proba_from_transformer(
        path_edge,
        path_edge,
        typical,
        u_scale,
    )
    setup_quality = float(np.clip(mfe / (mae + 1e-6), 0.0, 1.0))
    if follow > 0.0:
        setup_quality = float(np.clip(setup_quality + 0.1, 0.0, 1.0))
    if (path_edge > 0 and struct_delta > 0) or (path_edge < 0 and struct_delta < 0):
        setup_quality = float(np.clip(setup_quality + 0.05, 0.0, 1.0))

    resolution = str(bundle_metadata.get("resolution") or f"{resolution_minutes}m")
    out_ctx: Dict[str, Any] = {
        "format": "jacksparrow_transformer_btcusd_per_tf",
        "resolution": resolution,
        "resolution_minutes": int(resolution_minutes),
        "entry_proba": entry_proba,
        "entry_confidence": primary_conf,
        "path_edge": path_edge,
        "long_edge": long_edge,
        "short_edge": short_edge,
        "winning_edge": float(winning),
        "path_imbalance_z": float(imbalance_z),
        "threshold": typical,
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
        "transformer_structure_outcome": str(structure_outcome or ""),
        "transformer_structure_outcome_id": int(structure_outcome_id),
        "transformer_structure_outcome_probs": dict(structure_outcome_probs or {}),
        "transformer_future_candle_class": int(future_candle_class),
        "transformer_future_candle_name": str(future_candle_name or ""),
        "transformer_future_candle_probs": dict(future_candle_probs or {}),
        "next_direction": int(next_direction),
        "next_wick": int(next_wick),
        "volume_state": int(volume_state),
        "pattern_validates": float(pattern_validates),
        "volume_confirms": float(volume_confirms),
        "horizon_t24_dir": int(horizon_t24_dir),
        "horizon_ladder": dict(horizon_ladder or {}),
        "p_regime_favorable": 1.0 - unc if regime == "trending" else max(0.0, 0.5 - unc),
        "p_setup_quality": setup_quality,
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
                "long_edge": ctx.get("long_edge"),
                "short_edge": ctx.get("short_edge"),
                "path_imbalance_z": ctx.get("path_imbalance_z"),
                "regime": ctx.get("regime"),
                "vol_regime": ctx.get("transformer_vol_regime"),
                "confidence": ctx.get("entry_confidence"),
                "resolution": ctx.get("resolution"),
                "mfe": (ctx.get("transformer_continuous_preds") or {}).get("mfe"),
                "mae": (ctx.get("transformer_continuous_preds") or {}).get("mae"),
                "drawdown_before_mfe": (ctx.get("transformer_continuous_preds") or {}).get(
                    "drawdown_before_mfe"
                ),
                "trend_strength": (ctx.get("transformer_continuous_preds") or {}).get(
                    "trend_strength"
                ),
                "structure_outcome": ctx.get("transformer_structure_outcome"),
                "future_candle_class": ctx.get("transformer_future_candle_class"),
                "candle_follow_through_atr": (
                    ctx.get("transformer_continuous_preds") or {}
                ).get("candle_follow_through_atr"),
                "structure_delta": (ctx.get("transformer_continuous_preds") or {}).get(
                    "structure_delta"
                ),
            }
            for key, ctx in per_tf_contexts.items()
        },
        "cross_tf_summary": dict(policy_result.get("cross_tf_summary") or {}),
        "transformer_signal": policy_result.get("signal"),
        "transformer_reason_codes": list(policy_result.get("reason_codes") or []),
    }
