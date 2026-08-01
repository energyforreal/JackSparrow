"""Causal per-TF feature engineering for BTCUSD transformers."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import FEATURE_COLS, scale_period
from feature_store.transformer_btcusd.derivatives import (
    compute_funding_derivatives,
    compute_oi_derivatives,
)


def prepare_raw_frame(
    df: pd.DataFrame,
    *,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Normalize agent/OHLCV frames to the notebook raw_df schema."""
    out = df.copy()
    if "timestamp" in out.columns and "time" not in out.columns:
        out["time"] = pd.to_datetime(out["timestamp"], utc=True)
    elif "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    else:
        raise ValueError("OHLCV frame requires timestamp or time column")

    required = ("open", "high", "low", "close", "volume")
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")

    out = out.sort_values("time").reset_index(drop=True)

    if funding_df is not None and not funding_df.empty:
        fund = funding_df.copy()
        if "timestamp" in fund.columns:
            fund["time"] = pd.to_datetime(fund["timestamp"], utc=True)
        rate_col = "funding_rate" if "funding_rate" in fund.columns else "close"
        fund = fund[["time", rate_col]].rename(columns={rate_col: "funding_rate"})
        out = pd.merge_asof(
            out.sort_values("time"),
            fund.sort_values("time"),
            on="time",
            direction="backward",
        )
    elif "funding_rate" not in out.columns:
        out["funding_rate"] = np.nan

    if oi_df is not None and not oi_df.empty:
        oi = oi_df.copy()
        if "timestamp" in oi.columns:
            oi["time"] = pd.to_datetime(oi["timestamp"], utc=True)
        oi_col = None
        for candidate in ("open_interest", "oi_contracts", "close"):
            if candidate in oi.columns:
                oi_col = candidate
                break
        if oi_col is not None:
            oi = oi[["time", oi_col]].rename(columns={oi_col: "open_interest"})
            out = pd.merge_asof(
                out.sort_values("time"),
                oi.sort_values("time"),
                on="time",
                direction="backward",
            )
    elif "open_interest" not in out.columns:
        out["open_interest"] = np.nan

    return out


