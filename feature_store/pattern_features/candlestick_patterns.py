"""
Candlestick pattern detection for ML features.

Detects single-candle, two-candle, and three-candle patterns.
Produces ML-ready feature columns aligned with input DataFrame index.
"""

import pandas as pd

from feature_store.pattern_features.pattern_utils import CandleGeometry

# Feature names for registration
CANDLESTICK_FEATURES = [
    "cdl_doji",
    "cdl_long_legged_doji",
    "cdl_dragonfly_doji",
    "cdl_gravestone_doji",
    "cdl_hammer",
    "cdl_inv_hammer",
    "cdl_hanging_man",
    "cdl_shooting_star",
    "cdl_bull_marubozu",
    "cdl_bear_marubozu",
    "cdl_spinning_top",
    "cdl_bull_engulfing",
    "cdl_bear_engulfing",
    "cdl_bull_harami",
    "cdl_bear_harami",
    "cdl_piercing",
    "cdl_dark_cloud",
    "cdl_tweezer_top",
    "cdl_tweezer_bottom",
    "cdl_bull_kicker",
    "cdl_bear_kicker",
    "cdl_morning_star",
    "cdl_evening_star",
    "cdl_three_white_soldiers",
    "cdl_three_black_crows",
    "cdl_three_inside_up",
    "cdl_three_inside_down",
    "cdl_abandoned_baby_bull",
    "cdl_abandoned_baby_bear",
    "cdl_bull_score",
    "cdl_bear_score",
    "cdl_net_score",
    "cdl_reversal_signal",
    "cdl_indecision_score",
    "cdl_body_ratio",
    "cdl_upper_wick_ratio",
    "cdl_lower_wick_ratio",
    "cdl_consecutive_bull",
    "cdl_consecutive_bear",
]


