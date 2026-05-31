"""Structural market-state labels for JackSparrow MSO v50 (classification, not returns)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEY_TO_BARS

MSO_STATE_DIMENSIONS: Tuple[str, ...] = (
    "trend_regime",
    "vol_regime",
    "breakout_state",
    "liquidity_condition",
    "momentum_quality",
    "compression_expansion",
)

TREND_REGIME_CLASSES: Tuple[str, ...] = (
    "STRONG_BULL",
    "WEAK_BULL",
    "RANGE",
    "WEAK_BEAR",
    "STRONG_BEAR",
)
VOL_REGIME_CLASSES: Tuple[str, ...] = (
    "LOW_VOL",
    "EXPANDING_VOL",
    "HIGH_VOL",
    "EXTREME_VOL",
)
BREAKOUT_CLASSES: Tuple[str, ...] = (
    "NO_BREAKOUT",
    "BREAKOUT_FORMING",
    "BREAKOUT_CONFIRMED",
    "FAKE_BREAKOUT",
    "BREAKOUT_EXHAUSTION",
)
LIQUIDITY_CLASSES: Tuple[str, ...] = (
    "BALANCED",
    "LONG_LIQ_RISK",
    "SHORT_LIQ_RISK",
    "STOP_HUNT_ENV",
    "LIQ_SWEEP_ACTIVE",
)
MOMENTUM_CLASSES: Tuple[str, ...] = (
    "HEALTHY",
    "WEAK",
    "DIVERGING",
    "EXHAUSTED",
)
COMPRESSION_CLASSES: Tuple[str, ...] = (
    "COMPRESSION",
    "PRE_EXPANSION",
    "EXPANSION",
    "POST_EXPANSION",
)

MSO_MODEL_FAMILY = "market_state_oracle_v50"
MSO_ARTIFACT_FORMAT = "jacksparrow_mso_v50_v1"
MSO_FEATURE_VERSION = "jacksparrow_mso_features_v1"

_EPS = 1e-12


def _atr_series(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev).abs(),
            (low - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=max(2, window // 2)).mean()


def build_trend_regime_labels(
    df_feat: pd.DataFrame,
    *,
    forward_bars: int,
    train_end_idx: Optional[int] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """5-class trend regime at t+forward_bars from ADX, trend_mom, hurst."""
    fb = int(forward_bars)
    n = len(df_feat)
    out: List[Optional[str]] = [None] * n
    for col in ("adx_14", "trend_mom", "hurst_60"):
        if col not in df_feat.columns:
            raise ValueError(f"build_trend_regime_labels missing column {col!r}")

    adx = pd.to_numeric(df_feat["adx_14"], errors="coerce")
    tm = pd.to_numeric(df_feat["trend_mom"], errors="coerce")
    hurst = pd.to_numeric(df_feat["hurst_60"], errors="coerce")
    if train_end_idx is not None:
        adx_fit = adx.iloc[: int(train_end_idx)]
    else:
        adx_fit = adx
    if len(adx_fit) >= 100 and adx_fit.notna().any():
        adx_thr_strong = float(adx_fit.quantile(0.70))
        adx_thr_weak = float(adx_fit.quantile(0.45))
    else:
        adx_thr_strong = 28.0
        adx_thr_weak = 20.0

    for i in range(n - fb):
        j = i + fb
        a = float(adx.iloc[j]) if pd.notna(adx.iloc[j]) else np.nan
        t = float(tm.iloc[j]) if pd.notna(tm.iloc[j]) else np.nan
        h = float(hurst.iloc[j]) if pd.notna(hurst.iloc[j]) else np.nan
        if not np.isfinite(a) or not np.isfinite(t):
            continue
        trending = a > adx_thr_weak and (not np.isfinite(h) or h > 0.52)
        if trending and a > adx_thr_strong and abs(t) > 0.0008:
            out[i] = "STRONG_BULL" if t > 0 else "STRONG_BEAR"
        elif trending:
            out[i] = "WEAK_BULL" if t > 0 else "WEAK_BEAR"
        else:
            out[i] = "RANGE"

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {c: int((series == c).sum()) for c in TREND_REGIME_CLASSES}
    stats = {
        "forward_bars": fb,
        "labeled_fraction": float(series.notna().mean()),
        "class_counts": counts,
        "adx_thr_strong": adx_thr_strong,
        "adx_thr_weak": adx_thr_weak,
        "train_end_idx": train_end_idx,
    }
    return series, stats


def build_vol_regime_labels(
    close: pd.Series,
    *,
    forward_bars: int,
    atr_window: int = 14,
    baseline_window: int = 200,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """4-class volatility regime from future vs historical ATR."""
    c = close.astype(float)
    high = c * 1.001
    low = c * 0.999
    if "high" in close.index.names:
        pass
    fb = int(forward_bars)
    atr = _atr_series(c, c, c, window=atr_window)
    n = len(c)
    out = pd.Series(np.nan, index=c.index, dtype=object)
    baseline = atr.rolling(baseline_window, min_periods=50).median()

    for i in range(n - fb):
        cur = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        bl = float(baseline.iloc[i]) if pd.notna(baseline.iloc[i]) else np.nan
        if not np.isfinite(cur) or not np.isfinite(bl) or bl <= 0:
            continue
        fut = atr.iloc[i + 1 : i + fb + 1]
        if int(fut.notna().sum()) < max(1, fb // 2):
            continue
        fut_mean = float(fut.mean())
        ratio = fut_mean / max(cur, _EPS)
        pct = cur / bl
        if pct > 1.8 or ratio > 2.0:
            out.iloc[i] = "EXTREME_VOL"
        elif pct > 1.35 or ratio > 1.35:
            out.iloc[i] = "HIGH_VOL"
        elif ratio > 1.15:
            out.iloc[i] = "EXPANDING_VOL"
        else:
            out.iloc[i] = "LOW_VOL"

    counts = {c: int((out == c).sum()) for c in VOL_REGIME_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
    }


def build_breakout_state_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
    atr_window: int = 14,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Breakout labels from future ATR expansion ratio + OI confirmation."""
    c = close.astype(float)
    high = pd.to_numeric(df_feat.get("high", c), errors="coerce") if "high" in df_feat.columns else c
    low = pd.to_numeric(df_feat.get("low", c), errors="coerce") if "low" in df_feat.columns else c
    if "high" not in df_feat.columns:
        ret = c.pct_change(fill_method=None).fillna(0)
        high = c * (1 + ret.abs())
        low = c * (1 - ret.abs())
    atr = _atr_series(high, low, c, window=atr_window)
    oi_acc = pd.to_numeric(
        df_feat.get("oi_acceleration", pd.Series(0.0, index=df_feat.index)),
        errors="coerce",
    )
    fb = int(forward_bars)
    n = len(c)
    out = pd.Series(np.nan, index=c.index, dtype=object)

    for i in range(n - fb):
        cur_atr = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        if not np.isfinite(cur_atr) or cur_atr <= 0:
            continue
        fut_atr = atr.iloc[i + 1 : i + fb + 1]
        if int(fut_atr.notna().sum()) < max(1, fb // 2):
            continue
        expansion = float(fut_atr.mean()) / cur_atr
        oi_spike = float(oi_acc.iloc[i]) if pd.notna(oi_acc.iloc[i]) else 0.0
        ret_fwd = float(c.iloc[i + fb] / c.iloc[i] - 1.0) if c.iloc[i] > 0 else 0.0

        if expansion > 2.0:
            if abs(oi_spike) < 0.003 and abs(ret_fwd) < 0.002:
                out.iloc[i] = "FAKE_BREAKOUT"
            else:
                out.iloc[i] = "BREAKOUT_CONFIRMED"
        elif expansion > 1.4:
            out.iloc[i] = "BREAKOUT_FORMING"
        elif expansion < 0.85 and i + fb < n:
            out.iloc[i] = "BREAKOUT_EXHAUSTION"
        else:
            out.iloc[i] = "NO_BREAKOUT"

    counts = {c: int((out == c).sum()) for c in BREAKOUT_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
    }


def build_liquidity_condition_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Liquidity proxy labels from OI, funding, wicks (no historical liquidation API)."""
    _ = forward_bars
    n = len(df_feat)
    oi_z = pd.to_numeric(df_feat.get("oi_zscore", 0), errors="coerce")
    fund_z = pd.to_numeric(df_feat.get("funding_zscore", 0), errors="coerce")
    wick = pd.to_numeric(df_feat.get("wick_asym", 0), errors="coerce")
    oi_acc = pd.to_numeric(df_feat.get("oi_acceleration", 0), errors="coerce")
    tm = pd.to_numeric(df_feat.get("trend_mom", 0), errors="coerce")
    c = close.astype(float)
    ret3 = c.pct_change(3, fill_method=None)

    out: List[str] = []
    for i in range(n):
        oz = float(oi_z.iloc[i]) if pd.notna(oi_z.iloc[i]) else 0.0
        fz = float(fund_z.iloc[i]) if pd.notna(fund_z.iloc[i]) else 0.0
        wk = float(wick.iloc[i]) if pd.notna(wick.iloc[i]) else 0.0
        oa = float(oi_acc.iloc[i]) if pd.notna(oi_acc.iloc[i]) else 0.0
        t = float(tm.iloc[i]) if pd.notna(tm.iloc[i]) else 0.0
        r3 = float(ret3.iloc[i]) if pd.notna(ret3.iloc[i]) else 0.0

        if abs(wk) > 0.6 and abs(oa) > 0.008 and abs(r3) > 0.004:
            out.append("STOP_HUNT_ENV")
        elif oz > 2.0 and abs(r3) > 0.01 and oa > 0.01:
            out.append("LIQ_SWEEP_ACTIVE")
        elif oz > 1.8 and fz > 1.2 and t > 0:
            out.append("LONG_LIQ_RISK")
        elif oz > 1.8 and fz < -1.2 and t < 0:
            out.append("SHORT_LIQ_RISK")
        else:
            out.append("BALANCED")

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {c: int((series == c).sum()) for c in LIQUIDITY_CLASSES}
    return series, {"labeled_fraction": 1.0, "class_counts": counts}


def build_momentum_quality_labels(
    df_feat: pd.DataFrame,
    *,
    forward_bars: int,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Momentum quality from RSI structure and price/OI divergence at t+N."""
    fb = int(forward_bars)
    n = len(df_feat)
    rsi = pd.to_numeric(df_feat.get("rsi_14", 50), errors="coerce")
    rsi_mom = pd.to_numeric(df_feat.get("rsi_mom", 0), errors="coerce")
    tm = pd.to_numeric(df_feat.get("trend_mom", 0), errors="coerce")
    oi_div = pd.to_numeric(df_feat.get("oi_price_divergence", 0), errors="coerce")
    out: List[Optional[str]] = [None] * n

    for i in range(n - fb):
        j = i + fb
        r = float(rsi.iloc[j]) if pd.notna(rsi.iloc[j]) else 50.0
        rm = float(rsi_mom.iloc[j]) if pd.notna(rsi_mom.iloc[j]) else 0.0
        t = float(tm.iloc[j]) if pd.notna(tm.iloc[j]) else 0.0
        d = float(oi_div.iloc[j]) if pd.notna(oi_div.iloc[j]) else 0.0

        if (r > 70 and t < 0) or (r < 30 and t > 0) or abs(d) > 0.02:
            out[i] = "DIVERGING"
        elif (r > 75 or r < 25) and abs(rm) < 0.5:
            out[i] = "EXHAUSTED"
        elif abs(t) > 0.0005 and abs(rm) > 0.3:
            out[i] = "HEALTHY"
        else:
            out[i] = "WEAK"

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {c: int((series == c).sum()) for c in MOMENTUM_CLASSES}
    return series, {
        "forward_bars": fb,
        "labeled_fraction": float(series.notna().mean()),
        "class_counts": counts,
    }


def build_compression_expansion_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Compression/expansion cycle from BB width percentile and future ATR."""
    c = close.astype(float)
    bb_w = pd.to_numeric(df_feat.get("bb_width", np.nan), errors="coerce")
    atr_pct = pd.to_numeric(df_feat.get("atr_pct", np.nan), errors="coerce")
    fb = int(forward_bars)
    n = len(c)
    bb_pct = bb_w.rolling(200, min_periods=30).apply(
        lambda x: float((x.iloc[-1] <= x).mean()) if len(x) else np.nan,
        raw=False,
    )
    atr = _atr_series(c, c, c)
    out = pd.Series(np.nan, index=c.index, dtype=object)

    for i in range(n - fb):
        pct = float(bb_pct.iloc[i]) if pd.notna(bb_pct.iloc[i]) else np.nan
        ap = float(atr_pct.iloc[i]) if pd.notna(atr_pct.iloc[i]) else np.nan
        cur_atr = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        if not np.isfinite(cur_atr) or cur_atr <= 0:
            continue
        fut_atr = float(atr.iloc[i + 1 : i + fb + 1].mean())
        exp_ratio = fut_atr / cur_atr

        if np.isfinite(pct) and pct < 0.15 and exp_ratio > 1.25:
            out.iloc[i] = "PRE_EXPANSION"
        elif exp_ratio > 1.4:
            out.iloc[i] = "EXPANSION"
        elif exp_ratio < 0.9 and np.isfinite(pct) and pct > 0.7:
            out.iloc[i] = "POST_EXPANSION"
        elif np.isfinite(pct) and pct < 0.25 and (not np.isfinite(ap) or ap < 0.5):
            out.iloc[i] = "COMPRESSION"
        else:
            out.iloc[i] = "COMPRESSION"

    counts = {c: int((out == c).sum()) for c in COMPRESSION_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
    }


_LABEL_BUILDERS = {
    "vol_regime": lambda df, close, fb: build_vol_regime_labels(close, forward_bars=fb),
    "breakout_state": lambda df, close, fb: build_breakout_state_labels(
        df, close, forward_bars=fb
    ),
    "liquidity_condition": lambda df, close, fb: build_liquidity_condition_labels(
        df, close, forward_bars=fb
    ),
    "momentum_quality": lambda df, close, fb: build_momentum_quality_labels(
        df, forward_bars=fb
    ),
    "compression_expansion": lambda df, close, fb: build_compression_expansion_labels(
        df, close, forward_bars=fb
    ),
}


def build_mso_label(
    df_feat: pd.DataFrame,
    close: pd.Series,
    state_dimension: str,
    forward_bars: int,
    train_end_idx: Optional[int] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Dispatch label builder for one state dimension."""
    key = str(state_dimension).strip()
    fb = int(forward_bars)
    if key == "trend_regime":
        return build_trend_regime_labels(
            df_feat, forward_bars=fb, train_end_idx=train_end_idx
        )
    if key not in _LABEL_BUILDERS:
        raise ValueError(f"Unknown MSO state dimension: {key!r}")
    return _LABEL_BUILDERS[key](df_feat, close, fb)


def classes_for_dimension(state_dimension: str) -> Tuple[str, ...]:
    """Return ordered class names for a state dimension."""
    mapping = {
        "trend_regime": TREND_REGIME_CLASSES,
        "vol_regime": VOL_REGIME_CLASSES,
        "breakout_state": BREAKOUT_CLASSES,
        "liquidity_condition": LIQUIDITY_CLASSES,
        "momentum_quality": MOMENTUM_CLASSES,
        "compression_expansion": COMPRESSION_CLASSES,
    }
    if state_dimension not in mapping:
        raise ValueError(f"Unknown MSO state dimension: {state_dimension!r}")
    return mapping[state_dimension]


def horizon_keys_and_bars() -> Dict[str, int]:
    """Canonical MSO horizon keys aligned with v43 multi-head."""
    return dict(V43_HORIZON_KEY_TO_BARS)
