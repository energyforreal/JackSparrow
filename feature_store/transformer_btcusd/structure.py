"""Causal OHLCV market-structure and chart-geometry features.

All values at bar t use information available at or before t. Swings are ATR
ZigZag confirmations (not future-looking fractals). Donchian/breakout ranges
exclude bar t. Higher-TF context is merged from fully closed resampled bars.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Tuple

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    CHART_PATTERN_COL,
    HTF_FEATURE_FIELDS,
    HTF_SOURCE_TFS,
    HTF_STRUCTURE_COLS,
    NATIVE_STRUCTURE_COLS,
    RESOLUTION_MINUTES,
)

_EPS = 1e-9
_ATR_CLIP = 8.0
_SLOPE_CLIP = 2.0
_ZZ_TAU = 1.5
_ZZ_EVENT_M = 6
_ZZ_EPS_ATR = 0.15
_SWING_K = 20
_ER_N = 32
_SLOPE_LAG = 8
_DONCHIAN_N = 32
_RANGE_PCTILE_W = 256
_TOUCH_W = 64
_SR_DELTA_ATR = 0.5
_POLE_BARS = 12
_FLAG_BARS = 16
_BREAKOUT_THRESH = 0.25
_FAILED_BREAK_BARS = 8
_CHANNEL_K = 3
_ATR_SHORT = 14
_ATR_LONG = 56
_HTF_NATIVE_MINUTES = 5

_HTF_NATIVE_MAP = {
    "structure_bias": "structure_bias",
    "trend_efficiency": "trend_efficiency",
    "ema21_slope_atr": "ema21_slope_atr",
    "dist_support_atr": "dist_to_support_atr",
    "dist_resistance_atr": "dist_to_resistance_atr",
    "range_width_atr": "range_width_atr",
}


def _safe_atr(atr: np.ndarray, close: np.ndarray, i: int) -> float:
    val = float(atr[i]) if np.isfinite(atr[i]) else float("nan")
    if not np.isfinite(val) or val <= 0:
        c = float(close[i]) if np.isfinite(close[i]) else 0.0
        return max(abs(c) * 0.01, _EPS)
    return val


def _clip_atr(val: float) -> float:
    if not np.isfinite(val):
        return 0.0
    return float(np.clip(val, -_ATR_CLIP, _ATR_CLIP))


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    n = float(len(x))
    if n < 2:
        return 0.0
    sx = float(x.sum())
    sy = float(y.sum())
    sxy = float((x * y).sum())
    sx2 = float((x * x).sum())
    den = n * sx2 - sx * sx
    if abs(den) < 1e-12:
        return 0.0
    return float((n * sxy - sx * sy) / den)


def _ensure_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    if "atr" in out.columns and out["atr"].notna().any():
        return out
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(period, min_periods=1).mean()
    return out


def _vectorized_trend_and_ma(out: pd.DataFrame) -> pd.DataFrame:
    """ER, displacement, MA distances/slopes, Donchian compression, flag geometry."""
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    volume = out["volume"].astype(float) if "volume" in out.columns else pd.Series(
        0.0, index=out.index
    )
    atr = out["atr"].astype(float) if "atr" in out.columns else pd.Series(
        close.abs() * 0.01, index=out.index
    )
    atr_safe = atr.replace(0, np.nan).fillna(close.abs() * 0.01 + _EPS)

    abs_move = (close - close.shift(_ER_N)).abs()
    path = close.diff().abs().rolling(_ER_N, min_periods=2).sum()
    out["trend_efficiency"] = (abs_move / (path + _EPS)).clip(0.0, 1.0).fillna(0.0)
    out["displacement_atr"] = (abs_move / (atr_safe + _EPS)).clip(
        0.0, _ATR_CLIP
    ).fillna(0.0)

    window_dir = np.sign(close - close.shift(_ER_N))
    up_frac = (close.diff() > 0).astype(float).rolling(_ER_N, min_periods=1).mean()
    pct = np.where(window_dir >= 0, up_frac, 1.0 - up_frac)
    out["pct_with_trend"] = pd.Series(pct, index=out.index).fillna(0.0)

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    out["price_vs_ema9_atr"] = ((close - ema9) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["price_vs_ema21_atr"] = ((close - ema21) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["price_vs_ema50_atr"] = ((close - ema50) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["price_vs_ema200_atr"] = ((close - ema200) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["ema9_vs_21_atr"] = ((ema9 - ema21) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["ema21_vs_50_atr"] = ((ema21 - ema50) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    out["ema50_vs_200_atr"] = ((ema50 - ema200) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    )
    lag = float(_SLOPE_LAG)
    out["ema21_slope_atr"] = (
        (ema21 - ema21.shift(_SLOPE_LAG)) / (atr_safe * lag + _EPS)
    ).clip(-_SLOPE_CLIP, _SLOPE_CLIP).fillna(0.0)
    out["ema50_slope_atr"] = (
        (ema50 - ema50.shift(_SLOPE_LAG)) / (atr_safe * lag + _EPS)
    ).clip(-_SLOPE_CLIP, _SLOPE_CLIP).fillna(0.0)

    prior_high = high.shift(1)
    prior_low = low.shift(1)
    donch_high = prior_high.rolling(_DONCHIAN_N, min_periods=1).max()
    donch_low = prior_low.rolling(_DONCHIAN_N, min_periods=1).min()
    range_width_atr = ((donch_high - donch_low) / (atr_safe + _EPS)).clip(
        0.0, _ATR_CLIP
    )
    out["range_width_atr"] = range_width_atr.fillna(0.0)
    out["range_width_pctile"] = range_width_atr.rolling(
        _RANGE_PCTILE_W, min_periods=8
    ).rank(pct=True).fillna(0.0)
    atr_short = atr_safe.rolling(_ATR_SHORT, min_periods=1).mean()
    atr_long = atr_safe.rolling(_ATR_LONG, min_periods=1).mean()
    out["atr_contraction"] = (atr_short / (atr_long + _EPS)).clip(0.0, _ATR_CLIP).fillna(
        1.0
    )

    out["breakout_size_atr"] = ((close - donch_high) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    ).fillna(0.0)
    vol_mean = volume.shift(1).rolling(_DONCHIAN_N, min_periods=1).mean()
    out["breakout_vol_ratio"] = (volume / (vol_mean + _EPS)).clip(0.0, _ATR_CLIP).fillna(
        0.0
    )
    out["pre_breakout_comp"] = out["range_width_pctile"].shift(1).fillna(0.0)

    pole_end = close.shift(_FLAG_BARS)
    pole_start = close.shift(_POLE_BARS + _FLAG_BARS)
    out["pole_disp_atr"] = ((pole_end - pole_start) / (atr_safe + _EPS)).clip(
        -_ATR_CLIP, _ATR_CLIP
    ).fillna(0.0)
    flag_high = high.rolling(_FLAG_BARS, min_periods=1).max()
    flag_low = low.rolling(_FLAG_BARS, min_periods=1).min()
    out["flag_width_atr"] = ((flag_high - flag_low) / (atr_safe + _EPS)).clip(
        0.0, _ATR_CLIP
    ).fillna(0.0)
    flag_lag = float(_FLAG_BARS)
    out["flag_slope_atr"] = (
        (close - close.shift(_FLAG_BARS)) / (atr_safe * flag_lag + _EPS)
    ).clip(-_SLOPE_CLIP, _SLOPE_CLIP).fillna(0.0)
    return out


def _zigzag_structure_loop(out: pd.DataFrame) -> pd.DataFrame:
    """Single-pass ATR ZigZag: HH/HL counts, S/R, breakout events, pattern geometry."""
    n = len(out)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    close = out["close"].to_numpy(dtype=np.float64)
    atr = out["atr"].to_numpy(dtype=np.float64) if "atr" in out.columns else np.full(
        n, np.nan
    )
    prior_high = np.roll(high, 1)
    prior_high[0] = high[0]
    prior_low = np.roll(low, 1)
    prior_low[0] = low[0]
    donch_h = np.empty(n, dtype=np.float64)
    donch_l = np.empty(n, dtype=np.float64)
    max_q: Deque[int] = deque()
    min_q: Deque[int] = deque()
    for t in range(n):
        left = t - _DONCHIAN_N
        while max_q and max_q[0] <= left:
            max_q.popleft()
        while min_q and min_q[0] <= left:
            min_q.popleft()
        src_h = prior_high[t]
        src_l = prior_low[t]
        while max_q and prior_high[max_q[-1]] <= src_h:
            max_q.pop()
        while min_q and prior_low[min_q[-1]] >= src_l:
            min_q.pop()
        max_q.append(t)
        min_q.append(t)
        donch_h[t] = prior_high[max_q[0]]
        donch_l[t] = prior_low[min_q[0]]

    hh_count = np.zeros(n, dtype=np.float64)
    hl_count = np.zeros(n, dtype=np.float64)
    lh_count = np.zeros(n, dtype=np.float64)
    ll_count = np.zeros(n, dtype=np.float64)
    structure_bias = np.zeros(n, dtype=np.float64)
    last_swing_dir = np.zeros(n, dtype=np.float64)
    bars_since_swing = np.zeros(n, dtype=np.float64)
    swing_amp_atr = np.zeros(n, dtype=np.float64)
    unconfirmed_ext_atr = np.zeros(n, dtype=np.float64)
    dist_to_support_atr = np.zeros(n, dtype=np.float64)
    dist_to_resistance_atr = np.zeros(n, dtype=np.float64)
    support_touch = np.zeros(n, dtype=np.float64)
    resistance_touch = np.zeros(n, dtype=np.float64)
    bars_since_breakout = np.zeros(n, dtype=np.float64)
    retest_dist_atr = np.zeros(n, dtype=np.float64)
    failed_break = np.zeros(n, dtype=np.float64)
    peak_diff_atr = np.zeros(n, dtype=np.float64)
    trough_diff_atr = np.zeros(n, dtype=np.float64)
    peak_sep_bars = np.zeros(n, dtype=np.float64)
    trough_sep_bars = np.zeros(n, dtype=np.float64)
    dist_neck_atr = np.zeros(n, dtype=np.float64)
    high_slope_atr = np.zeros(n, dtype=np.float64)
    low_slope_atr = np.zeros(n, dtype=np.float64)
    convergence = np.zeros(n, dtype=np.float64)
    width_now_atr = np.zeros(n, dtype=np.float64)

    direction = 1
    e_idx = 0
    e_price = high[0] if n else 0.0
    last_high_price = float("nan")
    last_low_price = float("nan")
    last_high_idx = -1
    last_low_idx = -1
    last_swing_idx = -1
    last_dir = 0.0
    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []
    events: Deque[str] = deque(maxlen=_ZZ_EVENT_M)
    last_bo_idx = -1
    last_bo_level = float("nan")
    last_bo_side = 0

    for t in range(n):
        atr_t = _safe_atr(atr, close, t)
        thresh = _ZZ_TAU * atr_t
        eps = _ZZ_EPS_ATR * atr_t

        if direction == 1:
            if high[t] >= e_price:
                e_price = high[t]
                e_idx = t
            elif (e_price - low[t]) >= thresh:
                highs.append((e_idx, e_price))
                if len(highs) > _SWING_K:
                    highs = highs[-_SWING_K:]
                if np.isfinite(last_high_price):
                    if e_price > last_high_price + eps:
                        events.append("HH")
                    elif e_price < last_high_price - eps:
                        events.append("LH")
                last_high_price = e_price
                last_high_idx = e_idx
                last_swing_idx = e_idx
                last_dir = 1.0
                direction = -1
                e_price = low[t]
                e_idx = t
        else:
            if low[t] <= e_price:
                e_price = low[t]
                e_idx = t
            elif (high[t] - e_price) >= thresh:
                lows.append((e_idx, e_price))
                if len(lows) > _SWING_K:
                    lows = lows[-_SWING_K:]
                if np.isfinite(last_low_price):
                    if e_price > last_low_price + eps:
                        events.append("HL")
                    elif e_price < last_low_price - eps:
                        events.append("LL")
                last_low_price = e_price
                last_low_idx = e_idx
                last_swing_idx = e_idx
                last_dir = -1.0
                direction = 1
                e_price = high[t]
                e_idx = t

        n_hh = sum(1 for e in events if e == "HH")
        n_hl = sum(1 for e in events if e == "HL")
        n_lh = sum(1 for e in events if e == "LH")
        n_ll = sum(1 for e in events if e == "LL")
        n_ev = max(len(events), 1)
        hh_count[t] = float(n_hh)
        hl_count[t] = float(n_hl)
        lh_count[t] = float(n_lh)
        ll_count[t] = float(n_ll)
        structure_bias[t] = (n_hh + n_hl - n_lh - n_ll) / float(n_ev)
        last_swing_dir[t] = last_dir
        bars_since_swing[t] = float(t - last_swing_idx) if last_swing_idx >= 0 else float(t)
        if np.isfinite(last_high_price) and np.isfinite(last_low_price):
            swing_amp_atr[t] = _clip_atr(abs(last_high_price - last_low_price) / atr_t)
        unconfirmed_ext_atr[t] = _clip_atr((e_price - close[t]) / atr_t)

        swing_lows = [p for _, p in lows if p <= close[t]]
        swing_highs = [p for _, p in highs if p >= close[t]]
        support = max(swing_lows) if swing_lows else float(donch_l[t])
        resistance = min(swing_highs) if swing_highs else float(donch_h[t])
        dist_to_support_atr[t] = _clip_atr((close[t] - support) / atr_t)
        dist_to_resistance_atr[t] = _clip_atr((resistance - close[t]) / atr_t)
        delta = _SR_DELTA_ATR * atr_t
        if low[t] <= support + delta and close[t] >= support - delta:
            support_touch[t] = 1.0
        if high[t] >= resistance - delta and close[t] <= resistance + delta:
            resistance_touch[t] = 1.0

        bo_size = (close[t] - donch_h[t]) / atr_t
        if abs(bo_size) >= _BREAKOUT_THRESH:
            last_bo_idx = t
            last_bo_level = float(donch_h[t] if bo_size > 0 else donch_l[t])
            last_bo_side = 1 if bo_size > 0 else -1
        if last_bo_idx >= 0:
            bars_since_breakout[t] = float(t - last_bo_idx)
            retest_dist_atr[t] = _clip_atr((close[t] - last_bo_level) / atr_t)
            if last_bo_side > 0 and close[t] < last_bo_level:
                failed_break[t] = 1.0
            elif last_bo_side < 0 and close[t] > last_bo_level:
                failed_break[t] = 1.0
        else:
            bars_since_breakout[t] = float(t)

        if len(highs) >= 2:
            (i1, p1), (i2, p2) = highs[-2], highs[-1]
            peak_diff_atr[t] = _clip_atr((p2 - p1) / atr_t)
            peak_sep_bars[t] = float(i2 - i1)
            between = [lp for li, lp in lows if i1 < li < i2]
            if between:
                neck = min(between)
                dist_neck_atr[t] = _clip_atr((close[t] - neck) / atr_t)
        if len(lows) >= 2:
            (j1, q1), (j2, q2) = lows[-2], lows[-1]
            trough_diff_atr[t] = _clip_atr((q2 - q1) / atr_t)
            trough_sep_bars[t] = float(j2 - j1)

        if len(highs) >= _CHANNEL_K:
            hx = np.array([idx for idx, _ in highs[-_CHANNEL_K:]], dtype=np.float64)
            hy = np.array([px for _, px in highs[-_CHANNEL_K:]], dtype=np.float64)
            hs = _ols_slope(hx, hy)
            high_slope_atr[t] = float(np.clip(hs / atr_t, -_SLOPE_CLIP, _SLOPE_CLIP))
        if len(lows) >= _CHANNEL_K:
            lx = np.array([idx for idx, _ in lows[-_CHANNEL_K:]], dtype=np.float64)
            ly = np.array([px for _, px in lows[-_CHANNEL_K:]], dtype=np.float64)
            ls = _ols_slope(lx, ly)
            low_slope_atr[t] = float(np.clip(ls / atr_t, -_SLOPE_CLIP, _SLOPE_CLIP))
        convergence[t] = float(
            np.clip(high_slope_atr[t] - low_slope_atr[t], -_SLOPE_CLIP, _SLOPE_CLIP)
        )
        if len(highs) >= 1 and len(lows) >= 1:
            h_line = highs[-1][1] + high_slope_atr[t] * atr_t * (t - highs[-1][0])
            l_line = lows[-1][1] + low_slope_atr[t] * atr_t * (t - lows[-1][0])
            width_now_atr[t] = _clip_atr((h_line - l_line) / atr_t)

    touch_sup = pd.Series(support_touch).rolling(_TOUCH_W, min_periods=1).sum()
    touch_res = pd.Series(resistance_touch).rolling(_TOUCH_W, min_periods=1).sum()

    out["hh_count"] = hh_count
    out["hl_count"] = hl_count
    out["lh_count"] = lh_count
    out["ll_count"] = ll_count
    out["structure_bias"] = structure_bias
    out["last_swing_dir"] = last_swing_dir
    out["bars_since_swing"] = bars_since_swing
    out["swing_amp_atr"] = swing_amp_atr
    out["unconfirmed_ext_atr"] = unconfirmed_ext_atr
    out["dist_to_support_atr"] = dist_to_support_atr
    out["dist_to_resistance_atr"] = dist_to_resistance_atr
    out["support_touch_count"] = touch_sup.to_numpy(dtype=np.float64)
    out["resistance_touch_count"] = touch_res.to_numpy(dtype=np.float64)
    out["bars_since_breakout"] = bars_since_breakout
    out["retest_dist_atr"] = retest_dist_atr
    out["failed_break"] = failed_break
    out["peak_diff_atr"] = peak_diff_atr
    out["trough_diff_atr"] = trough_diff_atr
    out["peak_sep_bars"] = peak_sep_bars
    out["trough_sep_bars"] = trough_sep_bars
    out["dist_neck_atr"] = dist_neck_atr
    out["high_slope_atr"] = high_slope_atr
    out["low_slope_atr"] = low_slope_atr
    out["convergence"] = convergence
    out["width_now_atr"] = width_now_atr
    out[CHART_PATTERN_COL] = _chart_pattern_ids(
        failed_break=failed_break,
        bars_since_breakout=bars_since_breakout,
        breakout_size_atr=(
            out["breakout_size_atr"].to_numpy(dtype=np.float64)
            if "breakout_size_atr" in out.columns
            else np.zeros(n)
        ),
        peak_diff_atr=peak_diff_atr,
        trough_diff_atr=trough_diff_atr,
        peak_sep_bars=peak_sep_bars,
        trough_sep_bars=trough_sep_bars,
        dist_neck_atr=dist_neck_atr,
        high_slope_atr=high_slope_atr,
        low_slope_atr=low_slope_atr,
        convergence=convergence,
        width_now_atr=width_now_atr,
        pole_disp_atr=(
            out["pole_disp_atr"].to_numpy(dtype=np.float64)
            if "pole_disp_atr" in out.columns
            else np.zeros(n)
        ),
        flag_width_atr=(
            out["flag_width_atr"].to_numpy(dtype=np.float64)
            if "flag_width_atr" in out.columns
            else np.zeros(n)
        ),
        flag_slope_atr=(
            out["flag_slope_atr"].to_numpy(dtype=np.float64)
            if "flag_slope_atr" in out.columns
            else np.zeros(n)
        ),
        structure_bias=structure_bias,
    )
    return out


def _chart_pattern_ids(
    *,
    failed_break: np.ndarray,
    bars_since_breakout: np.ndarray,
    breakout_size_atr: np.ndarray,
    peak_diff_atr: np.ndarray,
    trough_diff_atr: np.ndarray,
    peak_sep_bars: np.ndarray,
    trough_sep_bars: np.ndarray,
    dist_neck_atr: np.ndarray,
    high_slope_atr: np.ndarray,
    low_slope_atr: np.ndarray,
    convergence: np.ndarray,
    width_now_atr: np.ndarray,
    pole_disp_atr: np.ndarray,
    flag_width_atr: np.ndarray,
    flag_slope_atr: np.ndarray,
    structure_bias: np.ndarray,
) -> np.ndarray:
    """Causal discrete chart-pattern id at bar t (0=NONE ... 8=FAILED_BREAK).

    FAILED_BREAK is a rising-edge event inside ``_FAILED_BREAK_BARS`` of the
    last Donchian breakout. It does not overwrite FLAG/TRIANGLE/DOUBLE/CHANNEL
    and does not stay on for the whole post-breakout regime.
    """
    n = int(failed_break.shape[0])
    ids = np.zeros(n, dtype=np.int64)
    channel = (np.abs(high_slope_atr - low_slope_atr) < 0.15) & (width_now_atr > 0.6)
    triangle = (np.abs(convergence) >= 0.08) & (width_now_atr < 2.5)
    double_top = (
        (np.abs(peak_diff_atr) < 0.45)
        & (peak_sep_bars >= 4)
        & (dist_neck_atr > 0.15)
    )
    double_bottom = (
        (np.abs(trough_diff_atr) < 0.45)
        & (trough_sep_bars >= 4)
        & (dist_neck_atr < -0.15)
    )
    flag_bull = (
        (pole_disp_atr > 1.0)
        & (flag_width_atr < 2.0)
        & (flag_slope_atr < 0.0)
        & (structure_bias > 0.15)
    )
    flag_bear = (
        (pole_disp_atr < -1.0)
        & (flag_width_atr < 2.0)
        & (flag_slope_atr > 0.0)
        & (structure_bias < -0.15)
    )
    breakout = (bars_since_breakout <= 2.0) & (np.abs(breakout_size_atr) >= 0.25)
    failed_now = (failed_break >= 0.5) & (
        bars_since_breakout <= float(_FAILED_BREAK_BARS)
    )
    failed_prev = np.empty_like(failed_now)
    failed_prev[0] = False
    if n > 1:
        failed_prev[1:] = failed_now[:-1]
    failed_pulse = failed_now & ~failed_prev
    ids = np.where(channel, 6, ids)
    ids = np.where(triangle, 3, ids)
    ids = np.where(flag_bull, 1, ids)
    ids = np.where(flag_bear, 2, ids)
    ids = np.where(double_bottom, 5, ids)
    ids = np.where(double_top, 4, ids)
    ids = np.where(breakout, 7, ids)
    named = np.isin(ids, [1, 2, 3, 4, 5, 6])
    ids = np.where(failed_pulse & ~named, 8, ids)
    return ids


def add_market_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add causal native-TF structure, trend, S/R, breakout, and geometry columns.

    Args:
        df: OHLCV frame with atr (computed if missing).

    Returns:
        Same frame with ``NATIVE_STRUCTURE_COLS`` assigned and finite-filled.
    """
    out = _ensure_atr(df)
    out = _vectorized_trend_and_ma(out)
    out = _zigzag_structure_loop(out)
    for col in NATIVE_STRUCTURE_COLS:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = out[col].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if CHART_PATTERN_COL not in out.columns:
        out[CHART_PATTERN_COL] = 0
    out[CHART_PATTERN_COL] = (
        pd.to_numeric(out[CHART_PATTERN_COL], errors="coerce").fillna(0).astype(np.int64)
    )
    return out