class CandlestickPatternEngine:
    """
    Detects candlestick patterns and produces ML-ready feature columns.
    All methods operate on a full OHLCV DataFrame and return a feature DataFrame
    aligned by index — safe for both training (batch) and live (last-row) use.
    """

    BULL_PATTERN_WEIGHTS = {
        "cdl_hammer": 0.8,
        "cdl_dragonfly_doji": 0.6,
        "cdl_bull_engulfing": 0.95,
        "cdl_bull_harami": 0.6,
        "cdl_piercing": 0.75,
        "cdl_morning_star": 0.9,
        "cdl_three_white_soldiers": 0.85,
        "cdl_bull_marubozu": 0.7,
        "cdl_tweezer_bottom": 0.65,
        "cdl_three_inside_up": 0.7,
        "cdl_abandoned_baby_bull": 0.95,
        "cdl_bull_kicker": 0.9,
        "cdl_inv_hammer": 0.5,
    }

    BEAR_PATTERN_WEIGHTS = {
        "cdl_shooting_star": 0.8,
        "cdl_gravestone_doji": 0.6,
        "cdl_bear_engulfing": 0.95,
        "cdl_bear_harami": 0.6,
        "cdl_dark_cloud": 0.75,
        "cdl_evening_star": 0.9,
        "cdl_three_black_crows": 0.85,
        "cdl_bear_marubozu": 0.7,
        "cdl_tweezer_top": 0.65,
        "cdl_three_inside_down": 0.7,
        "cdl_abandoned_baby_bear": 0.95,
        "cdl_bear_kicker": 0.9,
        "cdl_hanging_man": 0.7,
    }

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Main entry point. Returns DataFrame of all candlestick pattern features.
        Aligned with input df index.
        """
        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        geo = list(df.apply(CandleGeometry.from_row, axis=1))
        out = pd.DataFrame(index=df.index)

        # Single-candle patterns
        out["cdl_doji"] = self._doji(df, geo)
        out["cdl_long_legged_doji"] = self._long_legged_doji(df, geo)
        out["cdl_dragonfly_doji"] = self._dragonfly_doji(df, geo)
        out["cdl_gravestone_doji"] = self._gravestone_doji(df, geo)
        out["cdl_hammer"] = self._hammer(df, geo)
        out["cdl_inv_hammer"] = self._inverted_hammer(df, geo)
        out["cdl_hanging_man"] = self._hanging_man(df, geo)
        out["cdl_shooting_star"] = self._shooting_star(df, geo)
        out["cdl_bull_marubozu"] = self._bull_marubozu(df, geo)
        out["cdl_bear_marubozu"] = self._bear_marubozu(df, geo)
        out["cdl_spinning_top"] = self._spinning_top(df, geo)

        # Two-candle patterns
        out["cdl_bull_engulfing"] = self._bull_engulfing(df, geo)
        out["cdl_bear_engulfing"] = self._bear_engulfing(df, geo)
        out["cdl_bull_harami"] = self._bull_harami(df, geo)
        out["cdl_bear_harami"] = self._bear_harami(df, geo)
        out["cdl_piercing"] = self._piercing(df, geo)
        out["cdl_dark_cloud"] = self._dark_cloud(df, geo)
        out["cdl_tweezer_top"] = self._tweezer_top(df, geo)
        out["cdl_tweezer_bottom"] = self._tweezer_bottom(df, geo)
        out["cdl_bull_kicker"] = self._bull_kicker(df, geo)
        out["cdl_bear_kicker"] = self._bear_kicker(df, geo)

        # Three-candle patterns
        out["cdl_morning_star"] = self._morning_star(df, geo)
        out["cdl_evening_star"] = self._evening_star(df, geo)
        out["cdl_three_white_soldiers"] = self._three_white_soldiers(df, geo)
        out["cdl_three_black_crows"] = self._three_black_crows(df, geo)
        out["cdl_three_inside_up"] = self._three_inside_up(df, geo)
        out["cdl_three_inside_down"] = self._three_inside_down(df, geo)
        out["cdl_abandoned_baby_bull"] = self._abandoned_baby(df, geo, direction="bull")
        out["cdl_abandoned_baby_bear"] = self._abandoned_baby(df, geo, direction="bear")

        # Composite scores
        out["cdl_bull_score"] = self._bull_composite(out)
        out["cdl_bear_score"] = self._bear_composite(out)
        out["cdl_net_score"] = out["cdl_bull_score"] - out["cdl_bear_score"]
        out["cdl_reversal_signal"] = out["cdl_net_score"].clip(-1, 1)
        out["cdl_indecision_score"] = (
            out["cdl_doji"] * 0.6
            + out["cdl_long_legged_doji"] * 0.8
            + out["cdl_spinning_top"] * 0.4
        ).clip(0, 1)

        # Raw geometry features
        out["cdl_body_ratio"] = [g.body_ratio for g in geo]
        out["cdl_upper_wick_ratio"] = [g.upper_ratio for g in geo]
        out["cdl_lower_wick_ratio"] = [g.lower_ratio for g in geo]
        out["cdl_consecutive_bull"] = self._consecutive_direction(df, direction="bull")
        out["cdl_consecutive_bear"] = self._consecutive_direction(df, direction="bear")

        return out.fillna(0)

    def _doji(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [1 if g.body_ratio < 0.10 and g.total_range > 0 else 0 for g in geo],
            index=df.index,
        )

    def _long_legged_doji(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.body_ratio < 0.10 and g.upper_ratio > 0.30 and g.lower_ratio > 0.30
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _dragonfly_doji(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.body_ratio < 0.10 and g.upper_ratio < 0.05 and g.lower_ratio > 0.60
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _gravestone_doji(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.body_ratio < 0.10 and g.lower_ratio < 0.05 and g.upper_ratio > 0.60
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _hammer(self, df: pd.DataFrame, geo: list) -> pd.Series:
        atr = df["close"].diff().abs().rolling(14).mean()
        result = []
        for i, g in enumerate(geo):
            atr_val = atr.iloc[i] if i < len(atr) else 0.0
            if pd.isna(atr_val) or atr_val <= 0:
                atr_val = df["close"].iloc[i] * 0.01
            cond = (
                g.lower_wick >= 2.0 * g.body
                and g.upper_ratio < 0.20
                and g.body_ratio > 0.05
                and g.total_range > float(atr_val) * 0.5
            )
            result.append(1 if cond else 0)
        return pd.Series(result, index=df.index)

    def _inverted_hammer(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.upper_wick >= 2.0 * g.body
                and g.lower_ratio < 0.20
                and g.body_ratio > 0.05
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _hanging_man(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.lower_wick >= 2.0 * g.body
                and g.upper_ratio < 0.20
                and g.body_ratio > 0.05
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _shooting_star(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if g.upper_wick >= 2.0 * g.body
                and g.lower_ratio < 0.20
                and g.body_ratio > 0.05
                and not g.is_bullish
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _bull_marubozu(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [1 if g.is_bullish and g.body_ratio > 0.95 else 0 for g in geo],
            index=df.index,
        )

    def _bear_marubozu(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [1 if not g.is_bullish and g.body_ratio > 0.95 else 0 for g in geo],
            index=df.index,
        )

    def _spinning_top(self, df: pd.DataFrame, geo: list) -> pd.Series:
        return pd.Series(
            [
                1
                if 0.10 < g.body_ratio < 0.40
                and g.upper_ratio > 0.20
                and g.lower_ratio > 0.20
                else 0
                for g in geo
            ],
            index=df.index,
        )

    def _bull_engulfing(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            if (
                not prev.is_bullish
                and curr.is_bullish
                and df["open"].iloc[i] <= df["close"].iloc[i - 1]
                and df["close"].iloc[i] >= df["open"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_engulfing(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            if (
                prev.is_bullish
                and not curr.is_bullish
                and df["open"].iloc[i] >= df["close"].iloc[i - 1]
                and df["close"].iloc[i] <= df["open"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bull_harami(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            if (
                not prev.is_bullish
                and curr.is_bullish
                and curr.body < prev.body * 0.5
                and df["open"].iloc[i] > df["close"].iloc[i - 1]
                and df["close"].iloc[i] < df["open"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_harami(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            if (
                prev.is_bullish
                and not curr.is_bullish
                and curr.body < prev.body * 0.5
                and df["open"].iloc[i] < df["close"].iloc[i - 1]
                and df["close"].iloc[i] > df["open"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _piercing(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            midpoint = (df["open"].iloc[i - 1] + df["close"].iloc[i - 1]) / 2
            if (
                not prev.is_bullish
                and curr.is_bullish
                and df["open"].iloc[i] < df["close"].iloc[i - 1]
                and df["close"].iloc[i] > midpoint
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _dark_cloud(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i - 1], geo[i]
            midpoint = (df["open"].iloc[i - 1] + df["close"].iloc[i - 1]) / 2
            if (
                prev.is_bullish
                and not curr.is_bullish
                and df["open"].iloc[i] > df["close"].iloc[i - 1]
                and df["close"].iloc[i] < midpoint
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _tweezer_top(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            high_diff = abs(df["high"].iloc[i] - df["high"].iloc[i - 1])
            atr = df["close"].iloc[max(0, i - 14) : i].diff().abs().mean()
            atr_val = atr if not pd.isna(atr) and atr > 0 else df["close"].iloc[i] * 0.01
            if not geo[i].is_bullish and high_diff < atr_val * 0.1:
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _tweezer_bottom(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            low_diff = abs(df["low"].iloc[i] - df["low"].iloc[i - 1])
            atr = df["close"].iloc[max(0, i - 14) : i].diff().abs().mean()
            atr_val = atr if not pd.isna(atr) and atr > 0 else df["close"].iloc[i] * 0.01
            if geo[i].is_bullish and low_diff < atr_val * 0.1:
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bull_kicker(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            if (
                not geo[i - 1].is_bullish
                and geo[i].is_bullish
                and df["open"].iloc[i] > df["open"].iloc[i - 1]
                and geo[i].body_ratio > 0.5
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_kicker(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(1, len(df)):
            if (
                geo[i - 1].is_bullish
                and not geo[i].is_bullish
                and df["open"].iloc[i] < df["open"].iloc[i - 1]
                and geo[i].body_ratio > 0.5
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _morning_star(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            mid_a = (df["open"].iloc[i - 2] + df["close"].iloc[i - 2]) / 2
            if (
                not a.is_bullish
                and a.body_ratio > 0.4
                and b.body_ratio < 0.3
                and c.is_bullish
                and df["close"].iloc[i] > mid_a
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _evening_star(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            mid_a = (df["open"].iloc[i - 2] + df["close"].iloc[i - 2]) / 2
            if (
                a.is_bullish
                and a.body_ratio > 0.4
                and b.body_ratio < 0.3
                and not c.is_bullish
                and df["close"].iloc[i] < mid_a
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_white_soldiers(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            if (
                a.is_bullish
                and b.is_bullish
                and c.is_bullish
                and df["close"].iloc[i] > df["close"].iloc[i - 1] > df["close"].iloc[i - 2]
                and a.body_ratio > 0.5
                and b.body_ratio > 0.5
                and c.body_ratio > 0.5
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_black_crows(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            if (
                not a.is_bullish
                and not b.is_bullish
                and not c.is_bullish
                and df["close"].iloc[i] < df["close"].iloc[i - 1] < df["close"].iloc[i - 2]
                and a.body_ratio > 0.5
                and b.body_ratio > 0.5
                and c.body_ratio > 0.5
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_inside_up(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            if (
                not a.is_bullish
                and b.is_bullish
                and c.is_bullish
                and b.body < a.body
                and df["close"].iloc[i] > df["close"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_inside_down(self, df: pd.DataFrame, geo: list) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            if (
                a.is_bullish
                and not b.is_bullish
                and not c.is_bullish
                and b.body < a.body
                and df["close"].iloc[i] < df["close"].iloc[i - 1]
            ):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _abandoned_baby(
        self, df: pd.DataFrame, geo: list, direction: str
    ) -> pd.Series:
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i - 2], geo[i - 1], geo[i]
            is_doji_b = b.body_ratio < 0.10
            if direction == "bull":
                gap1 = df["low"].iloc[i - 1] < df["low"].iloc[i - 2]
                gap2 = df["low"].iloc[i] > df["high"].iloc[i - 1]
                if not a.is_bullish and is_doji_b and c.is_bullish and gap1 and gap2:
                    result[i] = 1
            else:
                gap1 = df["high"].iloc[i - 1] > df["high"].iloc[i - 2]
                gap2 = df["high"].iloc[i] < df["low"].iloc[i - 1]
                if a.is_bullish and is_doji_b and not c.is_bullish and gap1 and gap2:
                    result[i] = 1
        return pd.Series(result, index=df.index)

    def _bull_composite(self, out: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=out.index)
        for col, weight in self.BULL_PATTERN_WEIGHTS.items():
            if col in out.columns:
                score += out[col] * weight
        total_weight = sum(self.BULL_PATTERN_WEIGHTS.values())
        return (score / total_weight).clip(0, 1)

    def _bear_composite(self, out: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=out.index)
        for col, weight in self.BEAR_PATTERN_WEIGHTS.items():
            if col in out.columns:
                score += out[col] * weight
        total_weight = sum(self.BEAR_PATTERN_WEIGHTS.values())
        return (score / total_weight).clip(0, 1)

    def _consecutive_direction(
        self, df: pd.DataFrame, direction: str
    ) -> pd.Series:
        is_bull = (df["close"] >= df["open"]).astype(int)
        values = is_bull if direction == "bull" else (1 - is_bull)
        result = []
        count = 0
        for v in values:
            count = count + 1 if v == 1 else 0
            result.append(count)
        return pd.Series(result, index=df.index)