def add_features(
    df: pd.DataFrame,
    *,
    resolution_minutes: int = 15,
    atr_period: int = 14,
    rsi_period: int = 14,
    adx_period: int = 14,
    ema_period: int = 50,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """Compute causal features on a native TF grid."""
    out = df.copy()
    rv_short = scale_period(16, resolution_minutes)
    rv_long = scale_period(96, resolution_minutes)
    sr_window = scale_period(96, resolution_minutes)
    obv_window = scale_period(96, resolution_minutes)
    vol_window = scale_period(96, resolution_minutes)
    ret2_bars = max(1, scale_period(2, resolution_minutes))

    atr_period = scale_period(atr_period, resolution_minutes)
    rsi_period = scale_period(rsi_period, resolution_minutes)
    adx_period = scale_period(adx_period, resolution_minutes)
    ema_period = scale_period(ema_period, resolution_minutes)
    macd_fast = scale_period(macd_fast, resolution_minutes)
    macd_slow = scale_period(macd_slow, resolution_minutes)
    macd_signal = scale_period(macd_signal, resolution_minutes)

    out["ret_1"] = np.log(out["close"] / out["close"].shift(1))

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(atr_period).mean()

    out["rv_16"] = out["ret_1"].rolling(rv_short).std()
    out["rv_96"] = out["ret_1"].rolling(rv_long).std()

    out["ema50"] = out["close"].ewm(span=ema_period, adjust=False).mean()
    out["ema50_dist_pct"] = (out["close"] - out["ema50"]) / out["ema50"]

    ema_fast_s = out["close"].ewm(span=macd_fast, adjust=False).mean()
    ema_slow_s = out["close"].ewm(span=macd_slow, adjust=False).mean()
    macd_line = ema_fast_s - ema_slow_s
    macd_signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
    out["macd_hist"] = macd_line - macd_signal_line

    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / (loss + 1e-9)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    up_move = out["high"].diff()
    down_move = -out["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_for_di = tr.rolling(adx_period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=out.index).rolling(adx_period).mean() / (
        atr_for_di + 1e-9
    )
    minus_di = 100 * pd.Series(minus_dm, index=out.index).rolling(adx_period).mean() / (
        atr_for_di + 1e-9
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    out["adx_14"] = dx.rolling(adx_period).mean()

    obv_raw = (np.sign(out["close"].diff()) * out["volume"]).fillna(0).cumsum()
    out["obv_z"] = (obv_raw - obv_raw.rolling(obv_window).mean()) / (
        obv_raw.rolling(obv_window).std() + 1e-9
    )

    out["vol_z"] = (out["volume"] - out["volume"].rolling(vol_window).mean()) / (
        out["volume"].rolling(vol_window).std() + 1e-9
    )

    rng = (out["high"] - out["low"]).replace(0, np.nan)
    out["body_ratio"] = (out["close"] - out["open"]) / rng
    out["upper_wick_ratio"] = (
        out["high"] - out[["open", "close"]].max(axis=1)
    ) / rng
    out["lower_wick_ratio"] = (
        out[["open", "close"]].min(axis=1) - out["low"]
    ) / rng

    out["hour"] = out["time"].dt.hour
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    out["dow"] = out["time"].dt.dayofweek
    out["dow_sin"] = np.sin(2 * np.pi * out["dow"] / 7)
    out["dow_cos"] = np.cos(2 * np.pi * out["dow"] / 7)

    rolling_high = out["high"].rolling(sr_window).max()
    rolling_low = out["low"].rolling(sr_window).min()
    out["dist_to_resistance_pct"] = (rolling_high - out["close"]) / out["close"]
    out["dist_to_support_pct"] = (out["close"] - rolling_low) / out["close"]

    if "funding_rate" not in out.columns:
        out["funding_rate"] = np.nan

    if "open_interest" in out.columns:
        oi_z_window = scale_period(96, resolution_minutes)
        out["oi_z"] = (out["open_interest"] - out["open_interest"].rolling(oi_z_window).mean()) / (
            out["open_interest"].rolling(oi_z_window).std() + 1e-9
        )
    else:
        out["oi_z"] = np.nan

    ret_2 = out["close"].pct_change(ret2_bars)
    fund_rate = out["funding_rate"].fillna(0.0)
    funding_deriv = compute_funding_derivatives(
        fund_rate, ret_2, resolution_minutes=resolution_minutes
    )
    for col in funding_deriv.columns:
        out[col] = funding_deriv[col].values

    oi_deriv = compute_oi_derivatives(out, resolution_minutes=resolution_minutes)
    out["oi_change_2"] = oi_deriv["oi_change_2"]
    out["oi_delta_z"] = oi_deriv["oi_delta_z"]
    out["oi_price_divergence"] = oi_deriv["oi_price_divergence"]
    out["oi_acceleration"] = oi_deriv["oi_acceleration"]
    out["funding_x_oi"] = out["funding_zscore"] * oi_deriv["oi_zscore"]

    return out


def build_feature_matrix(
    df: pd.DataFrame,
    *,
    resolution_minutes: int = 15,
    atr_period: int = 14,
    dropna: bool = True,
) -> pd.DataFrame:
    """Return feature columns ready for windowing."""
    feat = add_features(df, resolution_minutes=resolution_minutes, atr_period=atr_period)
    if dropna:
        feat = feat.dropna().reset_index(drop=True)
    return feat


def latest_closed_feature_row(feat_df: pd.DataFrame) -> pd.Series:
    """Closed-bar row used for diagnostics (second-to-last after dropna)."""
    if len(feat_df) < 2:
        raise ValueError("Need at least 2 feature rows for closed-bar semantics")
    return feat_df.iloc[-2]


def validate_feature_columns(feat_df: pd.DataFrame) -> None:
    missing = [c for c in FEATURE_COLS if c not in feat_df.columns]
    if missing:
        raise ValueError(f"Feature matrix missing columns: {missing}")
