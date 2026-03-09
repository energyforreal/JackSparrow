"""
Batch feature pipeline: identical logic for training and live inference.

Computes the canonical 50 features from OHLCV DataFrame. Uses vectorized
operations so training and agent get the same values without async/sync mismatch.
"""

from typing import Optional

import numpy as np
import pandas as pd

from feature_store.feature_registry import FEATURE_LIST, EXPECTED_FEATURE_COUNT


def _ema_series(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def compute_features(
    df: pd.DataFrame,
    resolution_minutes: int = 15,
    fill_invalid: bool = True,
) -> pd.DataFrame:
    """
    Compute canonical 50 features from OHLCV DataFrame.
    Columns required: open, high, low, close, volume.
    Optional: timestamp (ignored).
    """
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    n = len(df)
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
    # Stochastic
    hh = h.rolling(14, min_periods=1).max()
    ll = l.rolling(14, min_periods=1).min()
    out["stochastic_k_14"] = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    out["stochastic_d_14"] = out["stochastic_k_14"].rolling(3, min_periods=1).mean()
    out["williams_r_14"] = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    # CCI
    tp = (h + l + c) / 3
    sma_tp = tp.rolling(20, min_periods=1).mean()
    mad = tp.rolling(20, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
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
    # ADX
    tr = np.maximum(h - l, np.maximum((h - c.shift(1)).abs(), (l - c.shift(1)).abs()))
    plus_dm = (h - h.shift(1)).where((h - h.shift(1)) > (l.shift(1) - l), 0).clip(lower=0)
    minus_dm = (l.shift(1) - l).where((l.shift(1) - l) > (h - h.shift(1)), 0).clip(lower=0)
    atr_14 = tr.rolling(14, min_periods=1).mean()
    plus_di = 100 * plus_dm.rolling(14, min_periods=1).mean() / atr_14.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(14, min_periods=1).mean() / atr_14.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out["adx_14"] = dx.rolling(14, min_periods=1).mean()
    # Aroon
    aroon_period = 14
    out["aroon_up"] = (aroon_period - h.rolling(aroon_period).apply(np.argmax, raw=True)) / aroon_period * 100
    out["aroon_down"] = (aroon_period - l.rolling(aroon_period).apply(np.argmin, raw=True)) / aroon_period * 100
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
    out["bb_position"] = (c - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"]).replace(0, np.nan)
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
    if fill_invalid:
        result = result.fillna(0).replace([np.inf, -np.inf], 0)
    return result


class FeaturePipeline:
    """
    Pipeline that computes canonical features from OHLCV.
    Optionally validates output count/order.
    """

    def __init__(
        self,
        resolution_minutes: int = 15,
        fill_invalid: bool = True,
        validate: bool = True,
    ):
        self.resolution_minutes = resolution_minutes
        self.fill_invalid = fill_invalid
        self.validate = validate

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        feat = compute_features(
            df,
            resolution_minutes=self.resolution_minutes,
            fill_invalid=self.fill_invalid,
        )
        if self.validate:
            if list(feat.columns) != FEATURE_LIST:
                raise ValueError("Feature order mismatch")
            if len(feat.columns) != EXPECTED_FEATURE_COUNT:
                raise ValueError(f"Feature count: expected {EXPECTED_FEATURE_COUNT}, got {len(feat.columns)}")
        return feat

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.transform(df)
