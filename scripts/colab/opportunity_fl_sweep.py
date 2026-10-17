"""Frozen 50-feature 30m research: regime-aligned exclusive policy.

Features stay fixed. Exclusive long/short labels are gated by a causal
UP/DOWN/RANGE regime. Barriers (2/2, 3/3, 4/2) compete on walk-forward.
Live fusion is not written. Injected as ``# CELL: FL_SPECS``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

OHLCV_COLS: Tuple[str, ...] = ("time", "open", "high", "low", "close", "volume")
FROZEN_HORIZON_BARS = 24
FROZEN_RESOLUTION = "30m"
ATR_PERIOD_DEFAULT = 14
TP_ATR_MULT = 4.0
SL_ATR_MULT = 2.0
DIR_BAND_ATR_MULT = 0.5
SCREEN_SEED = 42
N_ESTIMATORS_DEFAULT = 400
_EPS = 1e-12
R_EPS = 1e-12
UNLABELED = -1
MIN_SIGNALS_DEFAULT = 100
MIN_SIGNALS_ALIGNED = 40
OPP_QUANTILES: Tuple[float, ...] = (0.5, 0.8, 0.9, 0.95)
K_VOL_GRID: Tuple[float, ...] = (0.15, 0.25, 0.35)
K_DD_GRID: Tuple[float, ...] = (0.8, 1.0, 1.2)
ADX_REGIME_MIN = 20.0
RANGE_FILL_CAP = 0.05
COST_STRESS_MULTS: Tuple[float, ...] = (1.0, 1.5, 2.0)
MLP_HIDDEN: Tuple[int, int] = (64, 32)
MLP_EPOCHS = 25
MLP_BATCH = 256
MLP_LR = 1e-3

DIR_UP = 0
DIR_NEUTRAL = 1
DIR_DOWN = 2
DIR_NAMES: Tuple[str, ...] = ("UP", "NEUTRAL", "DOWN")

OPP_TP_FIRST = 0
OPP_SL_FIRST = 1
OPP_TIMEOUT = 2
OPP_NAMES: Tuple[str, ...] = ("TP_FIRST", "SL_FIRST", "TIMEOUT")

REGIME_UP = 0
REGIME_DOWN = 1
REGIME_RANGE = 2
REGIME_NAMES: Tuple[str, ...] = ("UP", "DOWN", "RANGE")

EXCL_LONG = 0
EXCL_SHORT = 1
EXCL_SKIP = 2
EXCL_NAMES: Tuple[str, ...] = ("EXCL_LONG", "EXCL_SHORT", "SKIP")

BARRIER_SPECS: Tuple[Dict[str, Any], ...] = (
    {"id": "b2_2", "tp_atr_mult": 2.0, "sl_atr_mult": 2.0},
    {"id": "b3_3", "tp_atr_mult": 3.0, "sl_atr_mult": 3.0},
    {"id": "b4_2", "tp_atr_mult": 4.0, "sl_atr_mult": 2.0},
)

FIXED_FEATURE_COLS: Tuple[str, ...] = (
    "return_1",
    "return_2",
    "return_4",
    "return_8",
    "return_12",
    "return_24",
    "return_48",
    "candle_body",
    "range_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "close_location",
    "ema_distance_8",
    "ema_distance_16",
    "ema_distance_24",
    "ema_distance_48",
    "ema_slope_8",
    "ema_slope_24",
    "rsi_7",
    "rsi_14",
    "rsi_28",
    "macd",
    "macd_signal_distance",
    "adx_14",
    "atr_pct_14",
    "rv_4",
    "rv_12",
    "rv_24",
    "volatility_ratio",
    "bollinger_z_20",
    "range_position_24",
    "range_position_48",
    "breakout_distance_24",
    "log_volume",
    "volume_change",
    "volume_zscore_24",
    "signed_volume_proxy",
    "volume_trend_24",
    "consecutive_candle_direction",
    "higher_high_count_8",
    "lower_low_count_8",
    "trend_efficiency_24",
    "rolling_return_skew_24",
    "rolling_return_kurtosis_24",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "drawdown_48",
    "distance_from_rolling_extreme",
)

TARGET_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "direction_head",
        "kind": "classification",
        "y_col": "y_direction",
        "n_classes": 3,
        "names": DIR_NAMES,
    },
    {
        "id": "return_head",
        "kind": "regression",
        "y_col": "y_return",
    },
    {
        "id": "volatility_head",
        "kind": "regression",
        "y_col": "y_volatility",
    },
    {
        "id": "opportunity_head",
        "kind": "classification",
        "y_col": "y_opportunity",
        "n_classes": 3,
        "names": OPP_NAMES,
    },
    {
        "id": "opportunity_short_head",
        "kind": "classification",
        "y_col": "y_opportunity_short",
        "n_classes": 3,
        "names": OPP_NAMES,
    },
    {
        "id": "excursion_head",
        "kind": "regression_pair",
        "y_cols": ("y_upside", "y_downside"),
    },
    {
        "id": "exclusive_head",
        "kind": "classification",
        "y_col": "y_exclusive",
        "n_classes": 3,
        "names": EXCL_NAMES,
    },
)

POLICY_HEAD_IDS: Tuple[str, ...] = (
    "exclusive_head",
    "volatility_head",
    "excursion_head",
)


def _require_ohlcv(df: pd.DataFrame) -> None:
    missing = [c for c in OHLCV_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")


def _wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _wilder_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=high.index,
    )
    alpha = 1.0 / float(period)
    atr_w = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    atr_safe = atr_w.replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(
        alpha=alpha, min_periods=period, adjust=False
    ).mean() / atr_safe
    minus_di = 100.0 * minus_dm.ewm(
        alpha=alpha, min_periods=period, adjust=False
    ).mean() / atr_safe
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()


def causal_atr(df: pd.DataFrame, period: int = ATR_PERIOD_DEFAULT) -> pd.Series:
    """14-bar simple average of true range. Uses only bars at or before t."""
    close = df["close"].astype(np.float64)
    high = df["high"].astype(np.float64)
    low = df["low"].astype(np.float64)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(int(period), min_periods=int(period)).mean()


def add_fixed_ohlcv_features(
    df: pd.DataFrame, *, atr_period: int = ATR_PERIOD_DEFAULT
) -> pd.DataFrame:
    """Causal 50-feature matrix from OHLCV available at the close of bar t.

    Reads only ``time, open, high, low, close, volume``. Rolling windows use
    ``min_periods=window``. ATR is the simple 14-bar true-range mean used by
    the opportunity barriers.

    Args:
        df: OHLCV frame with a UTC ``time`` column.
        atr_period: True-range averaging window.

    Returns:
        Copy with ``atr`` plus ``FIXED_FEATURE_COLS`` appended.
    """
    _require_ohlcv(df)
    if len(FIXED_FEATURE_COLS) != 50:
        raise RuntimeError("FIXED_FEATURE_COLS must contain exactly 50 names")
    if len(set(FIXED_FEATURE_COLS)) != 50:
        raise RuntimeError("FIXED_FEATURE_COLS must be unique")

    out = df.loc[:, list(OHLCV_COLS)].copy()
    close = out["close"].astype(np.float64)
    high = out["high"].astype(np.float64)
    low = out["low"].astype(np.float64)
    open_ = out["open"].astype(np.float64)
    volume = out["volume"].astype(np.float64)
    close_safe = close.replace(0.0, np.nan)
    atr = causal_atr(out, period=int(atr_period))
    out["atr"] = atr
    log_ret = np.log(close_safe).diff()
    log_volume = np.log1p(volume.clip(lower=0.0))
    body = close - open_
    body_sign = pd.Series(np.sign(body.to_numpy()), index=out.index).fillna(0.0)
    candle_range = high - low

    feats: Dict[str, pd.Series] = {}
    for k in (1, 2, 4, 8, 12, 24, 48):
        feats[f"return_{k}"] = np.log(close_safe / close_safe.shift(k))
    feats["candle_body"] = body / close_safe
    feats["range_pct"] = candle_range / close_safe
    feats["upper_wick_pct"] = (high - np.maximum(close, open_)) / close_safe
    feats["lower_wick_pct"] = (np.minimum(close, open_) - low) / close_safe
    feats["close_location"] = (close - low) / candle_range.replace(0.0, np.nan)

    ema_cache: Dict[int, pd.Series] = {}
    for span in (8, 16, 24, 48):
        ema = close.ewm(span=span, adjust=False, min_periods=span).mean()
        ema_cache[span] = ema
        feats[f"ema_distance_{span}"] = (close - ema) / close_safe
    for span in (8, 24, 48):
        ema = ema_cache[span]
        feats[f"ema_slope_{span}"] = (ema - ema.shift(1)) / close_safe

    for period in (7, 14, 28):
        feats[f"rsi_{period}"] = _wilder_rsi(close, period=period)

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_raw = ema12 - ema26
    signal_raw = macd_raw.ewm(span=9, adjust=False, min_periods=9).mean()
    feats["macd"] = macd_raw / close_safe
    feats["macd_signal_distance"] = (macd_raw - signal_raw) / close_safe
    feats["adx_14"] = _wilder_adx(high, low, close, period=14)
    feats["atr_pct_14"] = atr / close_safe
    for window in (4, 12, 24):
        feats[f"rv_{window}"] = log_ret.rolling(window, min_periods=window).std()
    feats["volatility_ratio"] = feats["rv_4"] / feats["rv_24"].replace(0.0, np.nan)

    sma20 = close.rolling(20, min_periods=20).mean()
    std20 = close.rolling(20, min_periods=20).std()
    feats["bollinger_z_20"] = (close - sma20) / std20.replace(0.0, np.nan)

    for window in (24, 48):
        hh = high.rolling(window, min_periods=window).max()
        ll = low.rolling(window, min_periods=window).min()
        feats[f"range_position_{window}"] = (close - ll) / (hh - ll).replace(
            0.0, np.nan
        )

    prior_high = high.shift(1).rolling(24, min_periods=24).max()
    prior_low = low.shift(1).rolling(24, min_periods=24).min()
    above = close - prior_high
    below = close - prior_low
    breakout = pd.Series(
        np.where(
            close > prior_high,
            above,
            np.where(close < prior_low, below, 0.0),
        ),
        index=out.index,
    )
    channel_ok = prior_high.notna() & prior_low.notna()
    feats["breakout_distance_24"] = (breakout / close_safe).where(channel_ok)

    feats["log_volume"] = log_volume
    feats["volume_change"] = log_volume.diff()
    vol_mean = volume.rolling(24, min_periods=24).mean()
    vol_std = volume.rolling(24, min_periods=24).std()
    feats["volume_zscore_24"] = (volume - vol_mean) / vol_std.replace(0.0, np.nan)
    feats["signed_volume_proxy"] = body_sign * log_volume
    feats["volume_trend_24"] = log_volume - log_volume.shift(24)

    changed = body_sign.ne(body_sign.shift())
    groups = changed.cumsum()
    feats["consecutive_candle_direction"] = body_sign * (
        body_sign.groupby(groups).cumcount() + 1
    )
    hh_flag = (high > high.shift(1)).astype(np.float64)
    ll_flag = (low < low.shift(1)).astype(np.float64)
    hh_flag.iloc[0] = np.nan
    ll_flag.iloc[0] = np.nan
    feats["higher_high_count_8"] = hh_flag.rolling(8, min_periods=8).sum()
    feats["lower_low_count_8"] = ll_flag.rolling(8, min_periods=8).sum()

    net = (close - close.shift(24)).abs()
    path = close.diff().abs().rolling(24, min_periods=24).sum()
    feats["trend_efficiency_24"] = net / path.replace(0.0, np.nan)
    feats["rolling_return_skew_24"] = log_ret.rolling(24, min_periods=24).skew()
    feats["rolling_return_kurtosis_24"] = log_ret.rolling(24, min_periods=24).kurt()

    ts = pd.to_datetime(out["time"], utc=True)
    hour = ts.dt.hour + ts.dt.minute / 60.0
    feats["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    feats["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    feats["weekday_sin"] = np.sin(2.0 * np.pi * ts.dt.dayofweek / 7.0)
    feats["weekday_cos"] = np.cos(2.0 * np.pi * ts.dt.dayofweek / 7.0)

    hh48 = high.rolling(48, min_periods=48).max()
    ll48 = low.rolling(48, min_periods=48).min()
    feats["drawdown_48"] = close / hh48.replace(0.0, np.nan) - 1.0
    dist_high = (hh48 - close) / close_safe
    dist_low = (close - ll48) / close_safe
    feats["distance_from_rolling_extreme"] = pd.Series(
        np.minimum(dist_high.to_numpy(), dist_low.to_numpy()),
        index=out.index,
    )

    featured = pd.concat([out, pd.DataFrame(feats, index=out.index)], axis=1)
    missing_cols = [c for c in FIXED_FEATURE_COLS if c not in featured.columns]
    if missing_cols:
        raise RuntimeError(f"Feature builder missing columns: {missing_cols}")
    return featured


def _forward_stack(values: np.ndarray, k: int) -> np.ndarray:
    """(k, n) array; row j holds values shifted back by j+1 bars."""
    n = values.shape[0]
    out = np.full((k, n), np.nan, dtype=np.float64)
    for j in range(1, k + 1):
        if n - j > 0:
            out[j - 1, : n - j] = values[j:]
    return out


def _first_touch_labels(
    fwd_high: np.ndarray,
    fwd_low: np.ndarray,
    tp_level: np.ndarray,
    sl_level: np.ndarray,
    *,
    short: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    """First-touch TP/SL/timeout. Same-bar double touch is SL first."""
    if short:
        tp_hits = fwd_low <= tp_level[None, :]
        sl_hits = fwd_high >= sl_level[None, :]
    else:
        tp_hits = fwd_high >= tp_level[None, :]
        sl_hits = fwd_low <= sl_level[None, :]
    any_hit = tp_hits | sl_hits
    has_hit = any_hit.any(axis=0)
    first = np.argmax(any_hit, axis=0)
    cols = np.arange(fwd_high.shape[1])
    tp_first = tp_hits[first, cols]
    sl_first = sl_hits[first, cols]
    double_hit = has_hit & tp_first & sl_first
    opp = np.where(
        ~has_hit,
        OPP_TIMEOUT,
        np.where(sl_first, OPP_SL_FIRST, OPP_TP_FIRST),
    ).astype(np.int64)
    return opp, double_hit.astype(np.float64)


def assign_regime(
    ema_slope_48: np.ndarray,
    adx_14: np.ndarray,
    *,
    adx_min: float = ADX_REGIME_MIN,
) -> np.ndarray:
    """Causal UP/DOWN/RANGE from EMA48 slope and ADX. Missing values are RANGE."""
    slope = np.asarray(ema_slope_48, dtype=np.float64).reshape(-1)
    adx = np.asarray(adx_14, dtype=np.float64).reshape(-1)
    finite = np.isfinite(slope) & np.isfinite(adx)
    out = np.full(slope.shape[0], REGIME_RANGE, dtype=np.int64)
    out[finite & (slope > 0.0) & (adx >= float(adx_min))] = REGIME_UP
    out[finite & (slope < 0.0) & (adx >= float(adx_min))] = REGIME_DOWN
    return out


def exclusive_path_labels(y_long: np.ndarray, y_short: np.ndarray) -> np.ndarray:
    """Exclusive TP-first without regime. Conflicts and SL/timeout are SKIP."""
    y_l = np.asarray(y_long, dtype=np.int64).reshape(-1)
    y_s = np.asarray(y_short, dtype=np.int64).reshape(-1)
    out = np.full(y_l.shape[0], EXCL_SKIP, dtype=np.int64)
    out[(y_l == OPP_TP_FIRST) & (y_s != OPP_TP_FIRST)] = EXCL_LONG
    out[(y_s == OPP_TP_FIRST) & (y_l != OPP_TP_FIRST)] = EXCL_SHORT
    out[(y_l < 0) | (y_s < 0)] = UNLABELED
    return out


def exclusive_regime_labels(
    y_path: np.ndarray, regime: np.ndarray
) -> np.ndarray:
    """Keep exclusive longs on UP and exclusive shorts on DOWN. Else SKIP."""
    y = np.asarray(y_path, dtype=np.int64).reshape(-1)
    reg = np.asarray(regime, dtype=np.int64).reshape(-1)
    unlabeled = y < 0
    out = np.full(y.shape[0], EXCL_SKIP, dtype=np.int64)
    out[(y == EXCL_LONG) & (reg == REGIME_UP)] = EXCL_LONG
    out[(y == EXCL_SHORT) & (reg == REGIME_DOWN)] = EXCL_SHORT
    out[unlabeled] = UNLABELED
    return out


def attach_fixed_targets(
    df: pd.DataFrame,
    *,
    horizon_bars: int = FROZEN_HORIZON_BARS,
    tp_atr_mult: float = TP_ATR_MULT,
    sl_atr_mult: float = SL_ATR_MULT,
    dir_band_atr_mult: float = DIR_BAND_ATR_MULT,
    atr_period: int = ATR_PERIOD_DEFAULT,
) -> pd.DataFrame:
    """Attach locked 24-bar targets. Last ``horizon_bars`` stay unlabeled.

    Entry is ``close[t]``. Long opportunity: TP ``tp_atr_mult`` ATR above,
    SL ``sl_atr_mult`` ATR below. Short opportunity is the mirror. A same-bar
    double touch is labeled SL first on that side. Exclusive and regime
    columns are attached when causal slope/ADX features are present.

    Args:
        df: Frame with OHLCV and preferably a causal ``atr`` column.
        horizon_bars: Forward path length.
        tp_atr_mult: Take-profit distance in ATR units.
        sl_atr_mult: Stop distance in ATR units.
        dir_band_atr_mult: Neutral band around a zero 24-bar log return.
        atr_period: Used only when ``atr`` is missing.

    Returns:
        Copy with ``y_*`` targets, ``fwd_return_pct``, and causal ``tp_pct`` /
        ``sl_pct``.
    """
    out = df.copy().reset_index(drop=True)
    n = len(out)
    k = int(horizon_bars)
    close = out["close"].to_numpy(dtype=np.float64)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    if "atr" in out.columns:
        atr = out["atr"].to_numpy(dtype=np.float64)
    else:
        atr = causal_atr(out, period=int(atr_period)).to_numpy(dtype=np.float64)

    y_dir = np.full(n, UNLABELED, dtype=np.int64)
    y_ret = np.full(n, np.nan, dtype=np.float64)
    y_vol = np.full(n, np.nan, dtype=np.float64)
    y_opp = np.full(n, UNLABELED, dtype=np.int64)
    y_opp_s = np.full(n, UNLABELED, dtype=np.int64)
    y_up = np.full(n, np.nan, dtype=np.float64)
    y_dn = np.full(n, np.nan, dtype=np.float64)
    double = np.full(n, np.nan, dtype=np.float64)
    double_s = np.full(n, np.nan, dtype=np.float64)
    fwd_pct = np.full(n, np.nan, dtype=np.float64)

    fwd_high = _forward_stack(high, k)
    fwd_low = _forward_stack(low, k)
    fwd_close = _forward_stack(close, k)
    index = np.arange(n)
    horizon_ok = index < n - k
    atr_ok = np.isfinite(atr) & (atr > _EPS)
    close_ok = np.isfinite(close) & (np.abs(close) > _EPS)
    path_ok = np.isfinite(fwd_close).all(axis=0) & np.isfinite(fwd_high).all(
        axis=0
    ) & np.isfinite(fwd_low).all(axis=0)
    valid = horizon_ok & atr_ok & close_ok & path_ok

    end_close = np.full(n, np.nan, dtype=np.float64)
    if n > k:
        end_close[: n - k] = close[k:]
    with np.errstate(invalid="ignore", divide="ignore"):
        log_r = np.log(end_close / close)
        band = float(dir_band_atr_mult) * atr / close
        fwd_pct_all = end_close / close - 1.0
        prev = np.concatenate([close[None, :], fwd_close[:-1, :]], axis=0)
        step = np.log(fwd_close / prev)
        rms = np.sqrt(np.mean(np.square(step), axis=0))
        max_high = np.nanmax(
            np.where(np.isfinite(fwd_high), fwd_high, -np.inf), axis=0
        )
        min_low = np.nanmin(
            np.where(np.isfinite(fwd_low), fwd_low, np.inf), axis=0
        )
        upside = (max_high - close) / close
        downside = (close - min_low) / close
        long_tp = close + float(tp_atr_mult) * atr
        long_sl = close - float(sl_atr_mult) * atr
        short_tp = close - float(tp_atr_mult) * atr
        short_sl = close + float(sl_atr_mult) * atr
        tp_pct_all = float(tp_atr_mult) * atr / close
        sl_pct_all = float(sl_atr_mult) * atr / close

    opp, double_hit = _first_touch_labels(
        fwd_high, fwd_low, long_tp, long_sl, short=False
    )
    opp_s, double_s_hit = _first_touch_labels(
        fwd_high, fwd_low, short_tp, short_sl, short=True
    )
    direction = np.where(
        log_r > band,
        DIR_UP,
        np.where(log_r < -band, DIR_DOWN, DIR_NEUTRAL),
    ).astype(np.int64)

    y_dir[valid] = direction[valid]
    y_ret[valid] = log_r[valid]
    y_vol[valid] = rms[valid]
    y_opp[valid] = opp[valid]
    y_opp_s[valid] = opp_s[valid]
    y_up[valid] = upside[valid]
    y_dn[valid] = downside[valid]
    double[valid] = double_hit[valid]
    double_s[valid] = double_s_hit[valid]
    fwd_pct[valid] = fwd_pct_all[valid]

    out["atr"] = atr
    out["y_direction"] = y_dir
    out["y_return"] = y_ret
    out["y_volatility"] = y_vol
    out["y_opportunity"] = y_opp
    out["y_opportunity_short"] = y_opp_s
    out["y_upside"] = y_up
    out["y_downside"] = y_dn
    out["same_bar_double_touch"] = double
    out["same_bar_double_touch_short"] = double_s
    out["fwd_return_pct"] = fwd_pct
    out["tp_pct"] = np.where(valid, tp_pct_all, np.nan)
    out["sl_pct"] = np.where(valid, sl_pct_all, np.nan)
    if "ema_slope_48" in out.columns and "adx_14" in out.columns:
        regime = assign_regime(
            out["ema_slope_48"].to_numpy(dtype=np.float64),
            out["adx_14"].to_numpy(dtype=np.float64),
        )
    else:
        regime = np.full(n, REGIME_RANGE, dtype=np.int64)
    y_path = exclusive_path_labels(y_opp, y_opp_s)
    y_excl = exclusive_regime_labels(y_path, regime)
    out["regime"] = regime
    out["y_exclusive_path"] = y_path
    out["y_exclusive"] = y_excl
    return out


def block_shuffle(
    values: np.ndarray, *, block: int, rng: np.random.Generator
) -> np.ndarray:
    """Permute labels in horizon-length blocks so serial dependence is kept."""
    arr = np.asarray(values)
    n = arr.shape[0]
    k = max(int(block), 1)
    parts = [arr[i : i + k] for i in range(0, n, k)]
    order = rng.permutation(len(parts))
    return np.concatenate([parts[i] for i in order], axis=0)[:n]


def shuffle_labeled_target(
    y: np.ndarray,
    *,
    labeled: np.ndarray,
    block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Block-shuffle labeled rows only. Unlabeled positions stay unlabeled."""
    out = np.asarray(y).copy()
    idx = np.flatnonzero(np.asarray(labeled, dtype=bool))
    if idx.size == 0:
        return out
    out[idx] = block_shuffle(out[idx], block=block, rng=rng)
    return out


