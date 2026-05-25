"""
JackSparrow v43 feature row for MCP / feature-server paths.

Trading inference uses pickled ``feature_engineer.transform()``; this module
reimplements the exported v43 feature *names* for per-feature HTTP/MCP requests
when only OHLCV candles are available (5m primary + resampled HTF).

Formulas match :mod:`feature_store.jacksparrow_v43_build_matrix` and
``metadata_v43.json`` / :data:`feature_store.jacksparrow_v43_contract.V43_CANONICAL_FEATURES`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_EXPECTED_FEATURE_COUNT,
    V43_FORWARD_TARGET_BARS,
)

EPS = 1e-9

V43_MCP_FEATURE_NAMES: frozenset[str] = frozenset(V43_CANONICAL_FEATURES)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _adx_df(df: pd.DataFrame, period: int = 14):
    """Return (adx, plus_di, minus_di) — matches v39 notebook structure."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_s = pd.Series(tr.values, index=tr.index).ewm(span=period, adjust=False).mean()
    atr_s.index = df.index
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(span=period, adjust=False).mean() / (
        atr_s + EPS
    )
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / (
        atr_s + EPS
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + EPS)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


def _hurst_fast(close: pd.Series, window: int = 60) -> pd.Series:
    log_ret = np.log(close / close.shift(1))
    var1 = log_ret.rolling(window, min_periods=max(2, window // 2)).var()
    var4 = log_ret.rolling(4, min_periods=2).mean().rolling(window, min_periods=max(2, window // 2)).var()
    h = 0.5 + 0.5 * np.log((var4 + 1e-12) / (var1 + 1e-12)) / np.log(4)
    return h.clip(0.0, 1.0).fillna(0.5)


def _efficiency_ratio(close: pd.Series, period: int = 20) -> pd.Series:
    direction = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period, min_periods=1).sum()
    return (direction / (volatility + EPS)).clip(0, 1)


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    d = df.copy()
    ts = pd.to_datetime(d["timestamp"], utc=True)
    day = ts.dt.date
    typical = (d["high"].astype(float) + d["low"].astype(float) + d["close"].astype(float)) / 3
    tp_vol = typical * d["volume"].astype(float)
    cum_tpv = tp_vol.groupby(day).cumsum()
    cum_vol = d["volume"].astype(float).groupby(day).cumsum()
    return cum_tpv / (cum_vol + EPS)


def _ohlc(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            "volume": df["volume"].astype(float),
        }
    )
    if "timestamp" in df.columns:
        raw = df["timestamp"]
        out["timestamp"] = pd.to_datetime(raw, utc=True, errors="coerce")
        if out["timestamp"].isna().all():
            out["timestamp"] = pd.to_datetime(raw, unit="s", utc=True, errors="coerce")
        out = out.sort_values("timestamp").reset_index(drop=True)
    else:
        out = out.reset_index(drop=True)
    return out


def _resample_ohlc(d: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample primary OHLCV to ``minutes`` bars (requires ``timestamp``)."""
    if "timestamp" not in d.columns or d["timestamp"].isna().all():
        raise ValueError("v43 HTF resample requires candle timestamps")

    work = d.set_index("timestamp").sort_index()
    agg = (
        work.resample(f"{minutes}min", label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(how="any")
    )
    return agg.reset_index()


def primary_minutes_from_interval(interval: str) -> int:
    s = (interval or "5m").strip().lower()
    if s.endswith("m"):
        return max(1, int(s[:-1]))
    if s.endswith("h"):
        return max(1, int(s[:-1]) * 60)
    if s.endswith("d"):
        return max(1, int(s[:-1]) * 1440)
    return 5


def build_v43_last_row(
    candles: List[Dict[str, Any]],
    *,
    primary_interval: str = "5m",
    funding_zscore: Optional[float] = None,
) -> Dict[str, float]:
    """Return scalar feature dict for the last row (training parity: closed bar logic)."""

    df0 = pd.DataFrame(candles or [])
    if df0.empty or len(df0) < 40:
        return {name: 0.0 for name in V43_MCP_FEATURE_NAMES}

    d = _ohlc(df0)
    fz = float(funding_zscore) if funding_zscore is not None else 0.0

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
        ts_last = pd.to_datetime(d["timestamp"].iloc[-1], utc=True)
        hour = float(ts_last.hour + ts_last.minute / 60.0)
        hour_sin = float(np.sin(2 * np.pi * hour / 24))
        hour_cos = float(np.cos(2 * np.pi * hour / 24))
    else:
        session_vwap_dev = pd.Series(0.0, index=d.index)
        hour_sin = 0.0
        hour_cos = 0.0

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

    funding_mom = pd.Series(fz, index=d.index) * ret_6
    funding_rate_roc = pd.Series(0.0, index=d.index)

    base_m = primary_minutes_from_interval(primary_interval)
    # HTF mirrors (notebook: true 15m / 1h bars)
    hf = _empty_hf_series(len(d))
    h1 = _empty_h1_series(len(d))
    try:
        d15 = _resample_ohlc(d, 15) if base_m <= 15 else None
        if d15 is not None and len(d15) >= 30:
            c15 = d15["close"]
            h15 = d15["high"]
            l15 = d15["low"]
            h_ema_21 = _ema(c15, 21)
            h_ema_50 = _ema(c15, 50)
            h_ema_200 = _ema(c15, 200)
            h_ret_1 = c15.pct_change(1)
            h_trend = (h_ema_21 - h_ema_50) / (h_ema_50 + EPS)
            h_trend_200 = (h_ema_50 - h_ema_200) / (h_ema_200 + EPS)
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
                {"open": d60["open"], "high": h60, "low": l60, "close": c60, "volume": d60["volume"]}
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

    def _last(series: pd.Series) -> float:
        try:
            return float(series.iloc[-1])
        except Exception:
            return 0.0

    row = {
        "ret_1": _last(ret_1),
        "ret_6": _last(ret_6),
        "ret_24": _last(ret_24),
        "mom_accel": _last(mom_accel),
        "ema_21_50_cross": _last((ema21 - ema50) / (ema50 + EPS)),
        "price_ema21": _last((c - ema21) / (ema21 + EPS)),
        "price_ema100": _last((c - ema100) / (ema100 + EPS)),
        "rsi_14": _last(rsi14),
        "rsi_mom": _last(rsi_mom),
        "macd_hist_n": _last(macd_hist_n),
        "bb_width": _last(bb_width),
        "bb_pos": _last(bb_pos),
        "atr_pct": _last(atr14 / (c + EPS)),
        "vol_regime": _last(vol_regime),
        "adx_14": _last(adx14),
        "di_spread": _last(di_spread),
        "kauf_er_20": _last(kauf_er_20),
        "obv_ret": _last(obv_ret),
        "cmf_20": _last(cmf_20),
        "session_vwap_dev": _last(session_vwap_dev),
        "body": _last(body),
        "body_dir": _last(body_dir),
        "wick_asym": _last(wick_asym),
        "sr_compression": _last(sr_compression),
        "hour_sin": hour_sin if "timestamp" in d.columns else 0.0,
        "hour_cos": hour_cos if "timestamp" in d.columns else 0.0,
        "hurst_60": _last(hurst_60),
        "trend_mom": _last(trend_mom),
        "trend_conf": _last(trend_conf),
        "funding_zscore": fz,
        "funding_mom": _last(funding_mom),
        "funding_rate_roc": _last(funding_rate_roc),
        "h_ret_1": _last(hf["h_ret_1"]),
        "h_trend": _last(hf["h_trend"]),
        "h_trend_200": _last(hf["h_trend_200"]),
        "h_rsi_14": _last(hf["h_rsi_14"]),
        "h1_trend": _last(h1["h1_trend"]),
        "h1_rsi_14": _last(h1["h1_rsi_14"]),
        "h1_adx": _last(h1["h1_adx"]),
        "h1_vol_regime": _last(h1["h1_vol_regime"]),
        "bull_bar": _last(bull_bar),
    }

    for k, v in list(row.items()):
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            row[k] = 0.0
    for name in V43_CANONICAL_FEATURES:
        row.setdefault(name, 0.0)
    return row


def _empty_hf_series(n: int) -> Dict[str, pd.Series]:
    idx = pd.RangeIndex(n)
    z = pd.Series(0.0, index=idx)
    return {"h_ret_1": z, "h_trend": z, "h_trend_200": z, "h_rsi_14": z}


def _empty_h1_series(n: int) -> Dict[str, pd.Series]:
    idx = pd.RangeIndex(n)
    z = pd.Series(0.0, index=idx)
    return {"h1_trend": z, "h1_rsi_14": z, "h1_adx": z, "h1_vol_regime": z}


def _align_hf_to_primary(
    d: pd.DataFrame,
    d15: pd.DataFrame,
    h_ret_1: pd.Series,
    h_trend: pd.Series,
    h_trend_200: pd.Series,
    h_rsi_14: pd.Series,
) -> Dict[str, pd.Series]:
    """Forward-fill 15m feature series onto primary index (merge_asof, no lookahead)."""
    prim_ts = pd.to_datetime(d["timestamp"], utc=True)
    hts = pd.to_datetime(d15["timestamp"], utc=True)
    n = len(d)
    out = _empty_hf_series(n)
    aux = pd.DataFrame(
        {
            "hts": hts,
            "h_ret_1": h_ret_1.values,
            "h_trend": h_trend.values,
            "h_trend_200": h_trend_200.values,
            "h_rsi_14": h_rsi_14.values,
        }
    ).sort_values("hts")
    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
    merged = pd.merge_asof(left, aux, left_on="ts", right_on="hts", direction="backward")
    merged = merged.sort_values("_ord")
    for col in ("h_ret_1", "h_trend", "h_trend_200", "h_rsi_14"):
        out[col] = merged[col].fillna(0).reset_index(drop=True)
    return out


def _align_h1_to_primary(
    d: pd.DataFrame,
    d60: pd.DataFrame,
    h1_trend: pd.Series,
    h1_rsi_14: pd.Series,
    h1_adx: pd.Series,
    h1_vol_regime: pd.Series,
) -> Dict[str, pd.Series]:
    prim_ts = pd.to_datetime(d["timestamp"], utc=True)
    hts = pd.to_datetime(d60["timestamp"], utc=True)
    n = len(d)
    out = _empty_h1_series(n)
    aux = pd.DataFrame(
        {
            "hts": hts,
            "h1_trend": h1_trend.values,
            "h1_rsi_14": h1_rsi_14.values,
            "h1_adx": h1_adx.values,
            "h1_vol_regime": h1_vol_regime.values,
        }
    ).sort_values("hts")
    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
    merged = pd.merge_asof(left, aux, left_on="ts", right_on="hts", direction="backward")
    merged = merged.sort_values("_ord")
    for col in ("h1_trend", "h1_rsi_14", "h1_adx", "h1_vol_regime"):
        out[col] = merged[col].fillna(0).reset_index(drop=True)
    return out
