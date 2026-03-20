"""
Multi-timeframe (MTF) decision synthesis from per-timeframe model outputs.

Maps model names like ``jacksparrow_BTCUSD_15m`` to timeframes and applies:
  - Trend direction from a higher TF (default 15m)
  - Entry confirmation from a middle TF (default 5m) with minimum confidence
  - Optional veto from a shorter TF (default 3m)

When required TFs are missing from the registry, falls back to comma-separated
fallback lists in settings. If still insufficient, returns None so the
reasoning engine uses legacy flat consensus.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

# Suffix after last underscore: 15m, 1h, 2h, 4h, 30m, etc.
_TF_SUFFIX_RE = re.compile(r"^(\d+[mhdw])$", re.IGNORECASE)


def parse_timeframe_from_model_name(model_name: str) -> Optional[str]:
    """Infer timeframe token from model name (e.g. ``jacksparrow_BTCUSD_15m`` -> ``15m``)."""
    if not model_name or "_" not in model_name:
        return None
    suffix = model_name.rsplit("_", 1)[-1].strip().lower()
    if _TF_SUFFIX_RE.match(suffix):
        return suffix
    return None


def _entry_signal_and_confidence(pred: Dict[str, Any]) -> Tuple[float, float]:
    """Read directional signal and confidence; prefer v4 context keys."""
    ctx = pred.get("context") if isinstance(pred.get("context"), dict) else {}
    sig = ctx.get("entry_signal")
    if sig is None:
        try:
            sig = float(pred.get("prediction", 0.0))
        except (TypeError, ValueError):
            sig = 0.0
    conf = ctx.get("entry_confidence")
    if conf is None:
        try:
            conf = float(pred.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
    return float(sig), max(0.0, min(1.0, float(conf)))


def index_predictions_by_timeframe(
    model_predictions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Map timeframe -> {signal, confidence}."""
    by_tf: Dict[str, Dict[str, float]] = {}
    for p in model_predictions:
        if not isinstance(p, dict):
            continue
        name = p.get("model_name") or ""
        tf = parse_timeframe_from_model_name(str(name))
        if not tf:
            continue
        sig, conf = _entry_signal_and_confidence(p)
        by_tf[tf] = {"signal": sig, "confidence": conf}
    return by_tf


def _first_available(
    by_tf: Dict[str, Dict[str, float]],
    order: List[str],
) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    for tf in order:
        if tf in by_tf:
            return by_tf[tf], tf
    return None, None


def _parse_tf_list(s: str) -> List[str]:
    return [x.strip().lower() for x in (s or "").split(",") if x.strip()]


def _filter_timeframe_enabled(raw: str) -> Optional[str]:
    t = (raw or "").strip().lower()
    if not t or t in ("none", "off", "-", "disable", "disabled"):
        return None
    return t


