"""
Multi-timeframe (MTF) decision synthesis from per-timeframe model outputs.

Maps model names like ``jacksparrow_BTCUSD_15m`` to timeframes and applies:

**standard** (``mtf_signal_architecture``): higher TF trend + lower TF entry
confirmation, optional shorter-TF veto.

**short_tf_primary**: primary TF (default 5m) uses ``buy - sell`` with a dead zone
and long/short edges; STRONG_* uses primary-TF probability floors. A context TF
(default 15m) never blocks — ``compute_context_position_size_multiplier`` scales
size up/down in the trading handler when context agrees or disagrees.

When required TFs are missing, falls back to comma-separated lists in settings.
If still insufficient, returns None so the reasoning engine uses legacy consensus.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.core.entry_edge_tracker import EntryEdgeTracker

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


def _entry_proba(pred: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Read entry class probabilities from context when available."""
    ctx = pred.get("context") if isinstance(pred.get("context"), dict) else {}
    raw = ctx.get("entry_proba")
    if not isinstance(raw, dict):
        return None
    try:
        sell = float(raw.get("sell"))
        hold = float(raw.get("hold"))
        buy = float(raw.get("buy"))
    except (TypeError, ValueError):
        return None
    return {"sell": sell, "hold": hold, "buy": buy}


