"""Causal feature columns for the 30-minute research line.

Every column at row ``t`` is a function of bars at or before ``t``.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from research.forecast_30m.contract import ATR_PERIOD, FEATURE_COLUMNS
from research.forecast_30m.contract_v4 import (
    CONSECUTIVE_CLIP,
    DOJI_BODY_MAX,
    HAMMER_OPPOSITE_MAX,
    HAMMER_WICK_MIN,
)
from research.forecast_30m.labels import causal_atr


def add_features(
    frame: pd.DataFrame,
    *,
    feature_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Append the fixed causal feature set.

    Args:
        frame: OHLCV sorted by time, with ``open``, ``high``, ``low``,
            ``close``, and ``volume``.
        feature_columns: Columns that must be finite for ``feature_row_ok``.
            Defaults to the v1 set so older pipelines are unchanged.

    Returns:
        Copy including the v1 columns and the v4 pattern block.

    Raises:
        ValueError: If a required price column is missing.
    """
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Feature frame is missing columns: {sorted(missing)}")
    out = frame.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    open_ = out["open"].astype(float)
    volume = out["volume"].astype(float)
    atr = causal_atr(
        high.to_numpy(dtype=np.float64),
        low.to_numpy(dtype=np.float64),
        close.to_numpy(dtype=np.float64),
        period=ATR_PERIOD,
    )
    out["return_1"] = close / close.shift(1) - 1.0
    out["return_6"] = close / close.shift(6) - 1.0
    out["return_12"] = close / close.shift(12) - 1.0
    out["return_24"] = close / close.shift(24) - 1.0
    moving = close.rolling(20, min_periods=20).mean()
    out["ma_distance_20"] = (close - moving) / close
    out["ma_slope_20"] = (moving - moving.shift(5)) / close
    out["rsi_14"] = _rsi(close, 14)
    out["atr_pct_14"] = atr / close.to_numpy(dtype=np.float64)
    log_return = np.log(close / close.shift(1))
    realized_12 = log_return.rolling(12, min_periods=12).std(ddof=0)
    realized_48 = log_return.rolling(48, min_periods=48).std(ddof=0)
    out["vol_ratio_12_48"] = realized_12 / realized_48.replace(0.0, np.nan)
    span = (high - low).replace(0.0, np.nan)
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low
    out["candle_body"] = (close - open_) / span
    out["upper_wick"] = upper / span
    out["lower_wick"] = lower / span
    out["close_location"] = (close - low) / span
    volume_mean = volume.rolling(24, min_periods=24).mean().replace(0.0, np.nan)
    out["volume_ratio_24"] = volume / volume_mean
    out["dist_high_24"] = (close - high.rolling(24, min_periods=24).max()) / close
    out["dist_low_24"] = (close - low.rolling(24, min_periods=24).min()) / close
    stamps = pd.to_datetime(out["time"], utc=True)
    hour = stamps.dt.hour + stamps.dt.minute / 60.0
    dow = stamps.dt.dayofweek.astype(float)
    out["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    out["dow_sin"] = np.sin(2.0 * np.pi * dow / 7.0)
    out["dow_cos"] = np.cos(2.0 * np.pi * dow / 7.0)
    _add_pattern_columns(out, open_, high, low, close, span)
    required_columns = list(FEATURE_COLUMNS if feature_columns is None else feature_columns)
    out["feature_row_ok"] = np.isfinite(out.loc[:, required_columns]).all(axis=1)
    return out


def _add_pattern_columns(
    out: pd.DataFrame,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    span: pd.Series,
) -> None:
    """Add candlestick and structure flags using bars at or before each row."""
    body = close - open_
    abs_body = body.abs()
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low
    body_frac = abs_body / span
    upper_frac = upper / span
    lower_frac = lower / span
    out["doji"] = (body_frac <= DOJI_BODY_MAX).astype(np.float64)
    out["hammer"] = (
        (lower_frac >= HAMMER_WICK_MIN)
        & (upper_frac <= HAMMER_OPPOSITE_MAX)
        & ((close - low) / span >= 0.5)
    ).astype(np.float64)
    out["shooting_star"] = (
        (upper_frac >= HAMMER_WICK_MIN)
        & (lower_frac <= HAMMER_OPPOSITE_MAX)
        & ((close - low) / span <= 0.5)
    ).astype(np.float64)
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_body = prev_close - prev_open
    bullish = close > open_
    bearish = close < open_
    prev_bullish = prev_close > prev_open
    prev_bearish = prev_close < prev_open
    two_bar = prev_open.notna()
    out["bullish_engulfing"] = np.where(
        two_bar,
        (
            prev_bearish
            & bullish
            & (open_ <= prev_close)
            & (close >= prev_open)
            & (abs_body > prev_body.abs())
        ).astype(np.float64),
        np.nan,
    )
    out["bearish_engulfing"] = np.where(
        two_bar,
        (
            prev_bullish
            & bearish
            & (open_ >= prev_close)
            & (close <= prev_open)
            & (abs_body > prev_body.abs())
        ).astype(np.float64),
        np.nan,
    )
    out["inside_bar"] = np.where(
        two_bar,
        ((high <= prev_high) & (low >= prev_low)).astype(np.float64),
        np.nan,
    )
    prior_high = high.shift(1).rolling(24, min_periods=24).max()
    prior_low = low.shift(1).rolling(24, min_periods=24).min()
    out["close_broke_high_24"] = np.where(
        prior_high.notna(), (close > prior_high).astype(np.float64), np.nan
    )
    out["close_broke_low_24"] = np.where(
        prior_low.notna(), (close < prior_low).astype(np.float64), np.nan
    )
    up = (close > close.shift(1)).fillna(False)
    down = (close < close.shift(1)).fillna(False)
    run = np.zeros(len(close), dtype=np.float64)
    for index in range(1, len(close)):
        if bool(up.iloc[index]):
            run[index] = run[index - 1] + 1.0 if run[index - 1] > 0.0 else 1.0
        elif bool(down.iloc[index]):
            run[index] = run[index - 1] - 1.0 if run[index - 1] < 0.0 else -1.0
        else:
            run[index] = 0.0
    out["consecutive_closes"] = np.clip(run, -CONSECUTIVE_CLIP, CONSECUTIVE_CLIP)
    range_ok = np.isfinite(span.to_numpy(dtype=np.float64))
    for column in ("doji", "hammer", "shooting_star"):
        out.loc[~range_ok, column] = np.nan
    out.loc[0, "consecutive_closes"] = np.nan


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period, min_periods=period).mean()
    relative = gain / loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + relative))
    rsi = rsi.where(loss != 0.0, np.where(gain > 0.0, 100.0, 50.0))
    return rsi
