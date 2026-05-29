"""Label schemes for JackSparrow v43 training (forward return + state heads)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Regime class order (stable for training + inference).
V43_REGIME_CLASSES: Tuple[str, ...] = (
    "trending_up",
    "trending_down",
    "ranging",
    "vol_expansion",
)

# Appendix B feature tiers for state-head training.
# Phase 5: horizon-specialised masks (populate after importance analysis).
V43_HORIZON_FEATURE_MASKS: Dict[str, Tuple[str, ...]] = {}

V43_STATE_HEAD_FEATURE_TIERS: Dict[str, Tuple[str, ...]] = {
    "regime": (
        "adx_14",
        "di_spread",
        "hurst_60",
        "trend_mom",
        "trend_conf",
        "atr_pct",
        "vol_regime",
        "bb_width",
        "sr_compression",
        "h1_trend",
        "h1_adx",
        "h1_vol_regime",
        "h_trend",
        "h_trend_200",
    ),
    "vol_expansion": (
        "atr_pct",
        "vol_regime",
        "bb_width",
        "oi_zscore",
        "oi_change_6",
        "oi_price_divergence",
        "oi_acceleration",
        "oi_delta_z",
        "funding_zscore",
        "funding_mom",
        "funding_rate_roc",
        "basis_zscore",
        "basis_momentum",
        "funding_x_oi",
    ),
    "trade_quality": (
        "rsi_14",
        "rsi_mom",
        "macd_hist_n",
        "bb_pos",
        "obv_ret",
        "cmf_20",
        "body",
        "body_dir",
        "wick_asym",
        "kauf_er_20",
        "ema_21_50_cross",
        "price_ema21",
        "price_ema100",
    ),
}


def build_forward_labels(close: pd.Series, forward_bars: int) -> pd.Series:
    """Forward return: close[t+h]/close[t] - 1."""
    c = close.astype(float)
    return c.shift(-int(forward_bars)) / c - 1.0


def build_cost_aware_forward_labels(
    close: pd.Series,
    forward_bars: int,
    *,
    round_trip_cost: float,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Forward return labels; sub-cost moves become NaN (excluded from training)."""
    raw = build_forward_labels(close, forward_bars)
    cost = float(round_trip_cost)
    tradable = raw.abs() >= cost
    masked = raw.where(tradable, np.nan)
    valid = raw.notna()
    stats = {
        "round_trip_cost_pct": cost,
        "tradable_label_fraction": float(tradable[valid].mean()) if valid.any() else 0.0,
        "sub_cost_suppressed_fraction": float((valid & ~tradable).mean()) if valid.any() else 0.0,
    }
    return masked, stats


