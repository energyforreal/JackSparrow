"""Vectorized JackSparrow v43 feature matrix for :func:`v43_pickle_shims.set_v43_build_feature_matrix`.

Mirrors :func:`build_v43_last_row` / :mod:`feature_store.jacksparrow_v43_mcp_row` on the full 5m grid
(resampled 15m/1h from primary). Separate ``df_15m`` / ``df_1h`` args are accepted for API parity but not
used so behavior matches ``jacksparrow_v43_mcp_row.build_v43_last_row``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_basis_features import _basis_features_on_primary
from feature_store.jacksparrow_v43_microstructure_features import _microstructure_features_on_primary
from feature_store.jacksparrow_v43_oi_features import _oi_features_on_primary
from feature_store.jacksparrow_v43_mcp_row import (
    EPS,
    V43_MCP_FEATURE_NAMES,
    _adx_df,
    _align_h1_to_primary,
    _align_hf_to_primary,
    _atr,
    _efficiency_ratio,
    _ema,
    _empty_h1_series,
    _empty_hf_series,
    _hurst_fast,
    _ohlc,
    _resample_ohlc,
    _rsi,
    _session_vwap,
    primary_minutes_from_interval,
)

REGIME_MIN_BARS = 6


def _smooth_regime_labels(regime_series: pd.Series, min_bars: int = REGIME_MIN_BARS) -> pd.Series:
    s = regime_series.astype(str).copy()
    out = s.copy()
    i = 0
    n = len(s)
    while i < n:
        j = i + 1
        while j < n and s.iloc[j] == s.iloc[i]:
            j += 1
        if j - i < min_bars:
            out.iloc[i:j] = "neutral"
        i = j
    return out


def _funding_rate_on_primary(d: pd.DataFrame, df_funding: Optional[pd.DataFrame]) -> pd.Series:
    n = len(d)
    z = pd.Series(0.0, index=range(n))
    if df_funding is None or df_funding.empty or "timestamp" not in df_funding.columns:
        return z
    try:
        prim_ts = pd.to_datetime(d["timestamp"], utc=True)
        ff = df_funding.copy()
        ff["_fts"] = pd.to_datetime(ff["timestamp"], utc=True)
        fr_col = "funding_rate" if "funding_rate" in ff.columns else "close"
        aux = pd.DataFrame({"_fts": ff["_fts"], "fr": ff[fr_col].astype(float)}).sort_values("_fts")
        left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
        merged = pd.merge_asof(left, aux, left_on="ts", right_on="_fts", direction="backward")
        merged = merged.sort_values("_ord")
        return merged["fr"].fillna(0.0).reset_index(drop=True)
    except Exception:
        return z


def build_v43_feature_matrix(
    df_5m: pd.DataFrame,
    df_15m: Optional[pd.DataFrame] = None,
    df_1h: Optional[pd.DataFrame] = None,
    df_funding: Optional[pd.DataFrame] = None,
    df_oi: Optional[pd.DataFrame] = None,
    df_mark: Optional[pd.DataFrame] = None,
    *,
    for_training: bool = False,
    primary_interval: str = "5m",
) -> pd.DataFrame:
    """Return DataFrame with v43 features (+ ``regime_label``) aligned to ``df_5m`` rows."""
    _ = df_15m, df_1h  # API parity; MCP row resamples HTF from 5m only.

    if df_5m is None or df_5m.empty or len(df_5m) < 40:
        return pd.DataFrame()

    d = _ohlc(df_5m)
    c = d["close"]
    h = d["high"]
    l = d["low"]
    o = d["open"]
    v = d["volume"]

    ema21 = _ema(c, 21)
    ema50 = _ema(c, 50)
    ema100 = _ema(c, 100)
    atr14 = _atr(d, 14)

    ret_1 = c.pct_change(1)
    ret_6 = c.pct_change(6)
    ret_24 = c.pct_change(24)
    mom_accel = c.pct_change(3) - c.pct_change(3).shift(3)

    sma20 = c.rolling(20, min_periods=1).mean()
    std20 = c.rolling(20, min_periods=1).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_mid = sma20
    bb_width = (bb_upper - bb_lower) / (bb_mid + EPS)
    bb_pos = (c - bb_lower) / (bb_upper - bb_lower + EPS)

    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line = ema12 - ema26
    macd_signal = _ema(macd_line, 9)
    macd_hist = macd_line - macd_signal
    macd_hist_n = macd_hist / (atr14 + EPS)

    rsi14 = _rsi(c, 14)
    rsi_mom = rsi14 - rsi14.shift(5)

    adx14, plus_di, minus_di = _adx_df(d, 14)
    di_spread = plus_di - minus_di

    vol_20 = ret_1.rolling(20, min_periods=1).std()
    vol_regime = vol_20 / (vol_20.rolling(50, min_periods=1).median() + EPS)

    kauf_er_20 = _efficiency_ratio(c, 20)
    hurst_60 = _hurst_fast(c, 60)

    _obv_raw = (np.sign(c.diff()) * v).fillna(0).cumsum()
    _obv_roll_std = _obv_raw.rolling(100, min_periods=20).std().clip(lower=EPS)
    _obv_roll_mu = _obv_raw.rolling(100, min_periods=20).mean()
    obv_ret = ((_obv_raw - _obv_roll_mu) / _obv_roll_std).clip(-4, 4)

    clv = ((c - l) - (h - c)) / (h - l + EPS)
    cmf_20 = (clv * v).rolling(20, min_periods=1).sum() / (v.rolling(20, min_periods=1).sum() + EPS)

    if "timestamp" in d.columns and not d["timestamp"].isna().all():
        session_vwap = _session_vwap(d)
        session_vwap_dev = (c - session_vwap) / (session_vwap + EPS)
        tsv = pd.to_datetime(d["timestamp"], utc=True)
        hour = tsv.dt.hour.astype(float) + tsv.dt.minute.astype(float) / 60.0
        hour_sin = np.sin(2 * np.pi * hour / 24)
        hour_cos = np.cos(2 * np.pi * hour / 24)
    else:
        session_vwap_dev = pd.Series(0.0, index=d.index)
        hour_sin = pd.Series(0.0, index=d.index)
        hour_cos = pd.Series(0.0, index=d.index)

    body = (c - o).abs() / (atr14 + EPS)
    body_dir = (c - o) / (atr14 + EPS)
    wick_up = (h - pd.concat([o, c], axis=1).max(axis=1)) / (atr14 + EPS)
    wick_dn = (pd.concat([o, c], axis=1).min(axis=1) - l) / (atr14 + EPS)
    wick_asym = wick_up - wick_dn

    _high200 = h.rolling(200, min_periods=50).max().shift(1)
    _low200 = l.rolling(200, min_periods=50).min().shift(1)
    _dist_high200 = (_high200 - c) / (c + EPS)
    _dist_low200 = (c - _low200) / (c + EPS)
    sr_compression = _dist_high200 / (_dist_high200 + _dist_low200 + EPS)

    adx_norm = (adx14 / 25.0).clip(0, 2)
    trend_mom = mom_accel * adx_norm
    trend_conf = (hurst_60 - 0.5) * kauf_er_20

    fund_rate = _funding_rate_on_primary(d, df_funding)
    wz = 48
    fz_mean = fund_rate.rolling(wz, min_periods=5).mean()
    fz_std = fund_rate.rolling(wz, min_periods=5).std().replace(0, EPS)
    funding_zscore = (fund_rate - fz_mean) / fz_std
    funding_zscore = funding_zscore.fillna(0.0)
    funding_mom = funding_zscore * ret_6

    base_m = primary_minutes_from_interval(primary_interval)
    hf = _empty_hf_series(len(d))
    h1 = _empty_h1_series(len(d))
    try:
        d15 = _resample_ohlc(d, 15) if base_m <= 15 else None
        if d15 is not None and len(d15) >= 30:
            c15 = d15["close"]
            ema21_15 = _ema(c15, 21)
            ema50_15 = _ema(c15, 50)
            ema200_15 = _ema(c15, 200)
            h_ret_1 = c15.pct_change(1)
            h_trend = (ema21_15 - ema50_15) / (ema50_15 + EPS)
            h_trend_200 = (ema50_15 - ema200_15) / (ema200_15 + EPS)
            h_rsi_14 = _rsi(c15, 14)
            hf = _align_hf_to_primary(d, d15, h_ret_1, h_trend, h_trend_200, h_rsi_14)
    except Exception:
        pass

    try:
        d60 = _resample_ohlc(d, 60) if base_m <= 60 else None
        if d60 is not None and len(d60) >= 30:
            c60 = d60["close"]
            h60 = d60["high"]
            l60 = d60["low"]
            df60 = pd.DataFrame(
                {
                    "open": d60["open"],
                    "high": h60,
                    "low": l60,
                    "close": c60,
                    "volume": d60["volume"],
                }
            )
            h1_ema_21 = _ema(c60, 21)
            h1_ema_50 = _ema(c60, 50)
            h1_trend = (h1_ema_21 - h1_ema_50) / (h1_ema_50 + EPS)
            h1_rsi_14 = _rsi(c60, 14)
            adx1, _, _ = _adx_df(df60, 14)
            h1_adx = adx1
            vol_ret = c60.pct_change(1)
            roll20 = vol_ret.rolling(20, min_periods=5).std()
            roll50 = vol_ret.rolling(50, min_periods=10).std()
            h1_vol_regime = roll20 / (roll50.rolling(100, min_periods=20).median() + EPS)
            h1 = _align_h1_to_primary(d, d60, h1_trend, h1_rsi_14, h1_adx, h1_vol_regime)
    except Exception:
        pass

    bull_bar = (c > o).astype(float)
    atr_pct = atr14 / (c + EPS)

    out = pd.DataFrame(
        {
            "ret_1": ret_1,
            "ret_6": ret_6,
            "ret_24": ret_24,
            "mom_accel": mom_accel,
            "ema_21_50_cross": (ema21 - ema50) / (ema50 + EPS),
            "price_ema21": (c - ema21) / (ema21 + EPS),
            "price_ema100": (c - ema100) / (ema100 + EPS),
            "rsi_14": rsi14,
            "rsi_mom": rsi_mom,
            "macd_hist_n": macd_hist_n,
            "bb_width": bb_width,
            "bb_pos": bb_pos,
            "atr_pct": atr_pct,
            "vol_regime": vol_regime,
            "adx_14": adx14,
            "di_spread": di_spread,
            "kauf_er_20": kauf_er_20,
            "obv_ret": obv_ret,
            "cmf_20": cmf_20,
            "session_vwap_dev": session_vwap_dev,
            "body": body,
            "body_dir": body_dir,
            "wick_asym": wick_asym,
            "sr_compression": sr_compression,
            "hour_sin": hour_sin,
            "hour_cos": hour_cos,
            "hurst_60": hurst_60,
            "trend_mom": trend_mom,
            "trend_conf": trend_conf,
            "funding_zscore": funding_zscore,
            "funding_mom": funding_mom,
            "h_ret_1": hf["h_ret_1"],
            "h_trend": hf["h_trend"],
            "h_trend_200": hf["h_trend_200"],
            "h_rsi_14": hf["h_rsi_14"],
            "h1_trend": h1["h1_trend"],
            "h1_rsi_14": h1["h1_rsi_14"],
            "h1_adx": h1["h1_adx"],
            "h1_vol_regime": h1["h1_vol_regime"],
            "bull_bar": bull_bar,
        }
    )
    out = out.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    crisis_thr = atr_pct.rolling(200, min_periods=20).quantile(0.95)
    _crisis = (atr_pct >= crisis_thr) | (vol_regime > 3.0)
    _trending = (~_crisis) & (adx14 > 22) & (hurst_60 > 0.55)
    _ranging = (~_crisis) & (~_trending) & (adx14 < 18) & (hurst_60 < 0.47)
    regime_raw = np.select(
        [_crisis.values, _trending.values, _ranging.values],
        ["crisis", "trending", "ranging"],
        default="neutral",
    )
    out["regime_label"] = _smooth_regime_labels(pd.Series(regime_raw)).values

    if "timestamp" in d.columns:
        out.insert(0, "timestamp", d["timestamp"].values)

    prim = d.reset_index(drop=True)
    oi_feats = _oi_features_on_primary(prim, df_oi)
    for col in ("oi_zscore", "oi_change_6", "oi_price_divergence", "oi_acceleration"):
        out[col] = oi_feats[col].values

    basis_feats = _basis_features_on_primary(prim, df_mark, df_oi)
    for col in ("basis", "basis_zscore", "basis_momentum"):
        out[col] = basis_feats[col].values

    micro_feats = _microstructure_features_on_primary(
        prim,
        df_oi,
        out["funding_zscore"],
        out["oi_zscore"],
    )
    for col in (
        "bid_ask_imbalance",
        "spread_bps",
        "funding_x_oi",
        "funding_predicted_zscore",
    ):
        out[col] = micro_feats[col].values

    if for_training:
        _ = for_training  # reserved for notebook parity

    # Restrict to known v43 names + timestamp/regime (model may expect only feature cols in transform)
    extra = [c for c in ("timestamp", "regime_label") if c in out.columns]
    feat_keep = [c for c in out.columns if c in V43_MCP_FEATURE_NAMES or c in extra]
    return out[feat_keep].copy()
