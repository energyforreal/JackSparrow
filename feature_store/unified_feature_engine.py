"""
Unified feature computation engine: single source of truth for all features.

Both training (batch) and live (single) paths MUST use this class to ensure
train-serve parity. No separate implementations elsewhere.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from feature_store.feature_registry import (
    CANDLESTICK_FEATURES,
    CHART_PATTERN_FEATURES,
    EXPECTED_FEATURE_COUNT,
    FEATURE_LIST,
    MTF_CONTEXT_FEATURES,
)
from feature_store.pattern_features.candlestick_patterns import CandlestickPatternEngine
from feature_store.pattern_features.chart_patterns import ChartPatternEngine

# V4 model extras (not in canonical 50 but used by jacksparrow_v4)
V4_EXTRA_FEATURES = [
    "ema_9",
    "ema_21",
    "macd_hist",  # alias for macd_histogram
    "bb_pct",  # alias for bb_position
    "vol_zscore",
    "vol_ratio",
    "ema_cross",
    "returns_1",
    "atr_pct",
]
FEATURE_ALIASES = {
    "macd_hist": "macd_histogram",
    "bb_pct": "bb_position",
    "vol_ratio": "volume_ratio",
}


def _ema_series(s: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return s.ewm(span=period, adjust=False).mean()


def _rsi_14_from_close(c: pd.Series) -> pd.Series:
    """RSI(14) on close; matches rolling-mean variant used in compute_batch."""
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ensure_timestamp_series(df: pd.DataFrame) -> pd.Series:
    """Return UTC datetime series aligned to df rows (from timestamp or time)."""
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
    elif "time" in df.columns:
        ts = pd.to_datetime(df["time"], unit="s", utc=True)
    else:
        raise ValueError("DataFrame must have 'timestamp' or 'time' for MTF context")
    return ts


class UnifiedFeatureEngine:
    """
    Single source of truth for all feature computation.
    Both live and training MUST use this class.
    """

    SUPPORTED_FEATURES = list(FEATURE_LIST) + list(
        {f for f in V4_EXTRA_FEATURES if f not in FEATURE_LIST}
    ) + list(CANDLESTICK_FEATURES) + list(CHART_PATTERN_FEATURES) + list(MTF_CONTEXT_FEATURES)

    def __init__(self):
        self._cdl_engine = CandlestickPatternEngine()
        self._chp_engine = ChartPatternEngine()

    def _mtf_context_from_primary(
        self, df: pd.DataFrame, resolution_minutes: int
    ) -> pd.DataFrame:
        """
        Multi-timeframe context on the primary bar index: resample OHLCV to 3m/15m,
        compute RSI/EMA on resampled closes, forward-fill to primary timestamps.
        mtf_1m_vol_ratio is a short-horizon volume spike proxy on the primary grid.
        When resolution is not 5m, returns zeros (caller should skip MTF in training).
        """
        n = len(df)
        zero = pd.DataFrame(
            {name: np.zeros(n, dtype=float) for name in MTF_CONTEXT_FEATURES}
        )
        if resolution_minutes != 5:
            return zero
        try:
            ts = _ensure_timestamp_series(df)
        except ValueError:
            return zero

        work = pd.DataFrame(
            {
                "timestamp": ts,
                "open": df["open"].astype(float),
                "high": df["high"].astype(float),
                "low": df["low"].astype(float),
                "close": df["close"].astype(float),
                "volume": df["volume"].astype(float),
            }
        )
        work = work.set_index("timestamp").sort_index()
        idx = work.index
        out = pd.DataFrame(index=idx)
        for rule, prefix in [("3min", "mtf_3m"), ("15min", "mtf_15m")]:
            r = (
                work.resample(rule, label="right", closed="right")
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
            c = r["close"].astype(float)
            rsi = _rsi_14_from_close(c).reindex(idx, method="ffill")
            ema12 = _ema_series(c, 12).reindex(idx, method="ffill")
            out[f"{prefix}_rsi_14"] = rsi
            out[f"{prefix}_ema_12"] = ema12

        v = work["volume"].astype(float)
        vm = v.rolling(3, min_periods=1).mean()
        out["mtf_1m_vol_ratio"] = v / vm.replace(0, np.nan)

        out = out.reindex(columns=list(MTF_CONTEXT_FEATURES))
        out = out.fillna(0).replace([np.inf, -np.inf], 0)
        return out.reset_index(drop=True)

    def compute_batch(
        self,
        df: pd.DataFrame,
        resolution_minutes: int = 15,
        fill_invalid: bool = True,
        include_pattern_features: bool = False,
        include_mtf_context: bool = False,
    ) -> pd.DataFrame:
        """
        Compute canonical 50 features from OHLCV DataFrame.
        Used during training. Returns full feature matrix.
        """
        o = df["open"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        out: dict[str, pd.Series] = {}

        # ---- Price ----
        for period in [10, 20, 50, 100, 200]:
            key = f"sma_{period}"
            out[key] = c.rolling(period, min_periods=1).mean()
        for period in [12, 26, 50]:
            key = f"ema_{period}"
            out[key] = _ema_series(c, period)
        for period in [20, 50, 200]:
            sma = c.rolling(period, min_periods=1).mean()
            out[f"close_sma_{period}_ratio"] = c / sma.replace(0, np.nan).ffill().bfill()
        out["high_low_spread"] = (h - l) / l.replace(0, np.nan)
        out["close_open_ratio"] = c / o.replace(0, np.nan)
        out["body_size"] = (c - o).abs() / o.replace(0, np.nan)
        body_top = np.maximum(c, o)
        body_bot = np.minimum(c, o)
        out["upper_shadow"] = (h - body_top) / body_top.replace(0, np.nan)
        out["lower_shadow"] = (body_bot - l) / body_bot.replace(0, np.nan)

        # ---- Momentum ----
        delta = c.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        for period in [14, 7]:
            avg_gain = gain.rolling(period, min_periods=1).mean()
            avg_loss = loss.rolling(period, min_periods=1).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            out[f"rsi_{period}"] = 100 - (100 / (1 + rs))
        hh = h.rolling(14, min_periods=1).max()
        ll = l.rolling(14, min_periods=1).min()
        out["stochastic_k_14"] = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
        out["stochastic_d_14"] = out["stochastic_k_14"].rolling(3, min_periods=1).mean()
        out["williams_r_14"] = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
        tp = (h + l + c) / 3
        sma_tp = tp.rolling(20, min_periods=1).mean()
        mad = tp.rolling(20, min_periods=1).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        out["cci_20"] = (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))
        out["roc_10"] = (c - c.shift(10)) / c.shift(10).replace(0, np.nan) * 100
        out["roc_20"] = (c - c.shift(20)) / c.shift(20).replace(0, np.nan) * 100
        out["momentum_10"] = c - c.shift(10)
        out["momentum_20"] = c - c.shift(20)

        # ---- Trend ----
        ema12 = _ema_series(c, 12)
        ema26 = _ema_series(c, 26)
        macd_line = ema12 - ema26
        out["macd"] = macd_line
        out["macd_signal"] = _ema_series(macd_line, 9)
        out["macd_histogram"] = macd_line - out["macd_signal"]
        tr = np.maximum(
            h - l,
            np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()),
        )
        plus_dm = (h - h.shift(1)).where(
            (h - h.shift(1)) > (l.shift(1) - l), 0
        ).clip(lower=0)
        minus_dm = (l.shift(1) - l).where(
            (l.shift(1) - l) > (h - h.shift(1)), 0
        ).clip(lower=0)
        atr_14 = tr.rolling(14, min_periods=1).mean()
        plus_di = 100 * plus_dm.rolling(14, min_periods=1).mean() / atr_14.replace(
            0, np.nan
        )
        minus_di = 100 * minus_dm.rolling(14, min_periods=1).mean() / atr_14.replace(
            0, np.nan
        )
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        out["adx_14"] = dx.rolling(14, min_periods=1).mean()
        aroon_period = 14
        out["aroon_up"] = (
            (aroon_period - h.rolling(aroon_period).apply(np.argmax, raw=True))
            / aroon_period
            * 100
        )
        out["aroon_down"] = (
            (aroon_period - l.rolling(aroon_period).apply(np.argmin, raw=True))
            / aroon_period
            * 100
        )
        out["aroon_oscillator"] = out["aroon_up"] - out["aroon_down"]
        sma5 = c.rolling(5, min_periods=1).mean()
        sma20 = c.rolling(20, min_periods=1).mean()
        out["trend_strength"] = (sma5 - sma20) / sma20.replace(0, np.nan) * 100

        # ---- Volatility ----
        sma20 = c.rolling(20, min_periods=1).mean()
        std20 = c.rolling(20, min_periods=1).std()
        out["bb_upper"] = sma20 + 2 * std20
        out["bb_lower"] = sma20 - 2 * std20
        out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / c.replace(0, np.nan) * 100
        out["bb_position"] = (c - out["bb_lower"]) / (
            (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
        )
        out["atr_14"] = tr.rolling(14, min_periods=1).mean()
        out["atr_20"] = tr.rolling(20, min_periods=1).mean()
        ret = c.pct_change()
        out["volatility_10"] = ret.rolling(10, min_periods=1).std().fillna(0) * 100
        out["volatility_20"] = ret.rolling(20, min_periods=1).std().fillna(0) * 100

        # ---- Volume ----
        out["volume_sma_20"] = v.rolling(20, min_periods=1).mean()
        out["volume_ratio"] = v / out["volume_sma_20"].replace(0, np.nan)
        obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
        out["obv"] = obv
        vpt = (v * ret).fillna(0).cumsum()
        out["volume_price_trend"] = vpt
        mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
        ad = (mfm * v).fillna(0).cumsum()
        out["accumulation_distribution"] = ad
        ad_ema3 = ad.ewm(span=3, adjust=False).mean()
        ad_ema10 = ad.ewm(span=10, adjust=False).mean()
        out["chaikin_oscillator"] = ad_ema3 - ad_ema10

        # ---- Returns (resolution-dependent) ----
        bars_1h = max(1, 60 // resolution_minutes)
        bars_24h = max(1, 24 * 60 // resolution_minutes)
        out["returns_1h"] = (c / c.shift(bars_1h).replace(0, np.nan) - 1) * 100
        out["returns_24h"] = (c / c.shift(bars_24h).replace(0, np.nan) - 1) * 100

        result = pd.DataFrame({k: out[k] for k in FEATURE_LIST})
        if include_pattern_features:
            cdl = self._cdl_engine.compute_all(df)
            chp = self._chp_engine.compute_all(df)
            result = pd.concat([result, cdl, chp], axis=1)
        if include_mtf_context:
            mtf = self._mtf_context_from_primary(df, resolution_minutes)
            result = pd.concat([result, mtf], axis=1)
        if fill_invalid:
            result = result.fillna(0).replace([np.inf, -np.inf], 0)
        return result

    def compute_single(
        self,
        feature_name: str,
        candles: List[dict],
        resolution_minutes: int = 15,
    ) -> float:
        """
        Compute a single feature value for live inference.
        Returns the latest scalar for the given feature.
        Supports canonical 50, aliases, v4 extras, and candlestick pattern features.
        """
        # Candlestick pattern features
        if feature_name in CANDLESTICK_FEATURES:
            df = pd.DataFrame(candles)
            cdl = self._cdl_engine.compute_all(df)
            return float(cdl[feature_name].iloc[-1])

        # Chart pattern features
        if feature_name in CHART_PATTERN_FEATURES:
            df = pd.DataFrame(candles)
            chp = self._chp_engine.compute_all(df)
            return float(chp[feature_name].iloc[-1])

        if feature_name in MTF_CONTEXT_FEATURES:
            df = pd.DataFrame(candles)
            mtf = self._mtf_context_from_primary(df, resolution_minutes)
            return float(mtf[feature_name].iloc[-1])

        resolved = FEATURE_ALIASES.get(feature_name, feature_name)
        if resolved in FEATURE_LIST:
            df = pd.DataFrame(candles)
            batch = self.compute_batch(
                df,
                resolution_minutes=resolution_minutes,
                fill_invalid=True,
            )
            return float(batch[resolved].iloc[-1])

        # V4 extras: compute on demand
        df = pd.DataFrame(candles)
        batch = self.compute_batch(
            df,
            resolution_minutes=resolution_minutes,
            fill_invalid=True,
        )
        c = df["close"].astype(float)
        v = df["volume"].astype(float)
        o = df["open"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)

        if feature_name == "ema_9":
            return float(_ema_series(c, 9).iloc[-1])
        if feature_name == "ema_21":
            return float(_ema_series(c, 21).iloc[-1])
        if feature_name == "ema_cross":
            ema9 = _ema_series(c, 9).iloc[-1]
            ema21 = _ema_series(c, 21).iloc[-1]
            return float(ema9 - ema21)
        if feature_name == "returns_1":
            if len(c) < 2:
                return 0.0
            return float((c.iloc[-1] / c.iloc[-2] - 1) * 100) if c.iloc[-2] > 0 else 0.0
        if feature_name == "atr_pct":
            atr = batch["atr_14"].iloc[-1]
            close = c.iloc[-1]
            return float(atr / close * 100) if close > 0 else 0.0
        if feature_name == "vol_zscore":
            if len(v) < 21:
                return 0.0
            recent = v.iloc[-20:]
            mean_v = recent.mean()
            std_v = recent.std()
            return float((v.iloc[-1] - mean_v) / std_v) if std_v > 0 else 0.0

        raise ValueError(f"Unknown feature: {feature_name}")


# Module-level singleton for convenience (optional; callers may instantiate)
_default_engine: Optional[UnifiedFeatureEngine] = None


def get_unified_engine() -> UnifiedFeatureEngine:
    """Return the default unified feature engine instance."""
    global _default_engine
    if _default_engine is None:
        _default_engine = UnifiedFeatureEngine()
    return _default_engine
