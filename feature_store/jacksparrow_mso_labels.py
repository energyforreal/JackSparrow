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

# Fixed trend thresholds (no global quantiles — avoids RANGE collapse on train-only fit)
TREND_ADX_STRONG = 28.0
TREND_ADX_WEAK = 18.0
TREND_STRONG_MOM = 0.0005
TREND_HURST_MIN = 0.50

_MIN_TRAIN_FOR_QUANTILES = 100


def _train_fit_slice(series: pd.Series, train_end_idx: Optional[int]) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if train_end_idx is not None and int(train_end_idx) > 0:
        return s.iloc[: int(train_end_idx)]
    return s


def _train_quantile(
    series: pd.Series,
    train_end_idx: Optional[int],
    q: float,
    *,
    fallback: float,
) -> float:
    fit = _train_fit_slice(series, train_end_idx).dropna()
    if len(fit) < _MIN_TRAIN_FOR_QUANTILES:
        return float(fallback)
    return float(fit.quantile(q))


def _top_class_fraction(counts: Dict[str, int]) -> float:
    total = sum(int(v) for v in counts.values())
    if total <= 0:
        return 1.0
    return max(int(v) for v in counts.values()) / total


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


def _resolve_ohlcv(df_feat: pd.DataFrame, close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Resolve high/low/close for ATR; use df_feat OHLCV when present."""
    c = close.astype(float)
    if "high" in df_feat.columns and "low" in df_feat.columns:
        high = pd.to_numeric(df_feat["high"], errors="coerce")
        low = pd.to_numeric(df_feat["low"], errors="coerce")
    else:
        ret = c.pct_change(fill_method=None).fillna(0)
        high = c * (1 + ret.abs())
        low = c * (1 - ret.abs())
    return high, low, c


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
    # Fixed absolute ADX gates (leak-free, stable class mix vs train quantiles)
    adx_thr_strong = TREND_ADX_STRONG
    adx_thr_weak = TREND_ADX_WEAK
    threshold_mode = "fixed"

    for i in range(n - fb):
        j = i + fb
        a = float(adx.iloc[j]) if pd.notna(adx.iloc[j]) else np.nan
        t = float(tm.iloc[j]) if pd.notna(tm.iloc[j]) else np.nan
        h = float(hurst.iloc[j]) if pd.notna(hurst.iloc[j]) else np.nan
        if not np.isfinite(a) or not np.isfinite(t):
            continue
        strong_trend = a > adx_thr_strong and abs(t) > TREND_STRONG_MOM
        weak_trend = a > adx_thr_weak and (
            strong_trend or not np.isfinite(h) or h > TREND_HURST_MIN
        )
        if strong_trend:
            out[i] = "STRONG_BULL" if t > 0 else "STRONG_BEAR"
        elif weak_trend:
            out[i] = "WEAK_BULL" if t > 0 else "WEAK_BEAR"
        else:
            out[i] = "RANGE"

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {cls: int((series == cls).sum()) for cls in TREND_REGIME_CLASSES}
    stats = {
        "forward_bars": fb,
        "labeled_fraction": float(series.notna().mean()),
        "class_counts": counts,
        "adx_thr_strong": adx_thr_strong,
        "adx_thr_weak": adx_thr_weak,
        "threshold_mode": threshold_mode,
        "train_end_idx": train_end_idx,
    }
    return series, stats


def build_vol_regime_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
    atr_window: int = 14,
    baseline_window: int = 200,
    train_end_idx: Optional[int] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """4-class volatility regime from future vs historical ATR (train-slice quantiles)."""
    high, low, c = _resolve_ohlcv(df_feat, close)
    fb = int(forward_bars)
    atr = _atr_series(high, low, c, window=atr_window)
    n = len(c)
    out = pd.Series(np.nan, index=c.index, dtype=object)
    baseline = atr.rolling(baseline_window, min_periods=50).median()
    ratio_s = pd.Series(np.nan, index=c.index, dtype=float)
    pct_s = pd.Series(np.nan, index=c.index, dtype=float)

    for i in range(n - fb):
        cur = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        bl = float(baseline.iloc[i]) if pd.notna(baseline.iloc[i]) else np.nan
        if not np.isfinite(cur) or not np.isfinite(bl) or bl <= 0:
            continue
        fut = atr.iloc[i + 1 : i + fb + 1]
        if int(fut.notna().sum()) < max(1, fb // 2):
            continue
        fut_mean = float(fut.mean())
        ratio_s.iloc[i] = fut_mean / max(cur, _EPS)
        pct_s.iloc[i] = cur / bl

    ratio_exp = _train_quantile(ratio_s, train_end_idx, 0.70, fallback=1.08)
    ratio_high = _train_quantile(ratio_s, train_end_idx, 0.85, fallback=1.20)
    ratio_extreme = _train_quantile(ratio_s, train_end_idx, 0.95, fallback=1.35)
    pct_high = _train_quantile(pct_s, train_end_idx, 0.85, fallback=1.15)
    pct_extreme = _train_quantile(pct_s, train_end_idx, 0.95, fallback=1.25)

    for i in range(n - fb):
        ratio = float(ratio_s.iloc[i]) if pd.notna(ratio_s.iloc[i]) else np.nan
        pct = float(pct_s.iloc[i]) if pd.notna(pct_s.iloc[i]) else np.nan
        if not np.isfinite(ratio) or not np.isfinite(pct):
            continue
        if pct > pct_extreme or ratio > ratio_extreme:
            out.iloc[i] = "EXTREME_VOL"
        elif pct > pct_high or ratio > ratio_high:
            out.iloc[i] = "HIGH_VOL"
        elif ratio > ratio_exp:
            out.iloc[i] = "EXPANDING_VOL"
        else:
            out.iloc[i] = "LOW_VOL"

    counts = {cls: int((out == cls).sum()) for cls in VOL_REGIME_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
        "threshold_mode": "train_quantile",
        "ratio_exp": ratio_exp,
        "ratio_high": ratio_high,
        "ratio_extreme": ratio_extreme,
        "train_end_idx": train_end_idx,
    }


def build_breakout_state_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
    atr_window: int = 14,
    train_end_idx: Optional[int] = None,
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
    expansion_s = pd.Series(np.nan, index=c.index, dtype=float)

    for i in range(n - fb):
        cur_atr = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        if not np.isfinite(cur_atr) or cur_atr <= 0:
            continue
        fut_atr = atr.iloc[i + 1 : i + fb + 1]
        if int(fut_atr.notna().sum()) < max(1, fb // 2):
            continue
        expansion_s.iloc[i] = float(fut_atr.mean()) / cur_atr

    exp_form = _train_quantile(expansion_s, train_end_idx, 0.75, fallback=1.12)
    exp_conf = _train_quantile(expansion_s, train_end_idx, 0.90, fallback=1.25)
    exp_exhaust = _train_quantile(expansion_s, train_end_idx, 0.15, fallback=0.95)

    for i in range(n - fb):
        expansion = float(expansion_s.iloc[i]) if pd.notna(expansion_s.iloc[i]) else np.nan
        if not np.isfinite(expansion):
            continue
        oi_spike = float(oi_acc.iloc[i]) if pd.notna(oi_acc.iloc[i]) else 0.0
        ret_fwd = float(c.iloc[i + fb] / c.iloc[i] - 1.0) if c.iloc[i] > 0 else 0.0

        if expansion > exp_conf:
            if abs(oi_spike) < 0.003 and abs(ret_fwd) < 0.002:
                out.iloc[i] = "FAKE_BREAKOUT"
            else:
                out.iloc[i] = "BREAKOUT_CONFIRMED"
        elif expansion > exp_form:
            out.iloc[i] = "BREAKOUT_FORMING"
        elif expansion < exp_exhaust and i + fb < n:
            out.iloc[i] = "BREAKOUT_EXHAUSTION"
        else:
            out.iloc[i] = "NO_BREAKOUT"

    counts = {cls: int((out == cls).sum()) for cls in BREAKOUT_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
        "threshold_mode": "train_quantile",
        "train_end_idx": train_end_idx,
    }


def build_liquidity_condition_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
    train_end_idx: Optional[int] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Liquidity proxy labels from OI, funding, wicks (train-slice quantile gates)."""
    _ = forward_bars
    n = len(df_feat)
    oi_z = pd.to_numeric(df_feat.get("oi_zscore", 0), errors="coerce")
    fund_z = pd.to_numeric(df_feat.get("funding_zscore", 0), errors="coerce")
    wick = pd.to_numeric(df_feat.get("wick_asym", 0), errors="coerce")
    oi_acc = pd.to_numeric(df_feat.get("oi_acceleration", 0), errors="coerce")
    tm = pd.to_numeric(df_feat.get("trend_mom", 0), errors="coerce")
    c = close.astype(float)
    ret3 = c.pct_change(3, fill_method=None)
    pressure = oi_z * fund_z

    stop_score = wick.abs() * oi_acc.abs() * ret3.abs()
    sweep_score = oi_z.clip(lower=0) * ret3.abs() * oi_acc.clip(lower=0)
    long_score = oi_z.clip(lower=0) * pressure.clip(lower=0) * tm.clip(lower=0)
    short_score = oi_z.clip(lower=0) * (-pressure).clip(lower=0) * (-tm).clip(lower=0)

    stop_thr = _train_quantile(stop_score, train_end_idx, 0.95, fallback=0.0)
    sweep_thr = _train_quantile(sweep_score, train_end_idx, 0.95, fallback=0.0)
    long_thr = _train_quantile(long_score, train_end_idx, 0.93, fallback=0.0)
    short_thr = _train_quantile(short_score, train_end_idx, 0.93, fallback=0.0)

    out: List[str] = []
    for i in range(n):
        if float(stop_score.iloc[i]) >= stop_thr and stop_thr > 0:
            out.append("STOP_HUNT_ENV")
        elif float(sweep_score.iloc[i]) >= sweep_thr and sweep_thr > 0:
            out.append("LIQ_SWEEP_ACTIVE")
        elif float(long_score.iloc[i]) >= long_thr and long_thr > 0:
            out.append("LONG_LIQ_RISK")
        elif float(short_score.iloc[i]) >= short_thr and short_thr > 0:
            out.append("SHORT_LIQ_RISK")
        else:
            out.append("BALANCED")

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {cls: int((series == cls).sum()) for cls in LIQUIDITY_CLASSES}
    return series, {
        "labeled_fraction": 1.0,
        "class_counts": counts,
        "threshold_mode": "train_quantile",
        "train_end_idx": train_end_idx,
    }


def build_momentum_quality_labels(
    df_feat: pd.DataFrame,
    *,
    forward_bars: int,
    train_end_idx: Optional[int] = None,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Momentum quality from RSI structure and price/OI divergence at t+N."""
    fb = int(forward_bars)
    n = len(df_feat)
    rsi = pd.to_numeric(df_feat.get("rsi_14", 50), errors="coerce")
    rsi_mom = pd.to_numeric(df_feat.get("rsi_mom", 0), errors="coerce")
    tm = pd.to_numeric(df_feat.get("trend_mom", 0), errors="coerce")
    oi_div = pd.to_numeric(df_feat.get("oi_price_divergence", 0), errors="coerce")
    div_thr = _train_quantile(oi_div.abs(), train_end_idx, 0.90, fallback=0.025)
    tm_healthy = _train_quantile(tm.abs(), train_end_idx, 0.65, fallback=0.00035)
    rm_healthy = _train_quantile(rsi_mom.abs(), train_end_idx, 0.65, fallback=0.25)
    out: List[Optional[str]] = [None] * n

    for i in range(n - fb):
        j = i + fb
        r = float(rsi.iloc[j]) if pd.notna(rsi.iloc[j]) else 50.0
        rm = float(rsi_mom.iloc[j]) if pd.notna(rsi_mom.iloc[j]) else 0.0
        t = float(tm.iloc[j]) if pd.notna(tm.iloc[j]) else 0.0
        d = float(oi_div.iloc[j]) if pd.notna(oi_div.iloc[j]) else 0.0

        if abs(t) > tm_healthy and abs(rm) > rm_healthy and 35 <= r <= 65 and abs(d) < div_thr:
            out[i] = "HEALTHY"
        elif (r > 72 or r < 28) and abs(rm) < 0.8:
            out[i] = "EXHAUSTED"
        elif (r > 65 and t < -tm_healthy) or (r < 35 and t > tm_healthy) or (
            abs(d) > div_thr and abs(t) > tm_healthy * 0.5
        ):
            out[i] = "DIVERGING"
        elif abs(rm) < rm_healthy * 0.5:
            out[i] = "WEAK"
        elif t * (r - 50) > 0:
            out[i] = "HEALTHY"
        else:
            out[i] = "WEAK"

    series = pd.Series(out, index=df_feat.index, dtype=object)
    counts = {cls: int((series == cls).sum()) for cls in MOMENTUM_CLASSES}
    return series, {
        "forward_bars": fb,
        "labeled_fraction": float(series.notna().mean()),
        "class_counts": counts,
        "threshold_mode": "train_quantile",
        "train_end_idx": train_end_idx,
    }


def build_compression_expansion_labels(
    df_feat: pd.DataFrame,
    close: pd.Series,
    *,
    forward_bars: int,
) -> Tuple[pd.Series, Dict[str, Any]]:
    """Compression/expansion cycle from BB width percentile and future ATR."""
    high, low, c = _resolve_ohlcv(df_feat, close)
    bb_w = pd.to_numeric(df_feat.get("bb_width", np.nan), errors="coerce")
    fb = int(forward_bars)
    n = len(c)
    bb_pct = bb_w.rolling(200, min_periods=30).apply(
        lambda x: float((x.iloc[-1] <= x).mean()) if len(x) else np.nan,
        raw=False,
    )
    atr = _atr_series(high, low, c)
    out = pd.Series(np.nan, index=c.index, dtype=object)

    for i in range(n - fb):
        pct = float(bb_pct.iloc[i]) if pd.notna(bb_pct.iloc[i]) else np.nan
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
        elif exp_ratio > 1.05 and np.isfinite(pct) and pct < 0.40:
            out.iloc[i] = "PRE_EXPANSION"
        elif exp_ratio < 0.95 and np.isfinite(pct) and pct > 0.55:
            out.iloc[i] = "POST_EXPANSION"
        elif np.isfinite(pct) and pct < 0.25:
            out.iloc[i] = "COMPRESSION"
        else:
            out.iloc[i] = "PRE_EXPANSION"

    counts = {cls: int((out == cls).sum()) for cls in COMPRESSION_CLASSES}
    return out, {
        "forward_bars": fb,
        "labeled_fraction": float(out.notna().mean()),
        "class_counts": counts,
    }


_LABEL_BUILDERS = {
    "vol_regime": lambda df, close, fb, train_end_idx=None: build_vol_regime_labels(
        df, close, forward_bars=fb, train_end_idx=train_end_idx
    ),
    "breakout_state": lambda df, close, fb, train_end_idx=None: build_breakout_state_labels(
        df, close, forward_bars=fb, train_end_idx=train_end_idx
    ),
    "liquidity_condition": lambda df, close, fb, train_end_idx=None: build_liquidity_condition_labels(
        df, close, forward_bars=fb, train_end_idx=train_end_idx
    ),
    "momentum_quality": lambda df, close, fb, train_end_idx=None: build_momentum_quality_labels(
        df, forward_bars=fb, train_end_idx=train_end_idx
    ),
    "compression_expansion": lambda df, close, fb, train_end_idx=None: build_compression_expansion_labels(
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
    return _LABEL_BUILDERS[key](df_feat, close, fb, train_end_idx)


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