def index_predictions_by_timeframe(
    model_predictions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Map timeframe -> prediction context used by MTF synthesis."""
    by_tf: Dict[str, Dict[str, Any]] = {}
    for p in model_predictions:
        if not isinstance(p, dict):
            continue
        name = p.get("model_name") or ""
        tf = parse_timeframe_from_model_name(str(name))
        if not tf:
            continue
        sig, conf = _entry_signal_and_confidence(p)
        by_tf[tf] = {"signal": sig, "confidence": conf, "proba": _entry_proba(p)}
    return by_tf


def _first_available(
    by_tf: Dict[str, Dict[str, Any]],
    order: List[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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


def _dedupe_tf_order(order: List[str]) -> List[str]:
    seen: set[str] = set()
    return [x for x in order if x and not (x in seen or seen.add(x))]


def compute_context_position_size_multiplier(
    signal: str,
    model_predictions: List[Dict[str, Any]],
    settings: Any,
) -> float:
    """
    When short_tf_primary mode: scale size up if context TF agrees, down if it disagrees.

    Never returns 0; clamped to [0.25, 1.5].
    """
    arch = (getattr(settings, "mtf_signal_architecture", "standard") or "standard").strip().lower()
    if arch != "short_tf_primary":
        return 1.0
    if signal in ("HOLD", None, "") or signal not in (
        "BUY",
        "STRONG_BUY",
        "SELL",
        "STRONG_SELL",
    ):
        return 1.0
    by_tf = index_predictions_by_timeframe(model_predictions)
    if not by_tf:
        return 1.0
    ctx_tf = getattr(settings, "mtf_context_timeframe", "15m").strip().lower()
    ctx_order = [ctx_tf] + _parse_tf_list(
        getattr(settings, "mtf_context_fallback_timeframes", "")
    )
    ctx_order = _dedupe_tf_order(ctx_order)
    ctx_row, _ctx_name = _first_available(by_tf, ctx_order)
    if ctx_row is None:
        return 1.0
    proba = ctx_row.get("proba")
    if not proba:
        return 1.0
    try:
        cb = float(proba["buy"])
        cs = float(proba["sell"])
    except (TypeError, ValueError, KeyError):
        return 1.0
    edge = float(getattr(settings, "mtf_context_agree_edge", 0.02))
    boost = float(getattr(settings, "mtf_context_aligned_size_multiplier", 1.15))
    cut = float(getattr(settings, "mtf_context_misaligned_size_multiplier", 0.75))
    long_sig = signal in ("BUY", "STRONG_BUY")
    ctx_bull = (cb - cs) >= edge
    ctx_bear = (cs - cb) >= edge
    if long_sig:
        if ctx_bull:
            m = boost
        elif ctx_bear:
            m = cut
        else:
            m = 1.0
    else:
        if ctx_bear:
            m = boost
        elif ctx_bull:
            m = cut
        else:
            m = 1.0
    return max(0.25, min(1.5, m))


def _synthesize_short_tf_primary(
    by_tf: Dict[str, Dict[str, Any]],
    settings: Any,
    symbol: Optional[str],
) -> Optional[Tuple[str, str, float, List[str]]]:
    """
    5m (or configured)-driven scalping: signal = buy - sell on primary TF.

    Context TF (e.g. 15m) is logged for diagnostics only — never blocks. Position sizing
    uses compute_context_position_size_multiplier in the trading handler.
    """
    primary_tf = getattr(settings, "mtf_primary_signal_timeframe", "5m").strip().lower()
    primary_order = [primary_tf] + _parse_tf_list(
        getattr(settings, "mtf_primary_signal_fallback_timeframes", "")
    )
    primary_order = _dedupe_tf_order(primary_order)
    prim, prim_tf = _first_available(by_tf, primary_order)
    if prim is None:
        logger.info(
            "mtf_short_primary_skipped_missing_tf",
            have=list(by_tf.keys()),
            primary_order=primary_order,
        )
        return None

    proba = prim.get("proba")
    if not isinstance(proba, dict):
        return None
    try:
        buy = float(proba["buy"])
        sell = float(proba["sell"])
    except (TypeError, ValueError, KeyError):
        return None

    raw_signal = buy - sell
    edge_hist_val = abs(raw_signal)
    conf = max(0.0, min(1.0, float(prim.get("confidence", max(buy, sell)))))

    def _emit(
        result: Tuple[str, str, float, List[str]],
    ) -> Tuple[str, str, float, List[str]]:
        if symbol and edge_hist_val is not None:
            EntryEdgeTracker.observe(symbol, edge_hist_val)
        return result

    dead = float(getattr(settings, "mtf_primary_dead_zone", 0.05))
    edge_long = float(getattr(settings, "mtf_primary_edge_long", 0.08))
    edge_short = float(getattr(settings, "mtf_primary_edge_short", 0.08))
    slong = float(getattr(settings, "mtf_primary_strong_long_min_prob", 0.55))
    sshort = float(getattr(settings, "mtf_primary_strong_short_min_prob", 0.58))

    ctx_tf = getattr(settings, "mtf_context_timeframe", "15m").strip().lower()
    ctx_order = [ctx_tf] + _parse_tf_list(
        getattr(settings, "mtf_context_fallback_timeframes", "")
    )
    ctx_order = _dedupe_tf_order(ctx_order)
    ctx_row, ctx_used = _first_available(by_tf, ctx_order)
    ctx_note = ""
    if ctx_row and isinstance(ctx_row.get("proba"), dict):
        try:
            cb = float(ctx_row["proba"]["buy"])
            cs = float(ctx_row["proba"]["sell"])
            ctx_note = f" context[{ctx_used}]: buy={cb:.2f} sell={cs:.2f} (sizing only)"
        except (TypeError, ValueError, KeyError):
            ctx_note = f" context[{ctx_used}]: (sizing only)"

    evidence: List[str] = [
        f"MTF short-primary: tf={prim_tf} signal={raw_signal:+.3f} buy={buy:.2f} sell={sell:.2f}{ctx_note}",
    ]

    pct_enabled = bool(getattr(settings, "mtf_entry_strength_percentile_enabled", False))
    pct_val = int(getattr(settings, "mtf_entry_strength_percentile", 80))
    pct_min_n = int(getattr(settings, "mtf_entry_strength_percentile_min_samples", 30))

    def _percentile_blocks() -> Optional[Tuple[str, str, float, List[str]]]:
        if not pct_enabled:
            return None
        ok, thr = EntryEdgeTracker.strength_vs_prior_percentile(
            symbol or "", edge_hist_val, pct_val, pct_min_n
        )
        if ok:
            return None
        ev = evidence + [
            f"MTF: primary |buy-sell|={edge_hist_val:.3f} below P{pct_val} prior={thr:.3f} — HOLD",
        ]
        return (
            "HOLD",
            "HOLD - MTF primary strength below rolling percentile",
            max(0.0, conf * 0.25),
            ev,
        )

    if abs(raw_signal) < dead:
        evidence.append(f"MTF: |signal| {abs(raw_signal):.3f} < dead zone {dead:.2f} — HOLD")
        return _emit(
            (
                "HOLD",
                "HOLD - MTF primary signal in dead zone",
                max(0.0, conf * 0.2),
                evidence,
            )
        )

    blocked = _percentile_blocks()
    if blocked is not None:
        return _emit(blocked)

    if raw_signal > edge_long:
        code = "STRONG_BUY" if buy >= slong else "BUY"
        conclusion = (
            f"{code} - short-primary {prim_tf} (long edge, context TF adjusts size only)"
        )
        return _emit((code, conclusion, conf, evidence))

    if raw_signal < -edge_short:
        code = "STRONG_SELL" if sell >= sshort else "SELL"
        conclusion = (
            f"{code} - short-primary {prim_tf} (short edge, context TF adjusts size only)"
        )
        return _emit((code, conclusion, conf, evidence))

    evidence.append(
        f"MTF: signal between dead zone and edge (|{raw_signal:.3f}| in ({dead:.2f},{edge_long:.2f})) — HOLD"
    )
    return _emit(
        (
            "HOLD",
            "HOLD - MTF primary signal below entry edge",
            max(0.0, conf * 0.25),
            evidence,
        )
    )


def synthesize_mtf_trading_decision(
    model_predictions: List[Dict[str, Any]],
    settings: Any,
    symbol: Optional[str] = None,
) -> Optional[Tuple[str, str, float, List[str]]]:
    """
    Return (decision_code, conclusion, step5_confidence, evidence_lines) or None to use legacy consensus.

    decision_code is one of: STRONG_BUY, BUY, STRONG_SELL, SELL, HOLD.
    """
    edge_hist_val: Optional[float] = None

    if not getattr(settings, "mtf_decision_engine_enabled", False):
        return None
    if not model_predictions:
        return None

    by_tf: Dict[str, Dict[str, Any]] = index_predictions_by_timeframe(model_predictions)
    if not by_tf:
        return None

    arch = (getattr(settings, "mtf_signal_architecture", "standard") or "standard").strip().lower()
    if arch == "short_tf_primary":
        return _synthesize_short_tf_primary(by_tf, settings, symbol)

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
        allow_partial = bool(
            getattr(settings, "mtf_allow_partial_timeframe_fallback", True)
        )
        if allow_partial and by_tf:
            sorted_tfs = sorted(by_tf.keys())
            if trend is None:
                trend_tf = sorted_tfs[-1]
                trend = by_tf.get(trend_tf)
            if entry is None:
                entry_tf = sorted_tfs[0]
                entry = by_tf.get(entry_tf)
            if trend is not None and entry is not None:
                logger.info(
                    "mtf_partial_timeframe_fallback",
                    have=list(by_tf.keys()),
                    selected_trend_tf=trend_tf,
                    selected_entry_tf=entry_tf,
                    trend_order=trend_order,
                    entry_order=entry_order,
                )
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
    use_proba = bool(getattr(settings, "mtf_use_entry_proba_gating", True))
    trend_buy_min = float(getattr(settings, "mtf_trend_min_buy_prob", 0.6))
    trend_sell_min = float(getattr(settings, "mtf_trend_min_sell_prob", 0.6))
    entry_buy_min = float(getattr(settings, "mtf_entry_min_buy_prob", 0.6))
    entry_sell_min = float(getattr(settings, "mtf_entry_min_sell_prob", 0.6))
    strong_buy_min = float(getattr(settings, "mtf_strong_min_buy_prob", 0.72))
    strong_sell_min = float(getattr(settings, "mtf_strong_min_sell_prob", 0.72))

    t_sig = trend["signal"]
    e_sig = entry["signal"]
    e_conf = entry["confidence"]
    trend_proba = trend.get("proba")
    entry_proba = entry.get("proba")
    can_use_proba = bool(use_proba and trend_proba and entry_proba)
    trend_buy = float(trend_proba["buy"]) if trend_proba else None
    trend_sell = float(trend_proba["sell"]) if trend_proba else None
    entry_buy = float(entry_proba["buy"]) if entry_proba else None
    entry_sell = float(entry_proba["sell"]) if entry_proba else None

    if (
        can_use_proba
        and entry_buy is not None
        and entry_sell is not None
    ):
        edge_hist_val = abs(entry_buy - entry_sell)

    def _emit(
        result: Tuple[str, str, float, List[str]],
    ) -> Tuple[str, str, float, List[str]]:
        if symbol and edge_hist_val is not None:
            EntryEdgeTracker.observe(symbol, edge_hist_val)
        return result

    use_trend_diff = bool(getattr(settings, "mtf_trend_use_prob_diff", True))
    trend_edge = float(getattr(settings, "mtf_trend_prob_diff_edge", 0.05))
    use_entry_diff = bool(getattr(settings, "mtf_entry_use_prob_diff", True))
    entry_edge = float(getattr(settings, "mtf_entry_prob_diff_edge", 0.08))
    prob_floor = float(getattr(settings, "mtf_entry_min_max_prob_floor", 0.0) or 0.0)
    strong_diff = float(getattr(settings, "mtf_strong_entry_prob_diff", 0.15))

    gap_min = float(getattr(settings, "mtf_min_confidence_gap", 0.0) or 0.0)
    if (
        can_use_proba
        and gap_min > 0
        and entry_buy is not None
        and entry_sell is not None
        and abs(entry_buy - entry_sell) < gap_min
    ):
        evidence_pre: List[str] = [
            f"MTF trend: tf={trend_tf} entry_signal={t_sig:+.3f}",
            f"MTF entry: tf={entry_tf} entry_signal={e_sig:+.3f} conf={e_conf:.2f} (min {min_conf:.2f})",
            f"MTF: entry |buy-sell|={abs(entry_buy - entry_sell):.3f} < {gap_min} — HOLD",
        ]
        return _emit(
            (
                "HOLD",
                "HOLD - MTF entry probability gap below minimum",
                max(0.0, e_conf * 0.25),
                evidence_pre,
            )
        )

    evidence: List[str] = [
        f"MTF trend: tf={trend_tf} entry_signal={t_sig:+.3f}",
        f"MTF entry: tf={entry_tf} entry_signal={e_sig:+.3f} conf={e_conf:.2f} (min {min_conf:.2f})",
    ]
    if can_use_proba:
        evidence.extend(
            [
                f"MTF trend proba: buy={trend_buy:.2f} sell={trend_sell:.2f}",
                f"MTF entry proba: buy={entry_buy:.2f} sell={entry_sell:.2f}",
            ]
        )
    if filt is not None and filt_tf:
        evidence.append(
            f"MTF filter: tf={filt_tf} entry_signal={filt['signal']:+.3f}"
        )

    if can_use_proba:
        if (
            use_trend_diff
            and trend_buy is not None
            and trend_sell is not None
        ):
            if (trend_buy - trend_sell) >= trend_edge:
                trend_dir = "bull"
            elif (trend_sell - trend_buy) >= trend_edge:
                trend_dir = "bear"
            else:
                evidence.append(
                    f"MTF: trend prob diff below edge ({trend_edge:.2f}) — HOLD"
                )
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF trend probability edge too small",
                        max(0.0, e_conf * 0.3),
                        evidence,
                    )
                )
        else:
            if trend_buy >= trend_buy_min:
                trend_dir = "bull"
            elif trend_sell >= trend_sell_min:
                trend_dir = "bear"
            else:
                evidence.append("MTF: trend proba below thresholds — HOLD")
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF trend probabilities below threshold",
                        max(0.0, e_conf * 0.3),
                        evidence,
                    )
                )
    else:
        evidence.append("MTF: using signal-threshold fallback (entry_proba missing/disabled)")
        if t_sig > t_thr:
            trend_dir = "bull"
        elif t_sig < -t_thr:
            trend_dir = "bear"
        else:
            evidence.append("MTF: trend neutral — HOLD")
            return _emit(
                (
                    "HOLD",
                    "HOLD - MTF trend timeframe neutral",
                    max(0.0, e_conf * 0.3),
                    evidence,
                )
            )

    # Optional shorter-TF veto: contradicts intended direction
    if filt is not None:
        if trend_dir == "bull" and e_sig > e_thr and filt["signal"] < -0.05:
            evidence.append("MTF: filter TF conflicts with BUY — HOLD")
            return _emit(
                ("HOLD", "HOLD - MTF filter conflicts with bullish entry", e_conf * 0.4, evidence)
            )
        if trend_dir == "bear" and e_sig < -e_thr and filt["signal"] > 0.05:
            evidence.append("MTF: filter TF conflicts with SELL — HOLD")
            return _emit(
                ("HOLD", "HOLD - MTF filter conflicts with bearish entry", e_conf * 0.4, evidence)
            )

    # Strict trend-entry alignment guard (hard filter)
    use_strict_alignment = bool(getattr(settings, "mtf_strict_trend_entry_alignment", True))
    if use_strict_alignment:
        if trend_dir == "bull" and e_sig <= 0:
            evidence.append("MTF: entry TF non-bullish while trend TF is bullish — HOLD")
            return _emit(("HOLD", "HOLD - MTF strict trend/entry alignment", 0.0, evidence))
        if trend_dir == "bear" and e_sig >= 0:
            evidence.append("MTF: entry TF non-bearish while trend TF is bearish — HOLD")
            return _emit(("HOLD", "HOLD - MTF strict trend/entry alignment", 0.0, evidence))

    pct_enabled = bool(getattr(settings, "mtf_entry_strength_percentile_enabled", False))
    pct_val = int(getattr(settings, "mtf_entry_strength_percentile", 80))
    pct_min_n = int(getattr(settings, "mtf_entry_strength_percentile_min_samples", 30))

    def _percentile_blocks() -> Optional[Tuple[str, str, float, List[str]]]:
        if not pct_enabled or edge_hist_val is None:
            return None
        ok, thr = EntryEdgeTracker.strength_vs_prior_percentile(
            symbol or "", edge_hist_val, pct_val, pct_min_n
        )
        if ok:
            return None
        ev = evidence + [
            f"MTF: entry |buy-sell|={edge_hist_val:.3f} below P{pct_val} prior={thr:.3f} — HOLD",
        ]
        return (
            "HOLD",
            "HOLD - MTF entry strength below rolling percentile",
            max(0.0, e_conf * 0.25),
            ev,
        )

    if trend_dir == "bull":
        if can_use_proba:
            if e_conf < min_conf:
                evidence.append("MTF: entry confidence below minimum — HOLD")
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF entry not confirming trend (BUY)",
                        0.0,
                        evidence,
                    )
                )
            if use_entry_diff and entry_buy is not None and entry_sell is not None:
                directed = entry_buy - entry_sell
                if directed < entry_edge:
                    evidence.append(
                        f"MTF: entry long edge {directed:.3f} < {entry_edge:.2f} — HOLD"
                    )
                    return _emit(
                        (
                            "HOLD",
                            "HOLD - MTF entry long edge below minimum",
                            0.0,
                            evidence,
                        )
                    )
                if prob_floor > 0 and max(entry_buy, entry_sell) < prob_floor:
                    evidence.append(
                        f"MTF: max(buy,sell) {max(entry_buy, entry_sell):.3f} < floor {prob_floor:.2f} — HOLD"
                    )
                    return _emit(
                        (
                            "HOLD",
                            "HOLD - MTF entry absolute probability too low",
                            0.0,
                            evidence,
                        )
                    )
            elif entry_buy < entry_buy_min:
                evidence.append("MTF: entry BUY probability below threshold — HOLD")
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF entry not confirming trend (BUY)",
                        0.0,
                        evidence,
                    )
                )
        else:
            if e_sig <= e_thr or e_conf < min_conf:
                evidence.append("MTF: entry TF not confirming bullish trend — HOLD")
                return _emit(
                    ("HOLD", "HOLD - MTF entry not confirming 15m+ trend (BUY)", 0.0, evidence)
                )
        blocked = _percentile_blocks()
        if blocked is not None:
            return _emit(blocked)
        strong_long = False
        if can_use_proba and use_entry_diff and entry_buy is not None and entry_sell is not None:
            strong_long = (entry_buy - entry_sell) >= strong_diff and e_conf >= strong_buy_min
        elif can_use_proba and entry_buy >= strong_buy_min and e_conf >= strong_buy_min:
            strong_long = True
        elif (not can_use_proba) and e_sig > 0.45 and e_conf >= 0.72:
            strong_long = True
        if strong_long:
            return _emit(
                (
                    "STRONG_BUY",
                    f"STRONG_BUY - MTF aligned (trend {trend_tf} + entry {entry_tf})",
                    e_conf,
                    evidence,
                )
            )
        return _emit(
            (
                "BUY",
                f"BUY - MTF aligned (trend {trend_tf} + entry {entry_tf})",
                e_conf,
                evidence,
            )
        )

    # bear
    if can_use_proba:
        if e_conf < min_conf:
            evidence.append("MTF: entry confidence below minimum — HOLD")
            return _emit(
                (
                    "HOLD",
                    "HOLD - MTF entry not confirming trend (SELL)",
                    0.0,
                    evidence,
                )
            )
        if use_entry_diff and entry_buy is not None and entry_sell is not None:
            directed = entry_sell - entry_buy
            if directed < entry_edge:
                evidence.append(
                    f"MTF: entry short edge {directed:.3f} < {entry_edge:.2f} — HOLD"
                )
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF entry short edge below minimum",
                        0.0,
                        evidence,
                    )
                )
            if prob_floor > 0 and max(entry_buy, entry_sell) < prob_floor:
                evidence.append(
                    f"MTF: max(buy,sell) {max(entry_buy, entry_sell):.3f} < floor {prob_floor:.2f} — HOLD"
                )
                return _emit(
                    (
                        "HOLD",
                        "HOLD - MTF entry absolute probability too low",
                        0.0,
                        evidence,
                    )
                )
        elif entry_sell < entry_sell_min:
            evidence.append("MTF: entry SELL probability below threshold — HOLD")
            return _emit(
                (
                    "HOLD",
                    "HOLD - MTF entry not confirming trend (SELL)",
                    0.0,
                    evidence,
                )
            )
    else:
        if e_sig >= -e_thr or e_conf < min_conf:
            evidence.append("MTF: entry TF not confirming bearish trend — HOLD")
            return _emit(
                ("HOLD", "HOLD - MTF entry not confirming trend (SELL)", 0.0, evidence)
            )
    blocked = _percentile_blocks()
    if blocked is not None:
        return _emit(blocked)
    strong_short = False
    if can_use_proba and use_entry_diff and entry_buy is not None and entry_sell is not None:
        strong_short = (entry_sell - entry_buy) >= strong_diff and e_conf >= strong_sell_min
    elif can_use_proba and entry_sell >= strong_sell_min and e_conf >= strong_sell_min:
        strong_short = True
    elif (not can_use_proba) and e_sig < -0.45 and e_conf >= 0.72:
        strong_short = True
    if strong_short:
        return _emit(
            (
                "STRONG_SELL",
                f"STRONG_SELL - MTF aligned (trend {trend_tf} + entry {entry_tf})",
                e_conf,
                evidence,
            )
        )
    return _emit(
        (
            "SELL",
            f"SELL - MTF aligned (trend {trend_tf} + entry {entry_tf})",
            e_conf,
            evidence,
        )
    )
