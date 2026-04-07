"""
v15 pipeline feature row computation (train-serve aligned naming).

Uses the same OHLCV math as UnifiedFeatureEngine where possible; adds v15-specific
names and scales (e.g. atr_pct as ratio, bb_width as fractional width).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from feature_store.unified_feature_engine import UnifiedFeatureEngine


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx_di(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    tr = np.maximum(
        h - l,
        np.maximum((h - c.shift(1)).abs(), (l.shift(1) - l).abs()),
    )
    atr = pd.Series(tr, index=df.index).rolling(period, min_periods=1).mean()
    plus_dm = (h - h.shift(1)).where((h - h.shift(1)) > (l.shift(1) - l), 0).clip(lower=0)
    minus_dm = (l.shift(1) - l).where((l.shift(1) - l) > (h - h.shift(1)), 0).clip(lower=0)
    plus_di = 100 * plus_dm.rolling(period, min_periods=1).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(period, min_periods=1).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(period, min_periods=1).mean()
    return adx, plus_di, minus_di


def _macd_hist(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    line = ema12 - ema26
    sig = _ema(line, 9)
    hist = line - sig
    return line, sig, hist


def _dataframe_from_candles(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for c in candles:
        rows.append(
            {
                "open": float(c.get("open", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "close": float(c.get("close", 0)),
                "volume": float(c.get("volume", 0)),
            }
        )
    return pd.DataFrame(rows)


def compute_v15_row_from_ohlcv(
    df: pd.DataFrame,
    *,
    include_patterns: bool = True,
) -> Dict[str, float]:
    """Compute the 15m-model feature dict from OHLCV dataframe (last bar)."""
    if df is None or len(df) < 5:
        return {}

    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0.0, index=df.index)

    eng = UnifiedFeatureEngine()
    batch = eng.compute_batch(
        pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}),
        resolution_minutes=15,
        fill_invalid=True,
        include_pattern_features=include_patterns,
        include_mtf_context=False,
    )
    last_i = -1
    sma20 = c.rolling(20, min_periods=1).mean()
    std20 = c.rolling(20, min_periods=1).std()
    bb_u = sma20 + 2 * std20
    bb_l = sma20 - 2 * std20
    bb_width = (bb_u - bb_l) / c.replace(0, np.nan)

    tr = np.maximum(
        h - l,
        np.maximum((h - c.shift(1)).abs(), (l.shift(1) - l).abs()),
    )
    atr_14 = pd.Series(tr, index=df.index).rolling(14, min_periods=1).mean()

    adx, pdi, mdi = _adx_di(pd.DataFrame({"high": h, "low": l, "close": c}), 14)
    macd_line, _, macd_hist = _macd_hist(c)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    ema50 = _ema(c, 50)
    ema200 = _ema(c, 200)

    ret = c.pct_change()
    vol = ret.rolling(20, min_periods=50).std()
    vol10 = ret.rolling(10, min_periods=1).std()
    roc20 = (c - c.shift(20)) / c.shift(20).replace(0, np.nan)

    sr_high = float(batch["sr_at_resistance"].iloc[last_i]) if "sr_at_resistance" in batch.columns else 0.0
    sr_low = float(batch["sr_at_support"].iloc[last_i]) if "sr_at_support" in batch.columns else 0.0
    bo_dn = 0.0
    if "bo_breakout_down" in batch.columns:
        bo_dn = float(batch["bo_breakout_down"].iloc[last_i])
    if "tl_breakout_down" in batch.columns:
        bo_dn = max(bo_dn, float(batch["tl_breakout_down"].iloc[last_i]))

    out: Dict[str, float] = {
        "adx_14": float(adx.iloc[last_i]),
        "atr_14": float(atr_14.iloc[last_i]),
        "bb_width": float(bb_width.iloc[last_i]) if np.isfinite(bb_width.iloc[last_i]) else 0.0,
        "di_diff": float(pdi.iloc[last_i] - mdi.iloc[last_i]),
        "ema_9": float(ema9.iloc[last_i]),
        "ema_cross_21_50": float(np.sign(ema21.iloc[last_i] - ema50.iloc[last_i])),
        "ema_cross_50_200": float(np.sign(ema50.iloc[last_i] - ema200.iloc[last_i])),
        "hl_range": float(h.iloc[last_i] - l.iloc[last_i]),
        "macd": float(macd_line.iloc[last_i]),
        "macd_hist": float(macd_hist.iloc[last_i]),
        "minus_di": float(mdi.iloc[last_i]),
        "plus_di": float(pdi.iloc[last_i]),
        "price_vs_ema200": float(c.iloc[last_i] / ema200.iloc[last_i] - 1.0)
        if ema200.iloc[last_i] and np.isfinite(ema200.iloc[last_i])
        else 0.0,
        "roc_20": float(roc20.iloc[last_i]) if np.isfinite(roc20.iloc[last_i]) else 0.0,
        "rsi_14": float(_rsi(c, 14).iloc[last_i]),
        "rsi_7": float(_rsi(c, 7).iloc[last_i]),
        "sr_near_high": 1.0 if sr_high > 0.5 else 0.0,
        "sr_near_low": 1.0 if sr_low > 0.5 else 0.0,
        "volatility": float(vol.iloc[last_i]) if np.isfinite(vol.iloc[last_i]) else 0.0,
        "volatility_10": float(vol10.iloc[last_i]) if np.isfinite(vol10.iloc[last_i]) else 0.0,
    }
    return out


def compute_v15_5m_base_row(
    df: pd.DataFrame,
    *,
    include_patterns: bool = True,
) -> Dict[str, float]:
    """5m primary-bar features (excludes *_15m HTF columns)."""
    if df is None or len(df) < 5:
        return {}
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0.0, index=df.index)

    eng = UnifiedFeatureEngine()
    batch = eng.compute_batch(
        pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}),
        resolution_minutes=5,
        fill_invalid=True,
        include_pattern_features=include_patterns,
        include_mtf_context=False,
    )
    last_i = -1
    adx, pdi, mdi = _adx_di(pd.DataFrame({"high": h, "low": l, "close": c}), 14)
    tr = np.maximum(
        h - l,
        np.maximum((h - c.shift(1)).abs(), (l.shift(1) - l).abs()),
    )
    atr_14 = pd.Series(tr, index=df.index).rolling(14, min_periods=1).mean()
    macd_line, _, _ = _macd_hist(c)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    ema50 = _ema(c, 50)
    ema200 = _ema(c, 200)
    ret = c.pct_change()
    vol = ret.rolling(20, min_periods=50).std()
    vol10 = ret.rolling(10, min_periods=1).std()
    atr_pct = atr_14 / c.replace(0, np.nan)
    sr_low = float(batch["sr_at_support"].iloc[last_i]) if "sr_at_support" in batch.columns else 0.0
    bo_dn = 0.0
    if "bo_breakout_down" in batch.columns:
        bo_dn = float(batch["bo_breakout_down"].iloc[last_i])
    if "tl_breakout_down" in batch.columns:
        bo_dn = max(bo_dn, float(batch["tl_breakout_down"].iloc[last_i]))

    out: Dict[str, float] = {
        "adx_14": float(adx.iloc[last_i]),
        "atr_14": float(atr_14.iloc[last_i]),
        "atr_pct": float(atr_pct.iloc[last_i]) if np.isfinite(atr_pct.iloc[last_i]) else 0.0,
        "ema_9": float(ema9.iloc[last_i]),
        "ema_cross_21_50": float(np.sign(ema21.iloc[last_i] - ema50.iloc[last_i])),
        "ema_cross_50_200": float(np.sign(ema50.iloc[last_i] - ema200.iloc[last_i])),
        "ema_cross_9_21": float(np.sign(ema9.iloc[last_i] - ema21.iloc[last_i])),
        "hl_range": float(h.iloc[last_i] - l.iloc[last_i]),
        "macd": float(macd_line.iloc[last_i]),
        "price_vs_ema200": float(c.iloc[last_i] / ema200.iloc[last_i] - 1.0)
        if ema200.iloc[last_i] and np.isfinite(ema200.iloc[last_i])
        else 0.0,
        "rsi_14": float(_rsi(c, 14).iloc[last_i]),
        "sr_breakout_dn": 1.0 if bo_dn > 0.5 else 0.0,
        "sr_near_low": 1.0 if sr_low > 0.5 else 0.0,
        "volatility": float(vol.iloc[last_i]) if np.isfinite(vol.iloc[last_i]) else 0.0,
        "volatility_10": float(vol10.iloc[last_i]) if np.isfinite(vol10.iloc[last_i]) else 0.0,
    }
    return out


def htf_suffix_map(row_15m: Dict[str, float]) -> Dict[str, float]:
    """Map 15m row keys to 5m HTF feature names."""
    adx = row_15m.get("adx_14", 0.0)
    di_diff = row_15m.get("di_diff", 0.0)
    ema_cross_50_200 = row_15m.get("ema_cross_50_200", 0.0)
    macd_hist = row_15m.get("macd_hist", 0.0)
    rsi_14 = row_15m.get("rsi_14", 50.0)
    return {
        "adx_14_15m": float(adx),
        "di_diff_15m": float(di_diff),
        "ema_cross_50_200_15m": float(ema_cross_50_200),
        "macd_hist_15m": float(macd_hist),
        "rsi_14_15m": float(rsi_14),
    }


def build_v15_feature_dict_for_tf(
    candles: List[Dict[str, Any]],
    timeframe: str,
    candles_15m: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Full v15 feature dict for one timeframe (5m merges HTF from candles_15m)."""
    df = _dataframe_from_candles(candles)
    tf = (timeframe or "15m").strip().lower()
    if tf == "5m":
        base = compute_v15_5m_base_row(df, include_patterns=True)
        if candles_15m and len(candles_15m) >= 14:
            df15 = _dataframe_from_candles(candles_15m)
            row15 = compute_v15_row_from_ohlcv(df15, include_patterns=False)
            base.update(htf_suffix_map(row15))
        return base
    return compute_v15_row_from_ohlcv(df, include_patterns=True)


def ordered_feature_vector(
    feature_map: Dict[str, float],
    names: List[str],
    train_median: Optional[Dict[str, float]] = None,
) -> List[float]:
    """Return values aligned to ``names``; impute from train_median when missing."""
    med = train_median or {}
    out: List[float] = []
    for n in names:
        v = feature_map.get(n)
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            v = float(med.get(n, 0.0))
        out.append(float(v))
    return out