def synthesize_mtf_trading_decision(
    model_predictions: List[Dict[str, Any]],
    settings: Any,
) -> Optional[Tuple[str, str, float, List[str]]]:
    """
    Return (decision_code, conclusion, step5_confidence, evidence_lines) or None to use legacy consensus.

    decision_code is one of: STRONG_BUY, BUY, STRONG_SELL, SELL, HOLD.
    """
    if not getattr(settings, "mtf_decision_engine_enabled", False):
        return None
    if not model_predictions:
        return None

    by_tf = index_predictions_by_timeframe(model_predictions)
    if not by_tf:
        return None

    primary_trend = getattr(settings, "mtf_trend_timeframe", "15m").strip().lower()
    primary_entry = getattr(settings, "mtf_entry_timeframe", "5m").strip().lower()
    trend_order = [primary_trend] + _parse_tf_list(
        getattr(settings, "mtf_trend_fallback_timeframes", "")
    )
    # De-duplicate order while preserving order
    seen: set[str] = set()
    trend_order = [x for x in trend_order if x and not (x in seen or seen.add(x))]

    entry_order = [primary_entry] + _parse_tf_list(
        getattr(settings, "mtf_entry_fallback_timeframes", "")
    )
    seen_e: set[str] = set()
    entry_order = [x for x in entry_order if x and not (x in seen_e or seen_e.add(x))]

    trend, trend_tf = _first_available(by_tf, trend_order)
    entry, entry_tf = _first_available(by_tf, entry_order)
    if trend is None or entry is None:
        logger.info(
            "mtf_decision_skipped_missing_tf",
            have=list(by_tf.keys()),
            trend_order=trend_order,
            entry_order=entry_order,
        )
        return None

    filt_tf = _filter_timeframe_enabled(getattr(settings, "mtf_filter_timeframe", "3m"))
    filt = by_tf.get(filt_tf) if filt_tf else None

    t_thr = float(getattr(settings, "mtf_trend_signal_threshold", 0.1))
    e_thr = float(getattr(settings, "mtf_entry_signal_threshold", 0.15))
    min_conf = float(getattr(settings, "mtf_entry_min_confidence", 0.6))

    t_sig = trend["signal"]
    e_sig = entry["signal"]
    e_conf = entry["confidence"]

    evidence: List[str] = [
        f"MTF trend: tf={trend_tf} entry_signal={t_sig:+.3f}",
        f"MTF entry: tf={entry_tf} entry_signal={e_sig:+.3f} conf={e_conf:.2f} (min {min_conf:.2f})",
    ]
    if filt is not None and filt_tf:
        evidence.append(
            f"MTF filter: tf={filt_tf} entry_signal={filt['signal']:+.3f}"
        )

    if t_sig > t_thr:
        trend_dir = "bull"
    elif t_sig < -t_thr:
        trend_dir = "bear"
    else:
        evidence.append("MTF: trend neutral — HOLD")
        return ("HOLD", "HOLD - MTF trend timeframe neutral", max(0.0, e_conf * 0.3), evidence)

    # Optional shorter-TF veto: contradicts intended direction
    if filt is not None:
        if trend_dir == "bull" and e_sig > e_thr and filt["signal"] < -0.05:
            evidence.append("MTF: filter TF conflicts with BUY — HOLD")
            return ("HOLD", "HOLD - MTF filter conflicts with bullish entry", e_conf * 0.4, evidence)
        if trend_dir == "bear" and e_sig < -e_thr and filt["signal"] > 0.05:
            evidence.append("MTF: filter TF conflicts with SELL — HOLD")
            return ("HOLD", "HOLD - MTF filter conflicts with bearish entry", e_conf * 0.4, evidence)

    if trend_dir == "bull":
        if e_sig <= e_thr or e_conf < min_conf:
            evidence.append("MTF: entry TF not confirming bullish trend — HOLD")
            return ("HOLD", "HOLD - MTF entry not confirming 15m+ trend (BUY)", 0.0, evidence)
        if e_sig > 0.45 and e_conf >= 0.72:
            return (
                "STRONG_BUY",
                f"STRONG_BUY - MTF aligned (trend {trend_tf} + entry {entry_tf})",
                e_conf,
                evidence,
            )
        return (
            "BUY",
            f"BUY - MTF aligned (trend {trend_tf} + entry {entry_tf})",
            e_conf,
            evidence,
        )

    # bear
    if e_sig >= -e_thr or e_conf < min_conf:
        evidence.append("MTF: entry TF not confirming bearish trend — HOLD")
        return ("HOLD", "HOLD - MTF entry not confirming trend (SELL)", 0.0, evidence)
    if e_sig < -0.45 and e_conf >= 0.72:
        return (
            "STRONG_SELL",
            f"STRONG_SELL - MTF aligned (trend {trend_tf} + entry {entry_tf})",
            e_conf,
            evidence,
        )
    return (
        "SELL",
        f"SELL - MTF aligned (trend {trend_tf} + entry {entry_tf})",
        e_conf,
        evidence,
    )