def _resample_closed_ohlcv(
    df: pd.DataFrame,
    htf_minutes: int,
    native_minutes: int = _HTF_NATIVE_MINUTES,
) -> pd.DataFrame:
    """Resample native bars to a higher TF, keeping only complete buckets."""
    expected = max(1, int(round(htf_minutes / native_minutes)))
    src = df[["time", "open", "high", "low", "close"]].copy()
    if "volume" in df.columns:
        src["volume"] = df["volume"]
    else:
        src["volume"] = 0.0
    src["time"] = pd.to_datetime(src["time"], utc=True)
    grouped = src.set_index("time")
    rule = f"{int(htf_minutes)}min"
    agg = grouped.resample(rule, label="right", closed="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    counts = grouped["close"].resample(rule, label="right", closed="right").count()
    complete = agg.loc[counts >= expected].dropna(subset=["open", "high", "low", "close"])
    if complete.empty:
        return complete
    complete = complete.reset_index()
    return complete


def add_htf_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Merge closed 15m/30m/1h/2h structure onto a 5m frame (backward asof)."""
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out = out.sort_values("time").reset_index(drop=True)

    for tf_name in HTF_SOURCE_TFS:
        minutes = RESOLUTION_MINUTES[tf_name]
        htf_raw = _resample_closed_ohlcv(out, minutes, _HTF_NATIVE_MINUTES)
        prefixed = {f"htf_{tf_name}_{field}": 0.0 for field in HTF_FEATURE_FIELDS}
        if htf_raw.empty:
            for col, val in prefixed.items():
                out[col] = val
            continue
        htf_feat = add_market_structure_features(_ensure_atr(htf_raw))
        merge_cols = {"time": htf_feat["time"]}
        for field in HTF_FEATURE_FIELDS:
            src = _HTF_NATIVE_MAP[field]
            merge_cols[f"htf_{tf_name}_{field}"] = htf_feat[src].to_numpy(dtype=np.float64)
        htf_df = pd.DataFrame(merge_cols).sort_values("time")
        out = pd.merge_asof(
            out.sort_values("time"),
            htf_df,
            on="time",
            direction="backward",
        )

    for col in HTF_STRUCTURE_COLS:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = out[col].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out