def _fit_scaler(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, keepdims=True)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _scale_x(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _xgb_kwargs(config: Mapping[str, Any], n_estimators: int, seed: int) -> Dict[str, Any]:
    return dict(
        n_estimators=int(n_estimators),
        max_depth=int(config["max_depth"]),
        learning_rate=float(config["learning_rate"]),
        min_child_weight=int(config["min_leaf"]),
        subsample=0.8,
        colsample_bytree=0.7,
        reg_lambda=5.0,
        tree_method="hist",
        n_jobs=int(config.get("threads_per_model", 2)),
        verbosity=0,
        random_state=int(seed),
    )


def _log_loss(y: np.ndarray, proba: np.ndarray, *, n_classes: int) -> float:
    y = np.asarray(y, dtype=np.int64).reshape(-1)
    p = np.asarray(proba, dtype=np.float64)
    if p.ndim != 2 or p.shape[0] != y.shape[0] or p.shape[1] != int(n_classes):
        return float("nan")
    if y.size == 0:
        return float("nan")
    p = np.clip(p, 1e-15, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    return float(-np.mean(np.log(p[np.arange(y.size), y])))


def _rmse(y: np.ndarray, pred: np.ndarray) -> float:
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    pred = np.asarray(pred, dtype=np.float64).reshape(-1)
    mask = np.isfinite(y) & np.isfinite(pred)
    if not mask.any():
        return float("nan")
    err = y[mask] - pred[mask]
    return float(np.sqrt(np.mean(np.square(err))))


def _class_prior(y: np.ndarray, n_classes: int) -> np.ndarray:
    prior = np.zeros(int(n_classes), dtype=np.float64)
    for c in range(int(n_classes)):
        prior[c] = float(np.mean(y == c))
    prior = np.clip(prior, 1e-6, 1.0)
    return prior / prior.sum()


def _align_multiclass_proba(clf: Any, x: np.ndarray, n_classes: int) -> np.ndarray:
    n = x.shape[0]
    out = np.full((n, int(n_classes)), 1.0 / float(n_classes), dtype=np.float64)
    if clf is None or n == 0:
        return out
    raw = np.asarray(clf.predict_proba(x), dtype=np.float64)
    classes = np.asarray(getattr(clf, "classes_", np.arange(raw.shape[1])))
    for j, cls in enumerate(classes.reshape(-1)):
        ci = int(cls)
        if 0 <= ci < int(n_classes) and j < raw.shape[1]:
            out[:, ci] = raw[:, j]
    out = np.clip(out, 1e-15, 1.0)
    return out / out.sum(axis=1, keepdims=True)


def majority_skill(model: Sequence[float], baseline: Sequence[float]) -> Dict[str, Any]:
    """True when a majority of scored folds beat the naive baseline (lower better)."""
    beats: List[bool] = []
    for m, b in zip(model, baseline):
        if np.isfinite(m) and np.isfinite(b):
            beats.append(bool(m < b))
    n = len(beats)
    share = float(np.mean(beats)) if n else float("nan")
    return {
        "n_folds_scored": n,
        "skill_share": share,
        "learnable": bool(n > 0 and share > 0.5),
    }


def _usable_class(frame: pd.DataFrame, y_col: str) -> np.ndarray:
    feats = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y = frame[y_col].to_numpy(dtype=np.int64)
    return (y >= 0) & np.isfinite(feats).all(axis=1)


def _usable_reg(frame: pd.DataFrame, y_col: str) -> np.ndarray:
    feats = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y = frame[y_col].to_numpy(dtype=np.float64)
    return np.isfinite(y) & np.isfinite(feats).all(axis=1)


def _in_split(n: int, split_idx: np.ndarray, usable: np.ndarray) -> np.ndarray:
    allowed = np.zeros(n, dtype=bool)
    idx = np.asarray(split_idx, dtype=np.int64)
    idx = idx[(idx >= 0) & (idx < n)]
    allowed[idx] = True
    return allowed & np.asarray(usable, dtype=bool)


def _class_mix(y: np.ndarray, names: Sequence[str]) -> Dict[str, float]:
    labeled = y[y >= 0]
    mix = {name: 0.0 for name in names}
    if labeled.size == 0:
        return mix
    for i, name in enumerate(names):
        mix[name] = float(np.mean(labeled == i))
    return mix


def _balanced_sample_weight(y: np.ndarray, n_classes: int) -> np.ndarray:
    y_arr = np.asarray(y, dtype=np.int64).reshape(-1)
    counts = np.bincount(
        np.clip(y_arr, 0, int(n_classes) - 1), minlength=int(n_classes)
    ).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = counts.sum() / (float(n_classes) * counts)
    return weights[np.clip(y_arr, 0, int(n_classes) - 1)]


def _fit_classifier(
    x: np.ndarray,
    y: np.ndarray,
    *,
    config: Mapping[str, Any],
    n_estimators: int,
    seed: int,
    sample_weight: Optional[np.ndarray] = None,
) -> Any:
    from xgboost import XGBClassifier

    if len(np.unique(y)) < 2:
        return None
    clf = XGBClassifier(
        objective="multi:softprob",
        eval_metric="mlogloss",
        **_xgb_kwargs(config, n_estimators, seed),
    )
    if sample_weight is None:
        clf.fit(x, y.astype(np.int32))
    else:
        clf.fit(x, y.astype(np.int32), sample_weight=np.asarray(sample_weight))
    return clf


def _fit_regressor(
    x: np.ndarray,
    y: np.ndarray,
    *,
    config: Mapping[str, Any],
    n_estimators: int,
    seed: int,
) -> Any:
    from xgboost import XGBRegressor

    if x.shape[0] < 8 or not np.isfinite(y).any():
        return None
    model = XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        **_xgb_kwargs(config, n_estimators, seed),
    )
    model.fit(x, y.astype(np.float32))
    return model


def _trade_pnl(
    pred: np.ndarray,
    fwd_pct: np.ndarray,
    *,
    cost: float,
    long_class: int,
    short_class: Optional[int] = None,
) -> Dict[str, float]:
    pnl = np.full(pred.shape[0], np.nan, dtype=np.float64)
    long_m = pred == int(long_class)
    pnl[long_m] = fwd_pct[long_m] - float(cost)
    if short_class is not None:
        short_m = pred == int(short_class)
        pnl[short_m] = -fwd_pct[short_m] - float(cost)
    taken = np.isfinite(pnl)
    if not taken.any():
        return {"trade_n": 0.0, "trade_mean_pnl": float("nan")}
    return {
        "trade_n": float(taken.sum()),
        "trade_mean_pnl": float(np.mean(pnl[taken])),
    }


def _walk_classifier(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
    y_override: Optional[np.ndarray] = None,
    score_true_y: bool = True,
) -> Dict[str, Any]:
    y_col = str(spec["y_col"])
    n_classes = int(spec["n_classes"])
    names = tuple(spec.get("names") or [str(i) for i in range(n_classes)])
    y_true = frame[y_col].to_numpy(dtype=np.int64)
    y_fit_all = y_true if y_override is None else np.asarray(y_override, dtype=np.int64)
    usable = _usable_class(frame, y_col)
    if y_override is not None:
        usable = usable & (y_fit_all >= 0)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    fwd = frame["fwd_return_pct"].to_numpy(dtype=np.float64)
    n = len(frame)
    model_ll: List[float] = []
    base_ll: List[float] = []
    trade_pnls: List[float] = []
    trade_ns: List[float] = []
    fold_rows: List[Dict[str, Any]] = []
    for fold_i, (tr_idx, va_idx) in enumerate(wf_folds, start=1):
        fit_m = _in_split(n, tr_idx, usable)
        eval_m = _in_split(n, va_idx, usable)
        if int(fit_m.sum()) < 32 or int(eval_m.sum()) < 8:
            continue
        y_tr = y_fit_all[fit_m]
        y_ev_fit = y_fit_all[eval_m]
        y_ev_true = y_true[eval_m]
        if len(np.unique(y_tr)) < 2:
            continue
        mean, std = _fit_scaler(x_all[fit_m])
        x_tr = _scale_x(x_all[fit_m], mean, std)
        x_ev = _scale_x(x_all[eval_m], mean, std)
        clf = _fit_classifier(
            x_tr,
            y_tr,
            config=config,
            n_estimators=n_estimators,
            seed=int(seed) + fold_i,
        )
        proba = _align_multiclass_proba(clf, x_ev, n_classes)
        y_score = y_ev_true if score_true_y else y_ev_fit
        valid_score = y_score >= 0
        if int(valid_score.sum()) < 8:
            continue
        ll = _log_loss(y_score[valid_score], proba[valid_score], n_classes=n_classes)
        prior = _class_prior(y_tr, n_classes)
        base = _log_loss(
            y_score[valid_score],
            np.repeat(prior[None, :], int(valid_score.sum()), axis=0),
            n_classes=n_classes,
        )
        pred = np.argmax(proba, axis=1)
        if spec["id"] == "direction_head":
            traded = _trade_pnl(
                pred, fwd[eval_m], cost=float(config["round_trip_cost_pct"]),
                long_class=DIR_UP, short_class=DIR_DOWN,
            )
        else:
            traded = _trade_pnl(
                pred, fwd[eval_m], cost=float(config["round_trip_cost_pct"]),
                long_class=OPP_TP_FIRST, short_class=None,
            )
        model_ll.append(ll)
        base_ll.append(base)
        trade_pnls.append(float(traded["trade_mean_pnl"]))
        trade_ns.append(float(traded["trade_n"]))
        fold_rows.append(
            {
                "fold": fold_i,
                "log_loss": ll,
                "baseline_log_loss": base,
                "skill": bool(np.isfinite(ll) and np.isfinite(base) and ll < base),
                **traded,
            }
        )
        print(
            f"{spec['id']} fold {fold_i}: log_loss={ll:.4f} baseline={base:.4f} "
            f"skill={fold_rows[-1]['skill']} trades={traded['trade_n']:.0f}"
        )
    gate = majority_skill(model_ll, base_ll)
    finite_pnl = [p for p in trade_pnls if np.isfinite(p)]
    return {
        "head": spec["id"],
        "kind": "classification",
        "n_classes": n_classes,
        "class_mix": _class_mix(y_true, names),
        "wf_log_loss": float(np.mean(model_ll)) if model_ll else float("nan"),
        "wf_baseline_log_loss": float(np.mean(base_ll)) if base_ll else float("nan"),
        "trade_mean_pnl": float(np.mean(finite_pnl)) if finite_pnl else float("nan"),
        "trade_n": float(np.sum(trade_ns)) if trade_ns else 0.0,
        "fold_rows": fold_rows,
        **gate,
    }


def _walk_regressor(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    y_col = str(spec["y_col"])
    usable = _usable_reg(frame, y_col)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y_all = frame[y_col].to_numpy(dtype=np.float64)
    n = len(frame)
    model_s: List[float] = []
    base_s: List[float] = []
    fold_rows: List[Dict[str, Any]] = []
    for fold_i, (tr_idx, va_idx) in enumerate(wf_folds, start=1):
        fit_m = _in_split(n, tr_idx, usable)
        eval_m = _in_split(n, va_idx, usable)
        if int(fit_m.sum()) < 32 or int(eval_m.sum()) < 8:
            continue
        mean, std = _fit_scaler(x_all[fit_m])
        model = _fit_regressor(
            _scale_x(x_all[fit_m], mean, std),
            y_all[fit_m],
            config=config,
            n_estimators=n_estimators,
            seed=int(seed) + fold_i,
        )
        if model is None:
            continue
        pred = np.asarray(
            model.predict(_scale_x(x_all[eval_m], mean, std)), dtype=np.float64
        )
        rmse = _rmse(y_all[eval_m], pred)
        base = _rmse(y_all[eval_m], np.full(int(eval_m.sum()), y_all[fit_m].mean()))
        model_s.append(rmse)
        base_s.append(base)
        fold_rows.append(
            {
                "fold": fold_i,
                "rmse": rmse,
                "baseline_rmse": base,
                "skill": bool(np.isfinite(rmse) and np.isfinite(base) and rmse < base),
            }
        )
        print(
            f"{spec['id']} fold {fold_i}: rmse={rmse:.6f} baseline={base:.6f} "
            f"skill={fold_rows[-1]['skill']}"
        )
    gate = majority_skill(model_s, base_s)
    return {
        "head": spec["id"],
        "kind": "regression",
        "wf_rmse": float(np.mean(model_s)) if model_s else float("nan"),
        "wf_baseline_rmse": float(np.mean(base_s)) if base_s else float("nan"),
        "fold_rows": fold_rows,
        **gate,
    }


def _walk_excursion(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    y_up_col, y_dn_col = spec["y_cols"]
    usable = _usable_reg(frame, y_up_col) & _usable_reg(frame, y_dn_col)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y_up = frame[str(y_up_col)].to_numpy(dtype=np.float64)
    y_dn = frame[str(y_dn_col)].to_numpy(dtype=np.float64)
    n = len(frame)
    up_m: List[float] = []
    up_b: List[float] = []
    dn_m: List[float] = []
    dn_b: List[float] = []
    fold_rows: List[Dict[str, Any]] = []
    for fold_i, (tr_idx, va_idx) in enumerate(wf_folds, start=1):
        fit_m = _in_split(n, tr_idx, usable)
        eval_m = _in_split(n, va_idx, usable)
        if int(fit_m.sum()) < 32 or int(eval_m.sum()) < 8:
            continue
        mean, std = _fit_scaler(x_all[fit_m])
        x_tr = _scale_x(x_all[fit_m], mean, std)
        x_ev = _scale_x(x_all[eval_m], mean, std)
        up_model = _fit_regressor(
            x_tr, y_up[fit_m], config=config, n_estimators=n_estimators,
            seed=int(seed) + fold_i,
        )
        dn_model = _fit_regressor(
            x_tr, y_dn[fit_m], config=config, n_estimators=n_estimators,
            seed=int(seed) + fold_i + 17,
        )
        if up_model is None or dn_model is None:
            continue
        up_pred = np.asarray(up_model.predict(x_ev), dtype=np.float64)
        dn_pred = np.asarray(dn_model.predict(x_ev), dtype=np.float64)
        up_rmse = _rmse(y_up[eval_m], up_pred)
        dn_rmse = _rmse(y_dn[eval_m], dn_pred)
        up_base = _rmse(y_up[eval_m], np.full(int(eval_m.sum()), y_up[fit_m].mean()))
        dn_base = _rmse(y_dn[eval_m], np.full(int(eval_m.sum()), y_dn[fit_m].mean()))
        up_m.append(up_rmse)
        up_b.append(up_base)
        dn_m.append(dn_rmse)
        dn_b.append(dn_base)
        both = (
            np.isfinite(up_rmse)
            and np.isfinite(dn_rmse)
            and up_rmse < up_base
            and dn_rmse < dn_base
        )
        fold_rows.append(
            {
                "fold": fold_i,
                "rmse_upside": up_rmse,
                "rmse_downside": dn_rmse,
                "baseline_rmse_upside": up_base,
                "baseline_rmse_downside": dn_base,
                "skill": bool(both),
            }
        )
        print(
            f"{spec['id']} fold {fold_i}: up={up_rmse:.6f}/{up_base:.6f} "
            f"dn={dn_rmse:.6f}/{dn_base:.6f} skill={both}"
        )
    both_share = (
        float(np.mean([bool(r["skill"]) for r in fold_rows])) if fold_rows else float("nan")
    )
    n_scored = len(fold_rows)
    return {
        "head": spec["id"],
        "kind": "regression_pair",
        "wf_rmse_upside": float(np.mean(up_m)) if up_m else float("nan"),
        "wf_rmse_downside": float(np.mean(dn_m)) if dn_m else float("nan"),
        "wf_baseline_rmse_upside": float(np.mean(up_b)) if up_b else float("nan"),
        "wf_baseline_rmse_downside": float(np.mean(dn_b)) if dn_b else float("nan"),
        "n_folds_scored": n_scored,
        "skill_share": both_share,
        "learnable": bool(n_scored > 0 and both_share > 0.5),
        "fold_rows": fold_rows,
    }


def _confirm_classifier_test(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    y_col = str(spec["y_col"])
    n_classes = int(spec["n_classes"])
    usable = _usable_class(frame, y_col)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y_all = frame[y_col].to_numpy(dtype=np.int64)
    fwd = frame["fwd_return_pct"].to_numpy(dtype=np.float64)
    n = len(frame)
    train_idx = np.concatenate(
        [np.asarray(splits["train"]), np.asarray(splits["val"])], axis=0
    )
    fit_m = _in_split(n, train_idx, usable)
    test_m = _in_split(n, splits["test"], usable)
    if int(fit_m.sum()) < 32 or int(test_m.sum()) < 8 or len(np.unique(y_all[fit_m])) < 2:
        return {"head": spec["id"], "test_scored": False}
    mean, std = _fit_scaler(x_all[fit_m])
    clf = _fit_classifier(
        _scale_x(x_all[fit_m], mean, std),
        y_all[fit_m],
        config=config,
        n_estimators=n_estimators,
        seed=seed,
    )
    proba = _align_multiclass_proba(clf, _scale_x(x_all[test_m], mean, std), n_classes)
    ll = _log_loss(y_all[test_m], proba, n_classes=n_classes)
    prior = _class_prior(y_all[fit_m], n_classes)
    base = _log_loss(
        y_all[test_m],
        np.repeat(prior[None, :], int(test_m.sum()), axis=0),
        n_classes=n_classes,
    )
    pred = np.argmax(proba, axis=1)
    if spec["id"] == "direction_head":
        traded = _trade_pnl(
            pred, fwd[test_m], cost=float(config["round_trip_cost_pct"]),
            long_class=DIR_UP, short_class=DIR_DOWN,
        )
    else:
        traded = _trade_pnl(
            pred, fwd[test_m], cost=float(config["round_trip_cost_pct"]),
            long_class=OPP_TP_FIRST, short_class=None,
        )
    return {
        "head": spec["id"],
        "test_scored": True,
        "test_log_loss": ll,
        "test_baseline_log_loss": base,
        "test_skill": bool(np.isfinite(ll) and np.isfinite(base) and ll < base),
        "n_test": float(test_m.sum()),
        **{f"test_{k}": v for k, v in traded.items()},
    }


def _confirm_regressor_test(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    y_col = str(spec["y_col"])
    usable = _usable_reg(frame, y_col)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y_all = frame[y_col].to_numpy(dtype=np.float64)
    n = len(frame)
    train_idx = np.concatenate(
        [np.asarray(splits["train"]), np.asarray(splits["val"])], axis=0
    )
    fit_m = _in_split(n, train_idx, usable)
    test_m = _in_split(n, splits["test"], usable)
    if int(fit_m.sum()) < 32 or int(test_m.sum()) < 8:
        return {"head": spec["id"], "test_scored": False}
    mean, std = _fit_scaler(x_all[fit_m])
    model = _fit_regressor(
        _scale_x(x_all[fit_m], mean, std),
        y_all[fit_m],
        config=config,
        n_estimators=n_estimators,
        seed=seed,
    )
    if model is None:
        return {"head": spec["id"], "test_scored": False}
    pred = np.asarray(
        model.predict(_scale_x(x_all[test_m], mean, std)), dtype=np.float64
    )
    rmse = _rmse(y_all[test_m], pred)
    base = _rmse(y_all[test_m], np.full(int(test_m.sum()), y_all[fit_m].mean()))
    return {
        "head": spec["id"],
        "test_scored": True,
        "test_rmse": rmse,
        "test_baseline_rmse": base,
        "test_skill": bool(np.isfinite(rmse) and np.isfinite(base) and rmse < base),
        "n_test": float(test_m.sum()),
    }


def _confirm_excursion_test(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    y_up_col, y_dn_col = spec["y_cols"]
    usable = _usable_reg(frame, y_up_col) & _usable_reg(frame, y_dn_col)
    x_all = frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64)
    y_up = frame[str(y_up_col)].to_numpy(dtype=np.float64)
    y_dn = frame[str(y_dn_col)].to_numpy(dtype=np.float64)
    n = len(frame)
    train_idx = np.concatenate(
        [np.asarray(splits["train"]), np.asarray(splits["val"])], axis=0
    )
    fit_m = _in_split(n, train_idx, usable)
    test_m = _in_split(n, splits["test"], usable)
    if int(fit_m.sum()) < 32 or int(test_m.sum()) < 8:
        return {"head": spec["id"], "test_scored": False}
    mean, std = _fit_scaler(x_all[fit_m])
    x_tr = _scale_x(x_all[fit_m], mean, std)
    x_te = _scale_x(x_all[test_m], mean, std)
    up_model = _fit_regressor(
        x_tr, y_up[fit_m], config=config, n_estimators=n_estimators, seed=seed
    )
    dn_model = _fit_regressor(
        x_tr, y_dn[fit_m], config=config, n_estimators=n_estimators, seed=seed + 17
    )
    if up_model is None or dn_model is None:
        return {"head": spec["id"], "test_scored": False}
    up_rmse = _rmse(y_up[test_m], np.asarray(up_model.predict(x_te), dtype=np.float64))
    dn_rmse = _rmse(y_dn[test_m], np.asarray(dn_model.predict(x_te), dtype=np.float64))
    up_base = _rmse(y_up[test_m], np.full(int(test_m.sum()), y_up[fit_m].mean()))
    dn_base = _rmse(y_dn[test_m], np.full(int(test_m.sum()), y_dn[fit_m].mean()))
    return {
        "head": spec["id"],
        "test_scored": True,
        "test_rmse_upside": up_rmse,
        "test_rmse_downside": dn_rmse,
        "test_baseline_rmse_upside": up_base,
        "test_baseline_rmse_downside": dn_base,
        "test_skill": bool(
            np.isfinite(up_rmse)
            and np.isfinite(dn_rmse)
            and up_rmse < up_base
            and dn_rmse < dn_base
        ),
        "n_test": float(test_m.sum()),
    }


def _json_sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_sanitize(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return value if np.isfinite(value) else None
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _print_stage_frame(name: str, rows: Sequence[Mapping[str, Any]]) -> None:
    print(f"\n===== {name} =====")
    if not rows:
        print("(empty)")
        return
    frame = pd.DataFrame([dict(r) for r in rows])
    nested = [
        c
        for c in frame.columns
        if frame[c].map(lambda v: isinstance(v, (dict, list))).any()
    ]
    show = frame.drop(columns=nested) if nested else frame
    with pd.option_context(
        "display.max_rows", None, "display.max_columns", None, "display.width", 220
    ):
        print(show.to_string(index=False))


def _walk_one(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    kind = str(spec["kind"])
    if kind == "classification":
        return _walk_classifier(
            frame, spec, wf_folds, config, n_estimators=n_estimators, seed=seed
        )
    if kind == "regression":
        return _walk_regressor(
            frame, spec, wf_folds, config, n_estimators=n_estimators, seed=seed
        )
    return _walk_excursion(
        frame, spec, wf_folds, config, n_estimators=n_estimators, seed=seed
    )


def _confirm_one(
    frame: pd.DataFrame,
    spec: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    kind = str(spec["kind"])
    if kind == "classification":
        return _confirm_classifier_test(
            frame, spec, splits, config, n_estimators=n_estimators, seed=seed
        )
    if kind == "regression":
        return _confirm_regressor_test(
            frame, spec, splits, config, n_estimators=n_estimators, seed=seed
        )
    return _confirm_excursion_test(
        frame, spec, splits, config, n_estimators=n_estimators, seed=seed
    )


def run_fixed_target_experiments(
    bars: pd.DataFrame,
    *,
    config: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    export_dir: Path,
    n_estimators: Optional[int] = None,
) -> Dict[str, Any]:
    """Train each locked target separately on the frozen 50-feature set.

    Learnability is walk-forward skill versus a naive baseline. The held-out
    test split is scored once for heads that pass. Classifiers also get a
    block-shuffled label null.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    trees = int(n_estimators or config.get("n_estimators", N_ESTIMATORS_DEFAULT))
    seed = int(config.get("seed", SCREEN_SEED))
    rng = np.random.default_rng(seed)
    featured = add_fixed_ohlcv_features(
        bars, atr_period=int(config.get("atr_period", ATR_PERIOD_DEFAULT))
    )
    labeled = attach_fixed_targets(
        featured,
        horizon_bars=int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
        tp_atr_mult=TP_ATR_MULT,
        sl_atr_mult=SL_ATR_MULT,
        dir_band_atr_mult=DIR_BAND_ATR_MULT,
        atr_period=int(config.get("atr_period", ATR_PERIOD_DEFAULT)),
    )
    null_rates = labeled.loc[:, list(FIXED_FEATURE_COLS)].isna().mean()
    print("n_features", len(FIXED_FEATURE_COLS))
    print(
        "max feature null rate",
        round(float(null_rates.max()), 4),
        "at",
        str(null_rates.idxmax()),
    )
    double_n = int(np.nansum(labeled["same_bar_double_touch"].to_numpy()))
    print("opportunity same-bar double-touch", double_n)

    walk_forward: List[Dict[str, Any]] = []
    shuffle_rows: List[Dict[str, Any]] = []
    test_rows: List[Dict[str, Any]] = []
    spec_by_id = {str(s["id"]): s for s in TARGET_SPECS}
    for spec in TARGET_SPECS:
        print(f"\n===== {spec['id']} =====")
        result = _walk_one(
            labeled, spec, wf_folds, config, n_estimators=trees, seed=seed
        )
        walk_forward.append(result)
        if spec["kind"] == "classification":
            y_col = str(spec["y_col"])
            usable = _usable_class(labeled, y_col)
            shuffled = shuffle_labeled_target(
                labeled[y_col].to_numpy(dtype=np.int64),
                labeled=usable,
                block=int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
                rng=rng,
            )
            null = _walk_classifier(
                labeled,
                spec,
                wf_folds,
                config,
                n_estimators=trees,
                seed=seed + 100,
                y_override=shuffled,
                score_true_y=True,
            )
            shuffle_rows.append(
                {
                    "head": spec["id"],
                    "wf_log_loss": null["wf_log_loss"],
                    "wf_baseline_log_loss": null["wf_baseline_log_loss"],
                    "skill_share": null["skill_share"],
                    "learnable": null["learnable"],
                }
            )
        if result.get("learnable"):
            print(f"Test once {spec['id']}")
            test_rows.append(
                _confirm_one(
                    labeled, spec, splits, config, n_estimators=trees, seed=seed
                )
            )

    learnable = [r["head"] for r in walk_forward if r.get("learnable")]
    summary_rows = []
    for row in walk_forward:
        summary_rows.append(
            {
                "head": row["head"],
                "kind": row["kind"],
                "learnable": row.get("learnable"),
                "n_folds_scored": row.get("n_folds_scored"),
                "skill_share": row.get("skill_share"),
                "wf_log_loss": row.get("wf_log_loss"),
                "wf_baseline_log_loss": row.get("wf_baseline_log_loss"),
                "wf_rmse": row.get("wf_rmse"),
                "wf_baseline_rmse": row.get("wf_baseline_rmse"),
                "wf_rmse_upside": row.get("wf_rmse_upside"),
                "wf_rmse_downside": row.get("wf_rmse_downside"),
                "trade_mean_pnl": row.get("trade_mean_pnl"),
                "trade_n": row.get("trade_n"),
                "class_mix": row.get("class_mix"),
            }
        )
    _print_stage_frame("Walk-forward skill", summary_rows)
    _print_stage_frame("Shuffle null", shuffle_rows)
    _print_stage_frame("Test once", test_rows)
    print("learnable", learnable)
    print("opportunity_double_touch_n", double_n)

    payload = {
        "resolution": str(config.get("resolution", FROZEN_RESOLUTION)),
        "horizon_bars": int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
        "model": "XGB",
        "n_estimators": trees,
        "n_features": len(FIXED_FEATURE_COLS),
        "feature_cols": list(FIXED_FEATURE_COLS),
        "tp_atr_mult": TP_ATR_MULT,
        "sl_atr_mult": SL_ATR_MULT,
        "dir_band_atr_mult": DIR_BAND_ATR_MULT,
        "entry": "close[t]",
        "opportunity_side": "long",
        "opportunity_double_touch_n": double_n,
        "walk_forward": walk_forward,
        "shuffle_rows": shuffle_rows,
        "test_rows": test_rows,
        "learnable": learnable,
        "target_ids": [s["id"] for s in TARGET_SPECS],
        "spec_by_id": {k: {"id": v["id"], "kind": v["kind"]} for k, v in spec_by_id.items()},
    }
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "sweep.json").write_text(
        json.dumps(_json_sanitize(payload), indent=2),
        encoding="utf-8",
    )
    print("wrote", export_dir / "sweep.json")
    return payload


def long_path_pnl(
    y_opp: np.ndarray,
    tp_pct: np.ndarray,
    sl_pct: np.ndarray,
    timeout_ret: np.ndarray,
    *,
    cost: float,
) -> np.ndarray:
    """Gross-of-path long P&L minus round-trip cost."""
    y = np.asarray(y_opp, dtype=np.int64)
    tp = np.asarray(tp_pct, dtype=np.float64)
    sl = np.asarray(sl_pct, dtype=np.float64)
    timeout = np.asarray(timeout_ret, dtype=np.float64)
    gross = np.where(
        y == OPP_TP_FIRST,
        tp,
        np.where(y == OPP_SL_FIRST, -sl, timeout),
    )
    return gross - float(cost)


def short_path_pnl(
    y_opp: np.ndarray,
    tp_pct: np.ndarray,
    sl_pct: np.ndarray,
    timeout_ret: np.ndarray,
    *,
    cost: float,
) -> np.ndarray:
    """Gross-of-path short P&L minus round-trip cost."""
    y = np.asarray(y_opp, dtype=np.int64)
    tp = np.asarray(tp_pct, dtype=np.float64)
    sl = np.asarray(sl_pct, dtype=np.float64)
    timeout = np.asarray(timeout_ret, dtype=np.float64)
    gross = np.where(
        y == OPP_TP_FIRST,
        tp,
        np.where(y == OPP_SL_FIRST, -sl, -timeout),
    )
    return gross - float(cost)


def r_multiple(pnl: np.ndarray, sl_pct: np.ndarray) -> np.ndarray:
    """P&L in stop-distance units. Causal sl_pct only."""
    sl = np.asarray(sl_pct, dtype=np.float64)
    pnl_arr = np.asarray(pnl, dtype=np.float64)
    return pnl_arr / np.where(np.abs(sl) > R_EPS, sl, np.nan)


def apply_policy_mask(
    p_tp: np.ndarray,
    pred_adverse: np.ndarray,
    sl_pct: np.ndarray,
    *,
    thr_opp: float,
    k_dd: float,
) -> np.ndarray:
    """Take a side when exclusive-prob and adverse excursion clear filters."""
    sl = np.asarray(sl_pct, dtype=np.float64)
    return (
        (np.asarray(p_tp, dtype=np.float64) >= float(thr_opp))
        & (np.asarray(pred_adverse, dtype=np.float64) <= float(k_dd) * sl)
        & np.isfinite(p_tp)
        & np.isfinite(pred_adverse)
        & np.isfinite(sl)
    )


def score_policy_r(
    take: np.ndarray,
    pnl: np.ndarray,
    sl_pct: np.ndarray,
    min_signals: int,
) -> Dict[str, float]:
    """R-expectancy on taken trades. No fallback when n < min_signals."""
    mask = np.asarray(take, dtype=bool).reshape(-1)
    r = r_multiple(pnl[mask], sl_pct[mask])
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n < int(min_signals):
        return {
            "r_expectancy": float("-inf"),
            "tstat": float("nan"),
            "n": float(n),
        }
    mean_r = float(r.mean())
    std = float(r.std(ddof=1)) if n > 1 else float("nan")
    tstat = (
        float(mean_r / (std / np.sqrt(n))) if n > 1 and std > 0 else float("nan")
    )
    return {"r_expectancy": mean_r, "tstat": tstat, "n": float(n)}


def apply_regime_policy(
    p_excl: np.ndarray,
    pred_up: np.ndarray,
    pred_down: np.ndarray,
    sl_pct: np.ndarray,
    regime: np.ndarray,
    *,
    thr_long: float,
    thr_short: float,
    k_dd: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Regime-aligned exclusive masks. Both-true bars are flattened."""
    p = np.asarray(p_excl, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] < 2:
        n = int(np.asarray(regime).reshape(-1).shape[0])
        z = np.zeros(n, dtype=bool)
        return z, z.copy()
    reg = np.asarray(regime, dtype=np.int64).reshape(-1)
    long_raw = (reg == REGIME_UP) & apply_policy_mask(
        p[:, EXCL_LONG],
        pred_down,
        sl_pct,
        thr_opp=thr_long,
        k_dd=k_dd,
    )
    short_raw = (reg == REGIME_DOWN) & apply_policy_mask(
        p[:, EXCL_SHORT],
        pred_up,
        sl_pct,
        thr_opp=thr_short,
        k_dd=k_dd,
    )
    conflict = long_raw & short_raw
    return long_raw & ~conflict, short_raw & ~conflict


def score_twosided_r(
    long_take: np.ndarray,
    short_take: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    sl_pct: np.ndarray,
    min_signals: int,
) -> Dict[str, float]:
    """Combined R plus per-side R. Conflicts must already be removed."""
    long_m = np.asarray(long_take, dtype=bool).reshape(-1)
    short_m = np.asarray(short_take, dtype=bool).reshape(-1)
    pnl = np.where(long_m, pnl_long, np.where(short_m, pnl_short, np.nan))
    total = score_policy_r(long_m | short_m, pnl, sl_pct, min_signals)
    long_s = score_policy_r(long_m, pnl_long, sl_pct, min_signals)
    short_s = score_policy_r(short_m, pnl_short, sl_pct, min_signals)
    return {
        "r_expectancy": total["r_expectancy"],
        "tstat": total["tstat"],
        "n": total["n"],
        "long_r_expectancy": long_s["r_expectancy"],
        "long_n": long_s["n"],
        "short_r_expectancy": short_s["r_expectancy"],
        "short_n": short_s["n"],
    }


def _mean_finite_r(
    rows: Sequence[Mapping[str, Any]], key: str = "r_expectancy"
) -> float:
    vals = [
        float(r[key])
        for r in rows
        if key in r and np.isfinite(r[key]) and r[key] > float("-inf") / 2
    ]
    return float(np.mean(vals)) if vals else float("-inf")


def non_overlapping_mask(
    take: np.ndarray,
    *,
    positions: Optional[np.ndarray] = None,
    horizon_bars: int = FROZEN_HORIZON_BARS,
) -> np.ndarray:
    """Keep the first fill in each horizon window; skip overlapping paths."""
    take_b = np.asarray(take, dtype=bool).reshape(-1)
    if positions is None:
        pos = np.arange(take_b.size, dtype=np.int64)
    else:
        pos = np.asarray(positions, dtype=np.int64).reshape(-1)
    out = np.zeros_like(take_b)
    blocked_until = -1_000_000_000
    for j in np.argsort(pos, kind="mergesort"):
        if not take_b[j]:
            continue
        if int(pos[j]) <= blocked_until:
            continue
        out[j] = True
        blocked_until = int(pos[j]) + int(horizon_bars) - 1
    return out


def exclusive_precision(
    y_true: np.ndarray, take: np.ndarray, class_id: int
) -> float:
    """Hit rate of ``class_id`` on taken rows."""
    y = np.asarray(y_true, dtype=np.int64).reshape(-1)
    mask = np.asarray(take, dtype=bool).reshape(-1) & (y >= 0)
    if not mask.any():
        return float("nan")
    return float(np.mean(y[mask] == int(class_id)))


def exclusive_precision_curve(
    y_true: np.ndarray,
    p_class: np.ndarray,
    class_id: int,
    quantiles: Sequence[float] = OPP_QUANTILES,
) -> List[Dict[str, float]]:
    """Exclusive hit rate at predicted-probability quantiles."""
    y = np.asarray(y_true, dtype=np.int64).reshape(-1)
    p = np.asarray(p_class, dtype=np.float64).reshape(-1)
    labeled = y >= 0
    rows: List[Dict[str, float]] = []
    if not labeled.any():
        return rows
    prior = float(np.mean(y[labeled] == int(class_id)))
    finite = labeled & np.isfinite(p)
    for q in quantiles:
        if not finite.any():
            rows.append(
                {
                    "quantile": float(q),
                    "threshold": float("nan"),
                    "precision": float("nan"),
                    "n": 0.0,
                    "prior": prior,
                    "beats_prior": False,
                }
            )
            continue
        thr = float(np.quantile(p[finite], float(q)))
        take = finite & (p >= thr)
        prec = exclusive_precision(y, take, class_id)
        rows.append(
            {
                "quantile": float(q),
                "threshold": thr,
                "precision": prec,
                "n": float(take.sum()),
                "prior": prior,
                "beats_prior": bool(np.isfinite(prec) and prec > prior),
            }
        )
    return rows


def regime_unfiltered_sides(
    regime: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Always long on UP, always short on DOWN, skip RANGE."""
    reg = np.asarray(regime, dtype=np.int64).reshape(-1)
    return reg == REGIME_UP, reg == REGIME_DOWN


def choose_regime_thresholds(
    p_excl: np.ndarray,
    pred_up: np.ndarray,
    pred_down: np.ndarray,
    sl_pct: np.ndarray,
    regime: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    positions: np.ndarray,
    *,
    min_signals: int,
    horizon_bars: int = FROZEN_HORIZON_BARS,
    opp_quantiles: Sequence[float] = OPP_QUANTILES,
    k_dd_grid: Sequence[float] = K_DD_GRID,
) -> Dict[str, float]:
    """Pick long/short P-thresholds and k_dd on calib non-overlap R."""
    best: Dict[str, float] = {
        "thr_long": 1.0,
        "thr_short": 1.0,
        "k_dd": float(k_dd_grid[0]),
        "r_expectancy": float("-inf"),
        "n": 0.0,
        "long_n": 0.0,
        "short_n": 0.0,
    }
    p = np.asarray(p_excl, dtype=np.float64)
    if p.ndim != 2 or p.shape[0] == 0:
        return best
    finite_l = np.isfinite(p[:, EXCL_LONG])
    finite_s = np.isfinite(p[:, EXCL_SHORT])
    if not finite_l.any() or not finite_s.any():
        return best
    for q_l in opp_quantiles:
        thr_l = float(np.quantile(p[finite_l, EXCL_LONG], float(q_l)))
        for q_s in opp_quantiles:
            thr_s = float(np.quantile(p[finite_s, EXCL_SHORT], float(q_s)))
            for k_dd in k_dd_grid:
                long_t, short_t = apply_regime_policy(
                    p,
                    pred_up,
                    pred_down,
                    sl_pct,
                    regime,
                    thr_long=thr_l,
                    thr_short=thr_s,
                    k_dd=float(k_dd),
                )
                long_n = non_overlapping_mask(
                    long_t, positions=positions, horizon_bars=horizon_bars
                )
                short_n = non_overlapping_mask(
                    short_t, positions=positions, horizon_bars=horizon_bars
                )
                scored = score_twosided_r(
                    long_n,
                    short_n,
                    pnl_long,
                    pnl_short,
                    sl_pct,
                    min_signals,
                )
                if float(scored["r_expectancy"]) > float(best["r_expectancy"]):
                    best = {
                        "thr_long": thr_l,
                        "thr_short": thr_s,
                        "k_dd": float(k_dd),
                        "r_expectancy": float(scored["r_expectancy"]),
                        "n": float(scored["n"]),
                        "long_n": float(scored["long_n"]),
                        "short_n": float(scored["short_n"]),
                    }
    return best


def policy_test_gate(
    fold_r: Sequence[float],
    unfiltered_r: float,
    shuffle_r: float,
    *,
    long_r: Optional[float] = None,
    short_r: Optional[float] = None,
    long_n: float = 0.0,
    short_n: float = 0.0,
    min_signals: int = MIN_SIGNALS_DEFAULT,
    cost_stress_r: Optional[float] = None,
    range_fill_share: Optional[float] = None,
    range_fill_cap: float = RANGE_FILL_CAP,
) -> bool:
    """True when mean WF R is positive, both sides pay, and beats comparators."""
    finite = [float(v) for v in fold_r if np.isfinite(v) and v > float("-inf") / 2]
    if not finite:
        return False
    mean_r = float(np.mean(finite))
    pos_share = float(np.mean([v > 0.0 for v in finite]))
    if mean_r <= 0.0 or pos_share <= 0.5:
        return False
    if np.isfinite(unfiltered_r) and mean_r <= float(unfiltered_r):
        return False
    if np.isfinite(shuffle_r) and mean_r <= float(shuffle_r):
        return False
    if long_r is None and short_r is None:
        return True
    if float(long_n) < int(min_signals) or float(short_n) < int(min_signals):
        return False
    if not (np.isfinite(long_r) and float(long_r) > 0.0):
        return False
    if not (np.isfinite(short_r) and float(short_r) > 0.0):
        return False
    if cost_stress_r is not None:
        if not (np.isfinite(cost_stress_r) and float(cost_stress_r) > 0.0):
            return False
    if range_fill_share is not None:
        if not np.isfinite(range_fill_share):
            return False
        if float(range_fill_share) > float(range_fill_cap):
            return False
    return True


def _usable_policy(frame: pd.DataFrame) -> np.ndarray:
    return (
        _usable_class(frame, "y_exclusive")
        & _usable_reg(frame, "y_volatility")
        & _usable_reg(frame, "y_upside")
        & _usable_reg(frame, "y_downside")
        & np.isfinite(frame["tp_pct"].to_numpy(dtype=np.float64))
        & np.isfinite(frame["sl_pct"].to_numpy(dtype=np.float64))
    )


def inner_split_train(
    train_idx: np.ndarray,
    *,
    calib_fraction: float,
    purge_bars: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Purged tail of a training window for threshold selection."""
    idx = np.asarray(train_idx, dtype=np.int64)
    n = idx.shape[0]
    cut = int(n * (1.0 - float(calib_fraction)))
    fit_idx = idx[: max(cut - int(purge_bars), 0)]
    calib_idx = idx[cut:]
    return fit_idx, calib_idx


def torch_available() -> bool:
    """True when PyTorch can be imported."""
    try:
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def _fit_xgb_policy_heads(
    x: np.ndarray,
    y_excl: np.ndarray,
    y_vol: np.ndarray,
    y_up: np.ndarray,
    y_dn: np.ndarray,
    *,
    config: Mapping[str, Any],
    n_estimators: int,
    seed: int,
) -> Dict[str, Any]:
    weights = _balanced_sample_weight(y_excl, 3)
    excl = _fit_classifier(
        x,
        y_excl,
        config=config,
        n_estimators=n_estimators,
        seed=seed,
        sample_weight=weights,
    )
    vol = _fit_regressor(
        x, y_vol, config=config, n_estimators=n_estimators, seed=seed + 2
    )
    up = _fit_regressor(
        x, y_up, config=config, n_estimators=n_estimators, seed=seed + 3
    )
    dn = _fit_regressor(
        x, y_dn, config=config, n_estimators=n_estimators, seed=seed + 4
    )
    return {
        "kind": "xgb",
        "excl": excl,
        "vol": vol,
        "up": up,
        "dn": dn,
    }


def _predict_xgb_heads(
    models: Mapping[str, Any], x: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = x.shape[0]
    p_excl = _align_multiclass_proba(models.get("excl"), x, 3)
    vol = (
        np.asarray(models["vol"].predict(x), dtype=np.float64)
        if models.get("vol") is not None
        else np.zeros(n, dtype=np.float64)
    )
    up = (
        np.asarray(models["up"].predict(x), dtype=np.float64)
        if models.get("up") is not None
        else np.zeros(n, dtype=np.float64)
    )
    dn = (
        np.asarray(models["dn"].predict(x), dtype=np.float64)
        if models.get("dn") is not None
        else np.zeros(n, dtype=np.float64)
    )
    return p_excl, vol.reshape(-1), up.reshape(-1), dn.reshape(-1)


def _build_policy_mlp(n_in: int, hidden: Tuple[int, int]) -> Any:
    import torch.nn as nn

    class PolicyMlp(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            h1, h2 = int(hidden[0]), int(hidden[1])
            self.backbone = nn.Sequential(
                nn.Linear(int(n_in), h1),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(h1, h2),
                nn.ReLU(),
            )
            self.exclusive = nn.Linear(h2, 3)
            self.vol = nn.Linear(h2, 1)
            self.exc = nn.Linear(h2, 2)

        def forward(self, x: Any) -> Tuple[Any, Any, Any]:
            h = self.backbone(x)
            return (
                self.exclusive(h),
                self.vol(h).squeeze(-1),
                self.exc(h),
            )

    return PolicyMlp()


def _fit_policy_mlp(
    x: np.ndarray,
    y_excl: np.ndarray,
    y_vol: np.ndarray,
    y_up: np.ndarray,
    y_dn: np.ndarray,
    *,
    seed: int,
    epochs: int = MLP_EPOCHS,
) -> Optional[Dict[str, Any]]:
    if not torch_available() or x.shape[0] < 32:
        return None
    import torch
    import torch.nn as nn

    torch.manual_seed(int(seed))
    vol_mean = float(np.mean(y_vol))
    vol_std = float(np.std(y_vol))
    vol_std = vol_std if vol_std > 1e-8 else 1.0
    exc = np.column_stack([y_up, y_dn]).astype(np.float32)
    exc_mean = exc.mean(axis=0, keepdims=True)
    exc_std = exc.std(axis=0, keepdims=True)
    exc_std = np.where(exc_std < 1e-8, 1.0, exc_std)
    model = _build_policy_mlp(x.shape[1], MLP_HIDDEN)
    opt = torch.optim.Adam(model.parameters(), lr=MLP_LR)
    class_w = np.bincount(
        np.clip(np.asarray(y_excl, dtype=np.int64), 0, 2), minlength=3
    ).astype(np.float64)
    class_w = np.maximum(class_w, 1.0)
    inv = class_w.sum() / (3.0 * class_w)
    ce = nn.CrossEntropyLoss(weight=torch.tensor(inv, dtype=torch.float32))
    mse = nn.MSELoss()
    xt = torch.from_numpy(np.asarray(x, dtype=np.float32))
    ye = torch.from_numpy(np.asarray(y_excl, dtype=np.int64))
    yv = torch.from_numpy(((y_vol - vol_mean) / vol_std).astype(np.float32))
    yexc = torch.from_numpy(((exc - exc_mean) / exc_std).astype(np.float32))
    n = xt.shape[0]
    batch = min(int(MLP_BATCH), n)
    model.train()
    for _epoch in range(int(epochs)):
        perm = torch.randperm(n)
        for start in range(0, n, batch):
            idx = perm[start : start + batch]
            opt.zero_grad()
            logits, vhat, ehat = model(xt[idx])
            loss = (
                ce(logits, ye[idx])
                + mse(vhat, yv[idx])
                + mse(ehat, yexc[idx])
            )
            loss.backward()
            opt.step()
    model.eval()
    return {
        "kind": "mlp",
        "model": model,
        "vol_mean": vol_mean,
        "vol_std": vol_std,
        "exc_mean": exc_mean.reshape(-1),
        "exc_std": exc_std.reshape(-1),
    }


def _predict_mlp_heads(
    models: Mapping[str, Any], x: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import torch
    import torch.nn.functional as F

    n = x.shape[0]
    if models is None or models.get("model") is None:
        p = np.full((n, 3), 1.0 / 3.0)
        z = np.zeros(n, dtype=np.float64)
        return p, z, z, z
    model = models["model"]
    model.eval()
    with torch.no_grad():
        xt = torch.from_numpy(np.asarray(x, dtype=np.float32))
        logits, vhat, ehat = model(xt)
        p_excl = F.softmax(logits, dim=1).cpu().numpy().astype(np.float64)
        vol = (
            vhat.cpu().numpy().reshape(-1) * float(models["vol_std"])
            + float(models["vol_mean"])
        )
        exc = ehat.cpu().numpy().astype(np.float64)
        up = exc[:, 0] * float(models["exc_std"][0]) + float(models["exc_mean"][0])
        dn = exc[:, 1] * float(models["exc_std"][1]) + float(models["exc_mean"][1])
    return p_excl, vol.reshape(-1), up.reshape(-1), dn.reshape(-1)


def _predict_heads(
    models: Mapping[str, Any], x: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if str(models.get("kind")) == "mlp":
        return _predict_mlp_heads(models, x)
    return _predict_xgb_heads(models, x)


def _arrays_for_policy(frame: pd.DataFrame) -> Dict[str, np.ndarray]:
    return {
        "x": frame.loc[:, list(FIXED_FEATURE_COLS)].to_numpy(dtype=np.float64),
        "y_excl": frame["y_exclusive"].to_numpy(dtype=np.int64),
        "y_opp": frame["y_opportunity"].to_numpy(dtype=np.int64),
        "y_opp_s": frame["y_opportunity_short"].to_numpy(dtype=np.int64),
        "y_vol": frame["y_volatility"].to_numpy(dtype=np.float64),
        "y_up": frame["y_upside"].to_numpy(dtype=np.float64),
        "y_dn": frame["y_downside"].to_numpy(dtype=np.float64),
        "tp": frame["tp_pct"].to_numpy(dtype=np.float64),
        "sl": frame["sl_pct"].to_numpy(dtype=np.float64),
        "fwd": frame["fwd_return_pct"].to_numpy(dtype=np.float64),
        "regime": frame["regime"].to_numpy(dtype=np.int64),
    }


def _fit_kind_models(
    kind: str,
    x_fit: np.ndarray,
    y_excl: np.ndarray,
    y_vol: np.ndarray,
    y_up: np.ndarray,
    y_dn: np.ndarray,
    *,
    config: Mapping[str, Any],
    n_estimators: int,
    seed: int,
) -> Optional[Dict[str, Any]]:
    if kind == "mlp":
        return _fit_policy_mlp(x_fit, y_excl, y_vol, y_up, y_dn, seed=seed)
    return _fit_xgb_policy_heads(
        x_fit,
        y_excl,
        y_vol,
        y_up,
        y_dn,
        config=config,
        n_estimators=n_estimators,
        seed=seed,
    )


def _pooled_side_stats(
    rows: Sequence[Mapping[str, Any]], r_key: str, n_key: str
) -> Tuple[float, float]:
    n_sum = float(sum(float(r.get(n_key, 0.0) or 0.0) for r in rows))
    rs = [
        float(r[r_key])
        for r in rows
        if r_key in r
        and np.isfinite(r[r_key])
        and r[r_key] > float("-inf") / 2
    ]
    mean_r = float(np.mean(rs)) if rs else float("-inf")
    return mean_r, n_sum


def _range_fill_share(
    long_t: np.ndarray, short_t: np.ndarray, regime: np.ndarray
) -> float:
    take = np.asarray(long_t, dtype=bool) | np.asarray(short_t, dtype=bool)
    if not take.any():
        return 0.0
    reg = np.asarray(regime, dtype=np.int64).reshape(-1)
    return float(np.mean(reg[take] == REGIME_RANGE))


def _score_take_pair(
    long_t: np.ndarray,
    short_t: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    sl: np.ndarray,
    positions: np.ndarray,
    *,
    min_n: int,
    horizon_bars: int,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    overlap = score_twosided_r(
        long_t, short_t, pnl_long, pnl_short, sl, min_n
    )
    long_n = non_overlapping_mask(
        long_t, positions=positions, horizon_bars=horizon_bars
    )
    short_n = non_overlapping_mask(
        short_t, positions=positions, horizon_bars=horizon_bars
    )
    clean = score_twosided_r(
        long_n, short_n, pnl_long, pnl_short, sl, min_n
    )
    return overlap, clean


def _cost_stress_r(
    long_t: np.ndarray,
    short_t: np.ndarray,
    y_opp: np.ndarray,
    y_opp_s: np.ndarray,
    tp: np.ndarray,
    sl: np.ndarray,
    fwd: np.ndarray,
    positions: np.ndarray,
    *,
    base_cost: float,
    min_n: int,
    horizon_bars: int,
    mult: float = 1.5,
) -> float:
    cost = float(base_cost) * float(mult)
    pnl_l = long_path_pnl(y_opp, tp, sl, fwd, cost=cost)
    pnl_s = short_path_pnl(y_opp_s, tp, sl, fwd, cost=cost)
    _overlap, clean = _score_take_pair(
        long_t,
        short_t,
        pnl_l,
        pnl_s,
        sl,
        positions,
        min_n=min_n,
        horizon_bars=horizon_bars,
    )
    return float(clean["r_expectancy"])


def _walk_policy(
    frame: pd.DataFrame,
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
    model_kind: str,
    y_excl_override: Optional[np.ndarray] = None,
    inner_calibration_split: Optional[
        Callable[..., Tuple[np.ndarray, np.ndarray]]
    ] = None,
) -> Dict[str, Any]:
    usable = _usable_policy(frame)
    pack = _arrays_for_policy(frame)
    if y_excl_override is not None:
        pack["y_excl"] = np.asarray(y_excl_override, dtype=np.int64)
    n = len(frame)
    cost = float(config["round_trip_cost_pct"])
    min_n = int(config.get("min_signals_aligned", MIN_SIGNALS_ALIGNED))
    horizon = int(config.get("horizon_bars", FROZEN_HORIZON_BARS))
    calib_frac = float(config.get("calib_fraction", 0.15))
    purge = int(config.get("purge_bars", FROZEN_HORIZON_BARS + 1))
    splitter = inner_calibration_split or inner_split_train
    fold_rows: List[Dict[str, Any]] = []
    unf_rows: List[Dict[str, Any]] = []
    always_long_rows: List[Dict[str, Any]] = []
    always_short_rows: List[Dict[str, Any]] = []
    last_models: Dict[str, Any] = {}
    last_thr: Dict[str, float] = {}
    last_mean: Optional[np.ndarray] = None
    last_std: Optional[np.ndarray] = None
    y_true = pack["y_excl"]
    idx_all = np.arange(n, dtype=np.int64)
    for fold_i, (tr_idx, va_idx) in enumerate(wf_folds, start=1):
        fit_idx, calib_idx = splitter(
            np.asarray(tr_idx, dtype=np.int64),
            calib_fraction=calib_frac,
            purge_bars=purge,
        )
        fit_m = _in_split(n, fit_idx, usable)
        calib_m = _in_split(n, calib_idx, usable)
        eval_m = _in_split(n, va_idx, usable)
        if int(fit_m.sum()) < 32 or int(eval_m.sum()) < 8 or not calib_m.any():
            continue
        y_fit = pack["y_excl"][fit_m]
        if len(np.unique(y_fit[y_fit >= 0])) < 2:
            continue
        mean, std = _fit_scaler(pack["x"][fit_m])
        x_fit = _scale_x(pack["x"][fit_m], mean, std)
        models = _fit_kind_models(
            model_kind,
            x_fit,
            y_fit,
            pack["y_vol"][fit_m],
            pack["y_up"][fit_m],
            pack["y_dn"][fit_m],
            config=config,
            n_estimators=n_estimators,
            seed=int(seed) + fold_i,
        )
        if models is None:
            continue
        p_c, _v_c, u_c, d_c = _predict_heads(
            models, _scale_x(pack["x"][calib_m], mean, std)
        )
        p_e, v_e, u_e, d_e = _predict_heads(
            models, _scale_x(pack["x"][eval_m], mean, std)
        )
        pnl_lc = long_path_pnl(
            pack["y_opp"][calib_m],
            pack["tp"][calib_m],
            pack["sl"][calib_m],
            pack["fwd"][calib_m],
            cost=cost,
        )
        pnl_sc = short_path_pnl(
            pack["y_opp_s"][calib_m],
            pack["tp"][calib_m],
            pack["sl"][calib_m],
            pack["fwd"][calib_m],
            cost=cost,
        )
        pnl_le = long_path_pnl(
            pack["y_opp"][eval_m],
            pack["tp"][eval_m],
            pack["sl"][eval_m],
            pack["fwd"][eval_m],
            cost=cost,
        )
        pnl_se = short_path_pnl(
            pack["y_opp_s"][eval_m],
            pack["tp"][eval_m],
            pack["sl"][eval_m],
            pack["fwd"][eval_m],
            cost=cost,
        )
        pos_c = idx_all[calib_m]
        pos_e = idx_all[eval_m]
        thr = choose_regime_thresholds(
            p_c,
            u_c,
            d_c,
            pack["sl"][calib_m],
            pack["regime"][calib_m],
            pnl_lc,
            pnl_sc,
            pos_c,
            min_signals=min_n,
            horizon_bars=horizon,
        )
        long_c, short_c = apply_regime_policy(
            p_c,
            u_c,
            d_c,
            pack["sl"][calib_m],
            pack["regime"][calib_m],
            thr_long=float(thr["thr_long"]),
            thr_short=float(thr["thr_short"]),
            k_dd=float(thr["k_dd"]),
        )
        _ov_c, calib_scored = _score_take_pair(
            long_c,
            short_c,
            pnl_lc,
            pnl_sc,
            pack["sl"][calib_m],
            pos_c,
            min_n=min_n,
            horizon_bars=horizon,
        )
        long_t, short_t = apply_regime_policy(
            p_e,
            u_e,
            d_e,
            pack["sl"][eval_m],
            pack["regime"][eval_m],
            thr_long=float(thr["thr_long"]),
            thr_short=float(thr["thr_short"]),
            k_dd=float(thr["k_dd"]),
        )
        overlap, scored = _score_take_pair(
            long_t,
            short_t,
            pnl_le,
            pnl_se,
            pack["sl"][eval_m],
            pos_e,
            min_n=min_n,
            horizon_bars=horizon,
        )
        unf_l, unf_s = regime_unfiltered_sides(pack["regime"][eval_m])
        _unf_o, unf = _score_take_pair(
            unf_l,
            unf_s,
            pnl_le,
            pnl_se,
            pack["sl"][eval_m],
            pos_e,
            min_n=min_n,
            horizon_bars=horizon,
        )
        always_l = score_policy_r(
            np.ones(int(eval_m.sum()), dtype=bool),
            pnl_le,
            pack["sl"][eval_m],
            min_n,
        )
        always_s = score_policy_r(
            np.ones(int(eval_m.sum()), dtype=bool),
            pnl_se,
            pack["sl"][eval_m],
            min_n,
        )
        long_nmask = non_overlapping_mask(
            long_t, positions=pos_e, horizon_bars=horizon
        )
        short_nmask = non_overlapping_mask(
            short_t, positions=pos_e, horizon_bars=horizon
        )
        y_eval = y_true[eval_m]
        prec_long = exclusive_precision(y_eval, long_nmask, EXCL_LONG)
        prec_short = exclusive_precision(y_eval, short_nmask, EXCL_SHORT)
        prior = _class_prior(y_fit, 3)
        ll = _log_loss(y_eval, p_e, n_classes=3)
        base_ll = _log_loss(
            y_eval,
            np.repeat(prior[None, :], int(eval_m.sum()), axis=0),
            n_classes=3,
        )
        stress = _cost_stress_r(
            long_t,
            short_t,
            pack["y_opp"][eval_m],
            pack["y_opp_s"][eval_m],
            pack["tp"][eval_m],
            pack["sl"][eval_m],
            pack["fwd"][eval_m],
            pos_e,
            base_cost=cost,
            min_n=min_n,
            horizon_bars=horizon,
            mult=1.5,
        )
        range_share = _range_fill_share(
            long_nmask, short_nmask, pack["regime"][eval_m]
        )
        curve_l = exclusive_precision_curve(
            y_eval, p_e[:, EXCL_LONG], EXCL_LONG
        )
        curve_s = exclusive_precision_curve(
            y_eval, p_e[:, EXCL_SHORT], EXCL_SHORT
        )
        calib_r = float(calib_scored["r_expectancy"])
        val_r = float(scored["r_expectancy"])
        gap = (
            calib_r - val_r
            if np.isfinite(calib_r) and np.isfinite(val_r)
            and calib_r > float("-inf") / 2
            and val_r > float("-inf") / 2
            else float("nan")
        )
        row = {
            "fold": fold_i,
            "kind": model_kind,
            "thr_long": thr["thr_long"],
            "thr_short": thr["thr_short"],
            "k_dd": thr["k_dd"],
            "r_expectancy": scored["r_expectancy"],
            "tstat": scored["tstat"],
            "n": scored["n"],
            "long_r_expectancy": scored["long_r_expectancy"],
            "long_n": scored["long_n"],
            "short_r_expectancy": scored["short_r_expectancy"],
            "short_n": scored["short_n"],
            "r_overlap": overlap["r_expectancy"],
            "n_overlap": overlap["n"],
            "calib_r": calib_r,
            "calib_val_gap": gap,
            "range_fill_share": range_share,
            "exclusive_precision_long": prec_long,
            "exclusive_precision_short": prec_short,
            "prior_long": float(prior[EXCL_LONG]),
            "prior_short": float(prior[EXCL_SHORT]),
            "log_loss": ll,
            "baseline_log_loss": base_ll,
            "cost_stress_r_1p5": stress,
            "vol_rmse": _rmse(pack["y_vol"][eval_m], v_e),
            "down_rmse": _rmse(pack["y_dn"][eval_m], d_e),
            "up_rmse": _rmse(pack["y_up"][eval_m], u_e),
            "precision_curve_long": curve_l,
            "precision_curve_short": curve_s,
        }
        fold_rows.append(row)
        unf_rows.append({"fold": fold_i, **unf})
        always_long_rows.append({"fold": fold_i, **always_l})
        always_short_rows.append({"fold": fold_i, **always_s})
        last_models = dict(models)
        last_thr = dict(thr)
        last_mean, last_std = mean, std
        print(
            f"{model_kind} policy fold {fold_i}: R={scored['r_expectancy']} "
            f"n={scored['n']:.0f} long_n={scored['long_n']:.0f} "
            f"short_n={scored['short_n']:.0f} unfiltered={unf['r_expectancy']}"
        )
    long_r, long_n = _pooled_side_stats(
        fold_rows, "long_r_expectancy", "long_n"
    )
    short_r, short_n = _pooled_side_stats(
        fold_rows, "short_r_expectancy", "short_n"
    )
    range_shares = [
        float(r["range_fill_share"])
        for r in fold_rows
        if np.isfinite(r.get("range_fill_share", np.nan))
    ]
    stress_vals = [
        float(r["cost_stress_r_1p5"])
        for r in fold_rows
        if np.isfinite(r.get("cost_stress_r_1p5", np.nan))
        and r["cost_stress_r_1p5"] > float("-inf") / 2
    ]
    return {
        "kind": model_kind,
        "wf_r_expectancy": _mean_finite_r(fold_rows),
        "wf_positive_share": (
            float(
                np.mean(
                    [
                        float(r["r_expectancy"]) > 0.0
                        for r in fold_rows
                        if np.isfinite(r["r_expectancy"])
                        and r["r_expectancy"] > float("-inf") / 2
                    ]
                    or [np.nan]
                )
            )
        ),
        "n_folds_scored": sum(
            1
            for r in fold_rows
            if np.isfinite(r["r_expectancy"])
            and r["r_expectancy"] > float("-inf") / 2
        ),
        "unfiltered_r": _mean_finite_r(unf_rows),
        "always_long_r": _mean_finite_r(always_long_rows),
        "always_short_r": _mean_finite_r(always_short_rows),
        "long_r_expectancy": long_r,
        "short_r_expectancy": short_r,
        "long_n": long_n,
        "short_n": short_n,
        "range_fill_share": (
            float(np.mean(range_shares)) if range_shares else 0.0
        ),
        "cost_stress_r_1p5": (
            float(np.mean(stress_vals)) if stress_vals else float("-inf")
        ),
        "fold_rows": fold_rows,
        "unfiltered_folds": unf_rows,
        "always_long_folds": always_long_rows,
        "always_short_folds": always_short_rows,
        "models": last_models,
        "thr": last_thr,
        "mean": last_mean,
        "std": last_std,
    }


def _confirm_policy_test(
    frame: pd.DataFrame,
    splits: Mapping[str, np.ndarray],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
    model_kind: str,
    inner_calibration_split: Optional[
        Callable[..., Tuple[np.ndarray, np.ndarray]]
    ] = None,
) -> Dict[str, Any]:
    usable = _usable_policy(frame)
    pack = _arrays_for_policy(frame)
    n = len(frame)
    cost = float(config["round_trip_cost_pct"])
    min_n = int(config.get("min_signals_aligned", MIN_SIGNALS_ALIGNED))
    horizon = int(config.get("horizon_bars", FROZEN_HORIZON_BARS))
    splitter = inner_calibration_split or inner_split_train
    fit_idx, calib_idx = splitter(
        np.asarray(splits["train"], dtype=np.int64),
        calib_fraction=float(config.get("calib_fraction", 0.15)),
        purge_bars=int(config.get("purge_bars", FROZEN_HORIZON_BARS + 1)),
    )
    val_idx = np.asarray(splits["val"], dtype=np.int64)
    if val_idx.size:
        calib_idx = val_idx
    fit_m = _in_split(n, fit_idx, usable)
    calib_m = _in_split(n, calib_idx, usable)
    test_m = _in_split(n, splits["test"], usable)
    if int(fit_m.sum()) < 32 or int(test_m.sum()) < 8 or not calib_m.any():
        return {"kind": model_kind, "test_scored": False}
    mean, std = _fit_scaler(pack["x"][fit_m])
    x_fit = _scale_x(pack["x"][fit_m], mean, std)
    models = _fit_kind_models(
        model_kind,
        x_fit,
        pack["y_excl"][fit_m],
        pack["y_vol"][fit_m],
        pack["y_up"][fit_m],
        pack["y_dn"][fit_m],
        config=config,
        n_estimators=n_estimators,
        seed=seed,
    )
    if models is None:
        return {"kind": model_kind, "test_scored": False}
    p_c, _v_c, u_c, d_c = _predict_heads(
        models, _scale_x(pack["x"][calib_m], mean, std)
    )
    p_t, _v_t, u_t, d_t = _predict_heads(
        models, _scale_x(pack["x"][test_m], mean, std)
    )
    pnl_lc = long_path_pnl(
        pack["y_opp"][calib_m],
        pack["tp"][calib_m],
        pack["sl"][calib_m],
        pack["fwd"][calib_m],
        cost=cost,
    )
    pnl_sc = short_path_pnl(
        pack["y_opp_s"][calib_m],
        pack["tp"][calib_m],
        pack["sl"][calib_m],
        pack["fwd"][calib_m],
        cost=cost,
    )
    pnl_lt = long_path_pnl(
        pack["y_opp"][test_m],
        pack["tp"][test_m],
        pack["sl"][test_m],
        pack["fwd"][test_m],
        cost=cost,
    )
    pnl_st = short_path_pnl(
        pack["y_opp_s"][test_m],
        pack["tp"][test_m],
        pack["sl"][test_m],
        pack["fwd"][test_m],
        cost=cost,
    )
    idx_all = np.arange(n, dtype=np.int64)
    pos_c = idx_all[calib_m]
    pos_t = idx_all[test_m]
    thr = choose_regime_thresholds(
        p_c,
        u_c,
        d_c,
        pack["sl"][calib_m],
        pack["regime"][calib_m],
        pnl_lc,
        pnl_sc,
        pos_c,
        min_signals=min_n,
        horizon_bars=horizon,
    )
    long_t, short_t = apply_regime_policy(
        p_t,
        u_t,
        d_t,
        pack["sl"][test_m],
        pack["regime"][test_m],
        thr_long=float(thr["thr_long"]),
        thr_short=float(thr["thr_short"]),
        k_dd=float(thr["k_dd"]),
    )
    overlap, scored = _score_take_pair(
        long_t,
        short_t,
        pnl_lt,
        pnl_st,
        pack["sl"][test_m],
        pos_t,
        min_n=min_n,
        horizon_bars=horizon,
    )
    stress = _cost_stress_r(
        long_t,
        short_t,
        pack["y_opp"][test_m],
        pack["y_opp_s"][test_m],
        pack["tp"][test_m],
        pack["sl"][test_m],
        pack["fwd"][test_m],
        pos_t,
        base_cost=cost,
        min_n=min_n,
        horizon_bars=horizon,
        mult=1.5,
    )
    return {
        "kind": model_kind,
        "test_scored": True,
        "n_test": float(test_m.sum()),
        "thr_long": thr["thr_long"],
        "thr_short": thr["thr_short"],
        "k_dd": thr["k_dd"],
        "test_r_overlap": overlap["r_expectancy"],
        "cost_stress_r_1p5": stress,
        **{f"test_{k}": v for k, v in scored.items()},
    }


def _gate_from_walk(walk: Mapping[str, Any], shuffle_r: float) -> bool:
    min_n = MIN_SIGNALS_ALIGNED
    return policy_test_gate(
        [r["r_expectancy"] for r in walk.get("fold_rows") or []],
        float(walk.get("unfiltered_r", float("-inf"))),
        float(shuffle_r),
        long_r=float(walk.get("long_r_expectancy", float("-inf"))),
        short_r=float(walk.get("short_r_expectancy", float("-inf"))),
        long_n=float(walk.get("long_n", 0.0)),
        short_n=float(walk.get("short_n", 0.0)),
        min_signals=min_n,
        cost_stress_r=walk.get("cost_stress_r_1p5"),
        range_fill_share=walk.get("range_fill_share"),
    )


def _public_walk(walk: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in walk.items() if k != "models"}


def _walk_barrier(
    labeled: pd.DataFrame,
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seed: int,
    model_kind: str,
    inner_calibration_split: Optional[
        Callable[..., Tuple[np.ndarray, np.ndarray]]
    ],
    rng: np.random.Generator,
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    print(f"\n===== {model_kind} policy =====")
    wf = _walk_policy(
        labeled,
        wf_folds,
        config,
        n_estimators=n_estimators,
        seed=seed,
        model_kind=model_kind,
        inner_calibration_split=inner_calibration_split,
    )
    usable = _usable_policy(labeled)
    shuffled = shuffle_labeled_target(
        labeled["y_exclusive"].to_numpy(dtype=np.int64),
        labeled=usable,
        block=int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
        rng=rng,
    )
    print(f"\n===== {model_kind} shuffle null =====")
    shuf = _walk_policy(
        labeled,
        wf_folds,
        config,
        n_estimators=n_estimators,
        seed=seed + 100,
        model_kind=model_kind,
        y_excl_override=shuffled,
        inner_calibration_split=inner_calibration_split,
    )
    gate = _gate_from_walk(wf, float(shuf.get("wf_r_expectancy", float("-inf"))))
    return wf, shuf, gate


def run_regime_exclusive_sweep(
    bars: pd.DataFrame,
    *,
    config: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    export_dir: Path,
    inner_calibration_split: Optional[
        Callable[..., Tuple[np.ndarray, np.ndarray]]
    ] = None,
    n_estimators: Optional[int] = None,
) -> Dict[str, Any]:
    """XGB exclusive policy on (2/2, 3/3, 4/2); MLP on the WF winner.

    Direction and return heads are not fit. Live fusion is not written.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    trees = int(n_estimators or config.get("n_estimators", N_ESTIMATORS_DEFAULT))
    seed = int(config.get("seed", SCREEN_SEED))
    rng = np.random.default_rng(seed)
    featured = add_fixed_ohlcv_features(
        bars, atr_period=int(config.get("atr_period", ATR_PERIOD_DEFAULT))
    )
    print("n_features", len(FIXED_FEATURE_COLS))
    print("policy heads", list(POLICY_HEAD_IDS))
    print("barriers", [b["id"] for b in BARRIER_SPECS])

    barrier_rows: List[Dict[str, Any]] = []
    barrier_payloads: Dict[str, Dict[str, Any]] = {}
    for spec in BARRIER_SPECS:
        bid = str(spec["id"])
        print(f"\n===== barrier {bid} =====")
        labeled = attach_fixed_targets(
            featured,
            horizon_bars=int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
            tp_atr_mult=float(spec["tp_atr_mult"]),
            sl_atr_mult=float(spec["sl_atr_mult"]),
            dir_band_atr_mult=DIR_BAND_ATR_MULT,
            atr_period=int(config.get("atr_period", ATR_PERIOD_DEFAULT)),
        )
        mix = _class_mix(
            labeled["y_exclusive"].to_numpy(dtype=np.int64), EXCL_NAMES
        )
        print("exclusive mix", mix)
        xgb_wf, xgb_shuf, xgb_gate = _walk_barrier(
            labeled,
            wf_folds,
            config,
            n_estimators=trees,
            seed=seed,
            model_kind="xgb",
            inner_calibration_split=inner_calibration_split,
            rng=rng,
        )
        row = {
            "barrier": bid,
            "tp_atr_mult": float(spec["tp_atr_mult"]),
            "sl_atr_mult": float(spec["sl_atr_mult"]),
            "model": "xgb_policy",
            "wf_r_expectancy": xgb_wf["wf_r_expectancy"],
            "wf_positive_share": xgb_wf["wf_positive_share"],
            "long_r": xgb_wf["long_r_expectancy"],
            "short_r": xgb_wf["short_r_expectancy"],
            "long_n": xgb_wf["long_n"],
            "short_n": xgb_wf["short_n"],
            "unfiltered_r": xgb_wf["unfiltered_r"],
            "shuffle_r": xgb_shuf["wf_r_expectancy"],
            "cost_stress_r_1p5": xgb_wf["cost_stress_r_1p5"],
            "range_fill_share": xgb_wf["range_fill_share"],
            "test_gate": xgb_gate,
            "exclusive_mix": mix,
        }
        barrier_rows.append(row)
        barrier_payloads[bid] = {
            "labeled_n": int(len(labeled)),
            "xgb_policy": _public_walk(xgb_wf),
            "xgb_shuffle": _public_walk(xgb_shuf),
            "xgb_test_gate": xgb_gate,
            "exclusive_mix": mix,
            "tp_atr_mult": float(spec["tp_atr_mult"]),
            "sl_atr_mult": float(spec["sl_atr_mult"]),
            "frame": labeled,
        }
        _print_stage_frame(f"{bid} XGB folds", xgb_wf.get("fold_rows") or [])
        _print_stage_frame(
            f"{bid} XGB unfiltered", xgb_wf.get("unfiltered_folds") or []
        )

    finite_rows = [
        r
        for r in barrier_rows
        if np.isfinite(r["wf_r_expectancy"])
        and r["wf_r_expectancy"] > float("-inf") / 2
    ]
    gated_rows = [r for r in finite_rows if r.get("test_gate")]
    pool = gated_rows or finite_rows
    if pool:
        winner = max(pool, key=lambda r: float(r["wf_r_expectancy"]))
        winner_id = str(winner["barrier"])
    else:
        winner_id = str(BARRIER_SPECS[0]["id"])
        winner = barrier_rows[0] if barrier_rows else {}
    winner_gate = bool(winner.get("test_gate"))
    print("wf_winner", winner_id, "gate", winner_gate)

    test_rows: List[Dict[str, Any]] = []
    winner_pack = barrier_payloads[winner_id]
    labeled_w = winner_pack["frame"]
    if winner_gate:
        print("Test once XGB policy", winner_id)
        test_rows.append(
            _confirm_policy_test(
                labeled_w,
                splits,
                config,
                n_estimators=trees,
                seed=seed,
                model_kind="xgb",
                inner_calibration_split=inner_calibration_split,
            )
        )

    mlp_wf: Dict[str, Any] = {"kind": "mlp", "skipped": True}
    mlp_shuf: Dict[str, Any] = {"kind": "mlp", "skipped": True}
    mlp_gate = False
    if torch_available():
        print(f"\n===== MLP on winner {winner_id} =====")
        mlp_wf, mlp_shuf, mlp_gate = _walk_barrier(
            labeled_w,
            wf_folds,
            config,
            n_estimators=trees,
            seed=seed,
            model_kind="mlp",
            inner_calibration_split=inner_calibration_split,
            rng=rng,
        )
        _print_stage_frame("MLP policy folds", mlp_wf.get("fold_rows") or [])
    else:
        print("Skipping Stage B MLP: torch is not available")

    ready = bool(winner_gate)
    payload = {
        "resolution": str(config.get("resolution", FROZEN_RESOLUTION)),
        "horizon_bars": int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
        "n_features": len(FIXED_FEATURE_COLS),
        "feature_cols": list(FIXED_FEATURE_COLS),
        "policy_heads": list(POLICY_HEAD_IDS),
        "entry": "close[t]",
        "opportunity_side": "regime_aligned_exclusive",
        "barriers": [b["id"] for b in BARRIER_SPECS],
        "barrier_rows": barrier_rows,
        "barriers_detail": {
            k: {sk: sv for sk, sv in v.items() if sk != "frame"}
            for k, v in barrier_payloads.items()
        },
        "winner_barrier": winner_id,
        "winner_gate": winner_gate,
        "mlp_policy": _public_walk(mlp_wf),
        "mlp_shuffle": _public_walk(mlp_shuf),
        "mlp_test_gate": mlp_gate,
        "test_rows": test_rows,
        "ready_to_promote": ready,
        "copied_to_live": False,
        "promote_reason": (
            "walk_forward_gate_passed" if ready else "walk_forward_gate_failed"
        ),
    }
    _print_stage_frame("Barrier compare", barrier_rows)
    _print_stage_frame("Test once", test_rows)
    print("winner_barrier", winner_id)
    print("xgb_winner_gate", winner_gate, "mlp_test_gate", mlp_gate)
    print("ready_to_promote", ready, "copied_to_live", False)

    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "policy.json").write_text(
        json.dumps(_json_sanitize(payload), indent=2),
        encoding="utf-8",
    )
    print("wrote", export_dir / "policy.json")
    return payload


def run_policy_and_multihead(
    bars: pd.DataFrame,
    *,
    config: Mapping[str, Any],
    splits: Mapping[str, np.ndarray],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    export_dir: Path,
    inner_calibration_split: Optional[
        Callable[..., Tuple[np.ndarray, np.ndarray]]
    ] = None,
    n_estimators: Optional[int] = None,
) -> Dict[str, Any]:
    """Alias for ``run_regime_exclusive_sweep``."""
    return run_regime_exclusive_sweep(
        bars,
        config=config,
        splits=splits,
        wf_folds=wf_folds,
        export_dir=export_dir,
        inner_calibration_split=inner_calibration_split,
        n_estimators=n_estimators,
    )