def build_triple_barrier_labels(
    close: pd.Series,
    *,
    forward_bars: int,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Triple-barrier labels: +1 TP hit first, -1 SL hit first, 0 timeout within horizon."""
    c = close.astype(float)
    n = len(c)
    fb = int(forward_bars)
    tp = float(take_profit_pct)
    sl = float(stop_loss_pct)
    out = pd.Series(np.nan, index=c.index, dtype=float)
    tp_hits = 0
    sl_hits = 0
    timeouts = 0
    for i in range(n - fb):
        entry = float(c.iloc[i])
        if not np.isfinite(entry) or entry <= 0:
            continue
        window = c.iloc[i + 1 : i + fb + 1].astype(float)
        if window.empty:
            continue
        rel = window / entry - 1.0
        tp_idx = rel[rel >= tp].index
        sl_idx = rel[rel <= -sl].index
        first_tp = tp_idx[0] if len(tp_idx) else None
        first_sl = sl_idx[0] if len(sl_idx) else None
        if first_tp is not None and (first_sl is None or first_tp <= first_sl):
            out.iloc[i] = 1.0
            tp_hits += 1
        elif first_sl is not None:
            out.iloc[i] = -1.0
            sl_hits += 1
        else:
            out.iloc[i] = 0.0
            timeouts += 1
    valid = out.notna()
    total = int(valid.sum())
    stats = {
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
        "forward_bars": fb,
        "labeled_fraction": float(total / max(1, n)),
        "tp_hit_fraction": float(tp_hits / max(1, total)),
        "sl_hit_fraction": float(sl_hits / max(1, total)),
        "timeout_fraction": float(timeouts / max(1, total)),
    }
    return out, stats


def _classify_regime_row(
    adx: float,
    hurst: float,
    trend_mom: float,
    vol_regime: float,
    atr_pct: float,
    vol_q80: float,
    atr_q90: float,
) -> str:
    """Deterministic regime label for one bar (migration spec §1.1)."""
    if np.isfinite(vol_regime) and vol_regime > vol_q80:
        return "vol_expansion"
    if np.isfinite(atr_pct) and atr_pct > atr_q90:
        return "vol_expansion"
    if (
        np.isfinite(adx)
        and adx > 22.0
        and np.isfinite(hurst)
        and hurst > 0.55
        and np.isfinite(trend_mom)
    ):
        if trend_mom > 0:
            return "trending_up"
        if trend_mom < 0:
            return "trending_down"
    return "ranging"


def build_regime_labels(
    df_feat: pd.DataFrame,
    *,
    n_bars: int = 3,
    vol_regime_window: int = 8640,
    atr_window: int = 8640,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """4-class regime labels at t+N using features evaluated at t+N."""
    n_shift = int(n_bars)
    work = df_feat.copy()
    for col in ("adx_14", "hurst_60", "trend_mom", "vol_regime", "atr_pct"):
        if col not in work.columns:
            raise ValueError(f"build_regime_labels missing column {col!r}")

    vol_s = pd.to_numeric(work["vol_regime"], errors="coerce")
    atr_s = pd.to_numeric(work["atr_pct"], errors="coerce")
    vol_q80 = vol_s.rolling(vol_regime_window, min_periods=200).quantile(0.80)
    atr_q90 = atr_s.rolling(atr_window, min_periods=200).quantile(0.90)

    labels: List[Optional[str]] = []
    idx = work.index
    for i in range(len(work)):
        j = i + n_shift
        if j >= len(work):
            labels.append(None)
            continue
        row = work.iloc[j]
        lab = _classify_regime_row(
            float(row["adx_14"]),
            float(row["hurst_60"]),
            float(row["trend_mom"]),
            float(row["vol_regime"]),
            float(row["atr_pct"]),
            float(vol_q80.iloc[j]) if pd.notna(vol_q80.iloc[j]) else np.inf,
            float(atr_q90.iloc[j]) if pd.notna(atr_q90.iloc[j]) else np.inf,
        )
        labels.append(lab)

    out = pd.Series(labels, index=idx, dtype=object)
    class_to_int = {c: i for i, c in enumerate(V43_REGIME_CLASSES)}
    y_int = out.map(class_to_int)
    valid = y_int.notna()
    counts = {c: int((out == c).sum()) for c in V43_REGIME_CLASSES}
    stats: Dict[str, Any] = {
        "n_bars": n_shift,
        "labeled_fraction": float(valid.mean()) if len(out) else 0.0,
        "class_counts": counts,
    }
    return out, stats


def build_vol_expansion_labels(
    close: pd.Series,
    *,
    forward_bars: int,
    vol_window: int = 200,
    mult: float = 1.25,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Binary: future realized vol over N bars exceeds rolling median baseline."""
    c = close.astype(float)
    ret = c.pct_change(fill_method=None)
    fb = int(forward_bars)
    n = len(c)
    out = pd.Series(np.nan, index=c.index, dtype=float)

    min_hist = max(20, vol_window // 4)
    hist_vol = ret.rolling(vol_window, min_periods=min_hist).std()
    baseline = hist_vol.rolling(vol_window, min_periods=50).median()

    for i in range(n - fb):
        window = ret.iloc[i + 1 : i + fb + 1]
        if int(window.notna().sum()) < max(2, fb // 2):
            continue
        fv = float(window.std())
        bl = float(baseline.iloc[i]) if i < len(baseline) else np.nan
        if not np.isfinite(fv) or not np.isfinite(bl) or bl <= 0:
            continue
        out.iloc[i] = 1.0 if fv > mult * bl else 0.0

    valid = out.dropna()
    pos_frac = float((valid > 0).mean()) if not valid.empty else 0.0
    stats = {
        "forward_bars": fb,
        "vol_window": int(vol_window),
        "mult": float(mult),
        "expansion_fraction": pos_frac,
        "labeled_fraction": float(out.notna().mean()),
    }
    return out, stats


def build_trade_quality_labels(
    close: pd.Series,
    *,
    forward_bars: int,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Tuple[pd.Series, Dict[str, float]]:
    """Binary tp_first=1, sl_first=0; timeout excluded (NaN)."""
    tb, tb_stats = build_triple_barrier_labels(
        close,
        forward_bars=forward_bars,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )
    out = pd.Series(np.nan, index=tb.index, dtype=float)
    out[tb > 0] = 1.0
    out[tb < 0] = 0.0
    valid = out.dropna()
    stats = dict(tb_stats)
    stats["tp_first_fraction"] = float((valid > 0).mean()) if not valid.empty else 0.0
    stats["binary_labeled_fraction"] = float(out.notna().mean())
    return out, stats


def compare_label_schemes(
    close: pd.Series,
    *,
    forward_bars: int,
    round_trip_cost: float,
    take_profit_pct: float = 0.01,
    stop_loss_pct: float = 0.01,
) -> Dict[str, Any]:
    """Summarize simple / no-trade-band / triple-barrier label distributions."""
    raw = build_forward_labels(close, forward_bars)
    cost_masked, cost_stats = build_cost_aware_forward_labels(
        close, forward_bars, round_trip_cost=round_trip_cost
    )
    tb, tb_stats = build_triple_barrier_labels(
        close,
        forward_bars=forward_bars,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )
    valid_raw = raw.dropna()
    valid_cost = cost_masked.dropna()
    valid_tb = tb.dropna()

    def _moments(s: pd.Series) -> Dict[str, float]:
        if s.empty:
            return {"count": 0.0, "mean": 0.0, "std": 0.0, "positive_frac": 0.0}
        return {
            "count": float(s.size),
            "mean": float(s.mean()),
            "std": float(s.std()) if s.size > 1 else 0.0,
            "positive_frac": float((s > 0).mean()),
        }

    return {
        "forward_bars": int(forward_bars),
        "round_trip_cost": float(round_trip_cost),
        "simple_forward": _moments(valid_raw),
        "cost_aware_no_trade_band": {**_moments(valid_cost), **cost_stats},
        "triple_barrier": {
            **_moments(valid_tb),
            **tb_stats,
            "long_frac": float((valid_tb > 0).mean()) if not valid_tb.empty else 0.0,
            "short_frac": float((valid_tb < 0).mean()) if not valid_tb.empty else 0.0,
            "flat_frac": float((valid_tb == 0).mean()) if not valid_tb.empty else 0.0,
        },
    }
