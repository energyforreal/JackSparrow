"""Causal per-TF feature engineering for BTCUSD transformers."""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CANDLE_CLASS_COL,
    FEATURE_COLS,
    scale_period,
)
from feature_store.transformer_btcusd.derivatives import (
    compute_funding_derivatives,
    compute_oi_derivatives,
)
from feature_store.transformer_btcusd.structure import (
    add_htf_structure_features,
    add_market_structure_features,
)

WICK_NEGLIGIBLE = 0.05
WICK_BALANCE_MAX = 0.25
FLAT_ATR_MULT = 1e-4
_RATIO_COLS = ("body_ratio", "upper_wick_ratio", "lower_wick_ratio")
_STRUCTURE_EPS = 1e-9
_ATR_NORM_CLIP = 8.0


def assemble_raw_frame(
    df: pd.DataFrame,
    *,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Merge OHLCV with funding/OI using the same path as live inference."""
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

    if "funding_rate" in out.columns:
        out["funding_rate"] = out["funding_rate"].ffill()
    if "open_interest" in out.columns:
        out["open_interest"] = out["open_interest"].ffill()

    return out


def prepare_raw_frame(
    df: pd.DataFrame,
    *,
    funding_df: Optional[pd.DataFrame] = None,
    oi_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Alias for assemble_raw_frame (agent inference entry point)."""
    return assemble_raw_frame(df, funding_df=funding_df, oi_df=oi_df)


def classify_candle_shape(out: pd.DataFrame, *, sr_window: int) -> pd.Series:
    """Assign mutually exclusive single-bar candle class ids 0..12.

    Uses bar-i OHLC geometry plus rolling body-size quantiles up to bar i.
    First matching ``np.select`` condition wins.

    Args:
        out: Frame with open/high/low/close, atr, and wick/body ratio columns.
        sr_window: Rolling lookback for doji/marubozu quantiles.

    Returns:
        int64 Series of class ids aligned with ``out.index``.
    """
    rng_raw = (out["high"] - out["low"]).astype(float)
    atr = out["atr"] if "atr" in out.columns else pd.Series(0.0, index=out.index)
    is_flat = (rng_raw.fillna(0) <= 0) | (
        rng_raw.fillna(0) < atr.fillna(0) * FLAT_ATR_MULT
    )

    body_abs = out["body_ratio"].abs()
    upper = out["upper_wick_ratio"]
    lower = out["lower_wick_ratio"]
    doji_thresh = body_abs.rolling(sr_window, min_periods=20).quantile(0.15)
    marubozu_thresh = body_abs.rolling(sr_window, min_periods=20).quantile(0.85)
    body_median = body_abs.rolling(sr_window, min_periods=20).median()

    wick_sum = upper + lower
    wick_imbalance = (upper - lower).abs() / (wick_sum + 1e-9)
    cond_wicks_balanced = (wick_sum > 2 * WICK_NEGLIGIBLE) & (
        wick_imbalance < WICK_BALANCE_MAX
    )

    cond_doji = ~is_flat & (body_abs < doji_thresh)
    cond_dragonfly = (
        cond_doji
        & (upper < WICK_NEGLIGIBLE)
        & (lower > 2 * WICK_NEGLIGIBLE)
    )
    cond_gravestone = (
        cond_doji
        & (lower < WICK_NEGLIGIBLE)
        & (upper > 2 * WICK_NEGLIGIBLE)
    )
    cond_doji_standard = cond_doji
    cond_marubozu_bull = (
        ~is_flat
        & ~cond_doji
        & (out["body_ratio"] > marubozu_thresh)
        & (upper < WICK_NEGLIGIBLE)
        & (lower < WICK_NEGLIGIBLE)
    )
    cond_marubozu_bear = (
        ~is_flat
        & ~cond_doji
        & (-out["body_ratio"] > marubozu_thresh)
        & (upper < WICK_NEGLIGIBLE)
        & (lower < WICK_NEGLIGIBLE)
    )
    cond_hammer = (
        ~is_flat
        & ~cond_doji
        & (lower > 2 * body_abs)
        & (upper < body_abs)
    )
    cond_inv_hammer = (
        ~is_flat
        & ~cond_doji
        & (upper > 2 * body_abs)
        & (lower < body_abs)
    )
    cond_spinning = (
        ~is_flat
        & ~cond_doji
        & (body_abs < body_median)
        & cond_wicks_balanced
    )
    cond_belt_bull = (
        ~is_flat
        & ~cond_doji
        & (out["close"] > out["open"])
        & (lower < WICK_NEGLIGIBLE)
        & (upper > WICK_NEGLIGIBLE)
    )
    cond_belt_bear = (
        ~is_flat
        & ~cond_doji
        & (out["close"] < out["open"])
        & (upper < WICK_NEGLIGIBLE)
        & (lower > WICK_NEGLIGIBLE)
    )
    cond_standard_bull = ~is_flat & (out["close"] > out["open"])
    cond_standard_bear = ~is_flat & (out["close"] < out["open"])

    conditions = [
        is_flat,
        cond_dragonfly,
        cond_gravestone,
        cond_doji_standard,
        cond_marubozu_bull,
        cond_marubozu_bear,
        cond_hammer,
        cond_inv_hammer,
        cond_spinning,
        cond_belt_bull,
        cond_belt_bear,
        cond_standard_bull,
        cond_standard_bear,
    ]
    choices = list(range(CANDLE_CLASS_CARDINALITY))
    ids = np.select(conditions, choices, default=3).astype(np.int64)
    return pd.Series(ids, index=out.index, dtype="int64")


def summarize_candle_class_distribution(
    feat_df: pd.DataFrame,
    *,
    high_frac: float = 0.40,
    low_frac: float = 0.001,
) -> pd.Series:
    """Return class fractions and print warnings for extreme imbalance.

    Args:
        feat_df: Feature frame containing ``candle_class_id``.
        high_frac: Warn if any class exceeds this share of bars.
        low_frac: Warn if any present class is below this share.

    Returns:
        Normalized value counts indexed by class id.
    """
    counts = feat_df[CANDLE_CLASS_COL].value_counts(normalize=True).sort_index()
    for cid, frac in counts.items():
        if float(frac) > high_frac or float(frac) < low_frac:
            print(
                f"WARNING: candle class {int(cid)} fraction {float(frac):.4f} "
                f"(thresholds {low_frac:.4f} / {high_frac:.2f})"
            )
    return counts


def add_candle_structure_features(out: pd.DataFrame) -> pd.DataFrame:
    """Add causal bar-geometry and bar-to-bar relation features.

    All columns use OHLCV and ATR at or before bar t. Shift-based values on
    the first bar fill to 0.

    Args:
        out: Frame with open/high/low/close and atr.

    Returns:
        The same frame with seven structure columns assigned.
    """
    rng_raw = (out["high"] - out["low"]).astype(float)
    atr = out["atr"] if "atr" in out.columns else pd.Series(0.0, index=out.index)
    is_flat = rng_raw.fillna(0) <= 0

    close_loc = (out["close"] - out["low"]) / (rng_raw + _STRUCTURE_EPS)
    out["close_loc"] = close_loc.where(~is_flat, 0.5).fillna(0.5)

    out["range_atr"] = (rng_raw / (atr + _STRUCTURE_EPS)).clip(
        -_ATR_NORM_CLIP, _ATR_NORM_CLIP
    )
    out["body_atr"] = (
        (out["close"] - out["open"]).abs() / (atr + _STRUCTURE_EPS)
    ).clip(-_ATR_NORM_CLIP, _ATR_NORM_CLIP)
    out["gap_atr"] = (
        (out["open"] - out["close"].shift(1)) / (atr + _STRUCTURE_EPS)
    ).clip(-_ATR_NORM_CLIP, _ATR_NORM_CLIP)

    prev_high = out["high"].shift(1)
    prev_low = out["low"].shift(1)
    out["inside_bar"] = (
        (out["high"] <= prev_high) & (out["low"] >= prev_low)
    ).astype(np.float32)
    out["outside_bar"] = (
        (out["high"] >= prev_high) & (out["low"] <= prev_low)
    ).astype(np.float32)

    prior_body = out["close"].shift(1) - out["open"].shift(1)
    cur_body = out["close"] - out["open"]
    opposite = np.sign(cur_body) != np.sign(prior_body)
    prior_nonzero = prior_body.abs() > _STRUCTURE_EPS
    penetration = (out["close"] - out["open"].shift(1)) / (
        prior_body.abs() + _STRUCTURE_EPS
    )
    out["engulf_score"] = (
        penetration.clip(-2.0, 2.0)
        * np.sign(cur_body)
        * opposite.astype(np.float64)
        * prior_nonzero.astype(np.float64)
    )

    shift_fill_cols = ("gap_atr", "inside_bar", "outside_bar", "engulf_score")
    for col in shift_fill_cols:
        out[col] = out[col].fillna(0.0)
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

    rng_raw = (out["high"] - out["low"]).astype(float)
    is_flat = (rng_raw.fillna(0) <= 0) | (
        rng_raw.fillna(0) < out["atr"].fillna(0) * FLAT_ATR_MULT
    )
    rng = rng_raw.replace(0, np.nan)
    out["body_ratio"] = (out["close"] - out["open"]) / rng
    out["upper_wick_ratio"] = (
        out["high"] - out[["open", "close"]].max(axis=1)
    ) / rng
    out["lower_wick_ratio"] = (
        out[["open", "close"]].min(axis=1) - out["low"]
    ) / rng
    out.loc[is_flat, list(_RATIO_COLS)] = 0.0
    out[list(_RATIO_COLS)] = out[list(_RATIO_COLS)].fillna(0.0)

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

    out = add_candle_structure_features(out)
    out[CANDLE_CLASS_COL] = classify_candle_shape(out, sr_window=sr_window)
    out = add_market_structure_features(out)
    if int(resolution_minutes) == 5:
        out = add_htf_structure_features(out)

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


def validate_feature_columns(
    feat_df: pd.DataFrame,
    *,
    require_finite_closed_bar: bool = False,
    feature_cols: Optional[Sequence[str]] = None,
) -> None:
    cols = tuple(feature_cols) if feature_cols is not None else FEATURE_COLS
    missing = [c for c in cols if c not in feat_df.columns]
    if missing:
        raise ValueError(f"Feature matrix missing columns: {missing}")
    if CANDLE_CLASS_COL not in feat_df.columns:
        raise ValueError(f"Feature matrix missing {CANDLE_CLASS_COL}")
    ids = feat_df[CANDLE_CLASS_COL]
    if ((ids < 0) | (ids > CANDLE_CLASS_CARDINALITY - 1)).any():
        raise ValueError(
            f"{CANDLE_CLASS_COL} out of range [0, {CANDLE_CLASS_CARDINALITY - 1}]"
        )
    if require_finite_closed_bar and len(feat_df) >= 2:
        closed = latest_closed_feature_row(feat_df)
        for col in cols:
            val = closed[col]
            if not np.isfinite(float(val)):
                raise ValueError(f"Non-finite closed-bar value for {col}: {val}")
        cid = int(closed[CANDLE_CLASS_COL])
        if cid < 0 or cid > CANDLE_CLASS_CARDINALITY - 1:
            raise ValueError(f"Closed-bar {CANDLE_CLASS_COL} out of range: {cid}")
