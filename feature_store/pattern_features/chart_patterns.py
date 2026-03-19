"""
Chart pattern detection for ML features.

Detects support/resistance, trendlines, flags, triangles, reversals, and breakouts.
Produces ML-ready feature columns aligned with input DataFrame index.
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from scipy.stats import linregress

# Feature names for registration
CHART_PATTERN_FEATURES = [
    "sr_support_dist_pct",
    "sr_resistance_dist_pct",
    "sr_at_support",
    "sr_at_resistance",
    "sr_support_strength",
    "sr_resistance_strength",
    "sr_range_position",
    "tl_uptrend_detected",
    "tl_downtrend_detected",
    "tl_trend_slope",
    "tl_dist_to_trendline",
    "tl_near_trendline",
    "tl_breakout_up",
    "tl_breakout_down",
    "chp_bull_flag",
    "chp_bear_flag",
    "chp_bull_flag_strength",
    "chp_bear_flag_strength",
    "chp_asc_triangle",
    "chp_desc_triangle",
    "chp_sym_triangle",
    "chp_triangle_apex_dist",
    "chp_double_top",
    "chp_double_bottom",
    "chp_double_top_dist",
    "chp_double_bottom_dist",
    "chp_hs_detected",
    "chp_ihs_detected",
    "bo_at_high",
    "bo_at_low",
    "bo_volume_confirmation",
    "bo_breakout_score",
]


class ChartPatternEngine:
    """
    Detects chart patterns and computes structural market features.
    All methods return full-length DataFrames aligned with input index.
    """

    def compute_all(self, df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
        """Main entry point — computes all chart pattern features."""
        atr = self._compute_atr(df, atr_period)
        out = pd.DataFrame(index=df.index)

        sr = self._compute_support_resistance(df, atr)
        out = pd.concat([out, sr], axis=1)

        tl = self._compute_trendlines(df, atr)
        out = pd.concat([out, tl], axis=1)

        flags = self._compute_flags(df, atr)
        out = pd.concat([out, flags], axis=1)

        tri = self._compute_triangles(df, atr)
        out = pd.concat([out, tri], axis=1)

        rev = self._compute_reversal_patterns(df, atr)
        out = pd.concat([out, rev], axis=1)

        bo = self._compute_breakouts(df, atr)
        out = pd.concat([out, bo], axis=1)

        return out.fillna(0)

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _compute_support_resistance(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        window: int = 5,
        lookback: int = 60,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        high_idx = argrelextrema(highs, np.greater, order=window)[0]
        low_idx = argrelextrema(lows, np.less, order=window)[0]

        sr_support_dist = np.full(len(df), np.nan)
        sr_resistance_dist = np.full(len(df), np.nan)
        sr_at_support = np.zeros(len(df))
        sr_at_resistance = np.zeros(len(df))
        sr_support_strength = np.zeros(len(df))
        sr_resistance_strength = np.zeros(len(df))
        sr_range_position = np.full(len(df), 0.5)

        for i in range(lookback, len(df)):
            current_price = closes[i]
            current_atr = (
                atr.iloc[i] if not np.isnan(atr.iloc[i]) else current_price * 0.01
            )

            recent_highs_idx = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            recent_lows_idx = low_idx[(low_idx >= i - lookback) & (low_idx < i)]

            if len(recent_highs_idx) > 0:
                resistance_levels = highs[recent_highs_idx]
                above = resistance_levels[resistance_levels > current_price]
                if len(above) > 0:
                    nearest_res = above.min()
                    sr_resistance_dist[i] = (
                        (nearest_res - current_price) / current_price * 100
                    )
                    sr_at_resistance[i] = (
                        1 if abs(nearest_res - current_price) < current_atr else 0
                    )
                    sr_resistance_strength[i] = np.sum(
                        np.abs(resistance_levels - nearest_res) < current_atr * 0.5
                    )

            if len(recent_lows_idx) > 0:
                support_levels = lows[recent_lows_idx]
                below = support_levels[support_levels < current_price]
                if len(below) > 0:
                    nearest_sup = below.max()
                    sr_support_dist[i] = (
                        (current_price - nearest_sup) / current_price * 100
                    )
                    sr_at_support[i] = (
                        1 if abs(current_price - nearest_sup) < current_atr else 0
                    )
                    sr_support_strength[i] = np.sum(
                        np.abs(support_levels - nearest_sup) < current_atr * 0.5
                    )

            sup_d = sr_support_dist[i] if not np.isnan(sr_support_dist[i]) else 0
            res_d = sr_resistance_dist[i] if not np.isnan(sr_resistance_dist[i]) else 0
            total = sup_d + res_d
            if total > 0:
                sr_range_position[i] = res_d / total

        out["sr_support_dist_pct"] = sr_support_dist
        out["sr_resistance_dist_pct"] = sr_resistance_dist
        out["sr_at_support"] = sr_at_support
        out["sr_at_resistance"] = sr_at_resistance
        out["sr_support_strength"] = sr_support_strength
        out["sr_resistance_strength"] = sr_resistance_strength
        out["sr_range_position"] = sr_range_position

        return out

    def _compute_trendlines(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        min_touches: int = 3,
        lookback: int = 50,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        high_idx = argrelextrema(highs, np.greater, order=5)[0]
        low_idx = argrelextrema(lows, np.less, order=5)[0]

        tl_uptrend = np.zeros(len(df))
        tl_downtrend = np.zeros(len(df))
        tl_slope = np.zeros(len(df))
        tl_dist = np.zeros(len(df))
        tl_near = np.zeros(len(df))
        tl_break_up = np.zeros(len(df))
        tl_break_down = np.zeros(len(df))

        for i in range(lookback, len(df)):
            current_atr = (
                float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i] * 0.01
            )

            ul_idx = low_idx[(low_idx >= i - lookback) & (low_idx < i)]
            if len(ul_idx) >= min_touches:
                x = ul_idx.astype(float)
                y = lows[ul_idx]
                slope, intercept, r, _, _ = linregress(x, y)
                if slope > 0 and r > 0.7:
                    tl_uptrend[i] = 1
                    trendline_val = slope * i + intercept
                    dist = (closes[i] - trendline_val) / current_atr
                    tl_slope[i] = slope / (closes[i] * 0.0001)
                    tl_dist[i] = max(0, dist)
                    tl_near[i] = 1 if abs(dist) < 1.0 else 0
                    if closes[i] < trendline_val and closes[i - 1] >= (
                        slope * (i - 1) + intercept
                    ):
                        tl_break_down[i] = 1

            dl_idx = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            if len(dl_idx) >= min_touches:
                x = dl_idx.astype(float)
                y = highs[dl_idx]
                slope, intercept, r, _, _ = linregress(x, y)
                if slope < 0 and r > 0.7:
                    tl_downtrend[i] = 1
                    trendline_val = slope * i + intercept
                    if closes[i] > trendline_val and closes[i - 1] <= (
                        slope * (i - 1) + intercept
                    ):
                        tl_break_up[i] = 1

        out["tl_uptrend_detected"] = tl_uptrend
        out["tl_downtrend_detected"] = tl_downtrend
        out["tl_trend_slope"] = tl_slope
        out["tl_dist_to_trendline"] = tl_dist
        out["tl_near_trendline"] = tl_near
        out["tl_breakout_up"] = tl_break_up
        out["tl_breakout_down"] = tl_break_down

        return out

    def _compute_flags(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        pole_bars: int = 10,
        flag_bars: int = 20,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        closes = df["close"].values
        n = len(df)

        bull_flag = np.zeros(n)
        bear_flag = np.zeros(n)
        bull_flag_strength = np.zeros(n)
        bear_flag_strength = np.zeros(n)

        for i in range(pole_bars + flag_bars, n):
            current_atr = (
                float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i] * 0.01
            )

            pole_start = i - pole_bars - flag_bars
            pole_end = i - flag_bars
            pole_move = closes[pole_end] - closes[pole_start]
            pole_magnitude = abs(pole_move) / (current_atr * pole_bars)

            if pole_magnitude > 0.5:
                flag_closes = closes[pole_end:i]
                flag_range = np.max(flag_closes) - np.min(flag_closes)
                flag_drift = closes[i - 1] - closes[pole_end]

                if pole_move > 0:
                    if flag_range < abs(pole_move) * 0.5 and flag_drift < 0:
                        bull_flag[i] = 1
                        bull_flag_strength[i] = pole_magnitude
                else:
                    if flag_range < abs(pole_move) * 0.5 and flag_drift > 0:
                        bear_flag[i] = 1
                        bear_flag_strength[i] = pole_magnitude

        out["chp_bull_flag"] = bull_flag
        out["chp_bear_flag"] = bear_flag
        out["chp_bull_flag_strength"] = bull_flag_strength
        out["chp_bear_flag_strength"] = bear_flag_strength

        return out

    def _compute_triangles(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        lookback: int = 40,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        asc_tri = np.zeros(n)
        desc_tri = np.zeros(n)
        sym_tri = np.zeros(n)
        apex_dist = np.zeros(n)

        for i in range(lookback, n):
            window_highs = highs[i - lookback : i]
            window_lows = lows[i - lookback : i]
            x = np.arange(lookback, dtype=float)

            slope_h, _, _, _, _ = linregress(x, window_highs)
            slope_l, _, _, _, _ = linregress(x, window_lows)

            atr_val = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else highs[i] * 0.01

            if abs(slope_h) < 0.1 * atr_val and slope_l > 0:
                asc_tri[i] = 1
            elif slope_h < 0 and abs(slope_l) < 0.1 * atr_val:
                desc_tri[i] = 1
            elif slope_h < 0 and slope_l > 0:
                sym_tri[i] = 1
                price_range = window_highs[-1] - window_lows[-1]
                if abs(slope_h - slope_l) > 1e-10:
                    bars_to_apex = price_range / abs(slope_h - slope_l)
                    apex_dist[i] = bars_to_apex / lookback

        out["chp_asc_triangle"] = asc_tri
        out["chp_desc_triangle"] = desc_tri
        out["chp_sym_triangle"] = sym_tri
        out["chp_triangle_apex_dist"] = apex_dist

        return out

    def _compute_reversal_patterns(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        lookback: int = 60,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        n = len(df)

        double_top = np.zeros(n)
        double_bottom = np.zeros(n)
        double_top_dist = np.zeros(n)
        double_bottom_dist = np.zeros(n)
        hs_detected = np.zeros(n)
        ihs_detected = np.zeros(n)

        high_idx = argrelextrema(highs, np.greater, order=5)[0]
        low_idx = argrelextrema(lows, np.less, order=5)[0]

        for i in range(lookback, n):
            current_atr = (
                float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i] * 0.01
            )

            recent_hi = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            if len(recent_hi) >= 2:
                h1, h2 = highs[recent_hi[-2]], highs[recent_hi[-1]]
                separation = recent_hi[-1] - recent_hi[-2]
                if abs(h1 - h2) < current_atr * 0.5 and 5 <= separation <= lookback // 2:
                    double_top[i] = 1
                    double_top_dist[i] = (closes[i] - min(h1, h2)) / current_atr

            recent_lo = low_idx[(low_idx >= i - lookback) & (low_idx < i)]
            if len(recent_lo) >= 2:
                l1, l2 = lows[recent_lo[-2]], lows[recent_lo[-1]]
                separation = recent_lo[-1] - recent_lo[-2]
                if abs(l1 - l2) < current_atr * 0.5 and 5 <= separation <= lookback // 2:
                    double_bottom[i] = 1
                    double_bottom_dist[i] = (max(l1, l2) - closes[i]) / current_atr

            if len(recent_hi) >= 3:
                p1, p2, p3 = (
                    highs[recent_hi[-3]],
                    highs[recent_hi[-2]],
                    highs[recent_hi[-1]],
                )
                if p2 > p1 and p2 > p3 and abs(p1 - p3) < current_atr:
                    hs_detected[i] = 1

            if len(recent_lo) >= 3:
                t1, t2, t3 = (
                    lows[recent_lo[-3]],
                    lows[recent_lo[-2]],
                    lows[recent_lo[-1]],
                )
                if t2 < t1 and t2 < t3 and abs(t1 - t3) < current_atr:
                    ihs_detected[i] = 1

        out["chp_double_top"] = double_top
        out["chp_double_bottom"] = double_bottom
        out["chp_double_top_dist"] = double_top_dist
        out["chp_double_bottom_dist"] = double_bottom_dist
        out["chp_hs_detected"] = hs_detected
        out["chp_ihs_detected"] = ihs_detected

        return out

    def _compute_breakouts(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        lookback: int = 20,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        closes = df["close"].values
        n = len(df)

        bo_at_high = np.zeros(n)
        bo_at_low = np.zeros(n)
        bo_volume_conf = np.zeros(n)
        bo_score = np.zeros(n)

        for i in range(lookback, n):
            window_closes = closes[i - lookback : i]
            range_high = np.max(window_closes)
            range_low = np.min(window_closes)
            current = closes[i]
            current_atr = (
                float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else current * 0.01
            )

            if current >= range_high - current_atr * 0.3:
                bo_at_high[i] = 1

            if current <= range_low + current_atr * 0.3:
                bo_at_low[i] = 1

            if "volume" in df.columns:
                vol = df["volume"].values
                avg_vol = np.mean(vol[i - lookback : i])
                if vol[i] > avg_vol * 1.5:
                    bo_volume_conf[i] = 1

            bo_score[i] = float(bo_at_high[i]) * 0.5 + float(bo_volume_conf[i]) * 0.5

        out["bo_at_high"] = bo_at_high
        out["bo_at_low"] = bo_at_low
        out["bo_volume_confirmation"] = bo_volume_conf
        out["bo_breakout_score"] = bo_score

        return out
