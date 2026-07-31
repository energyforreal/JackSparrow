"""Higher-timeframe and derivative feature helpers for the 15m transformer."""

from __future__ import annotations

import numpy as np
import pandas as pd

_EPS = 1e-9

# v43 48-bar @ 5m ~= 16-bar @ 15m (4h wall-clock).
_ZSCORE_WINDOW_15M = 16
_OI_CHANGE_WINDOW_15M = 2
_FUNDING_ROC_DIFF_BARS_15M = 1


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


def _adx_df(df: pd.DataFrame, period: int = 14) -> pd.Series:
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
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(span=period, adjust=False).mean() / (
        atr_s + _EPS
    )
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / (
        atr_s + _EPS
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + _EPS)
    return dx.ewm(span=period, adjust=False).mean()


def _resample_ohlc(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    work = df.set_index("time").sort_index()
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


def _align_htf_to_primary(
    primary: pd.DataFrame,
    htf: pd.DataFrame,
    feature_cols: tuple[str, ...],
) -> pd.DataFrame:
    """Backward-align HTF feature columns onto the 15m primary index."""
    prim_ts = pd.to_datetime(primary["time"], utc=True)
    hts = pd.to_datetime(htf["time"], utc=True)
    n = len(primary)
    aux = htf[["time"] + list(feature_cols)].copy()
    aux["time"] = hts
    aux = aux.sort_values("time")
    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n)}).sort_values("ts")
    merged = pd.merge_asof(left, aux, left_on="ts", right_on="time", direction="backward")
    merged = merged.sort_values("_ord")
    out = pd.DataFrame(index=primary.index)
    for col in feature_cols:
        out[col] = merged[col].fillna(0.0).values
    return out


def compute_h1_features(primary: pd.DataFrame) -> pd.DataFrame:
    """1h trend/momentum/vol features aligned to 15m bars."""
    zeros = pd.DataFrame(
        {
            "h1_trend": 0.0,
            "h1_rsi_14": 0.0,
            "h1_adx": 0.0,
            "h1_vol_regime": 0.0,
        },
        index=primary.index,
    )
    try:
        d60 = _resample_ohlc(primary, 60)
        if len(d60) < 30:
            return zeros
        c60 = d60["close"]
        df60 = pd.DataFrame(
            {
                "open": d60["open"],
                "high": d60["high"],
                "low": d60["low"],
                "close": c60,
                "volume": d60["volume"],
            }
        )
        h1_ema_21 = _ema(c60, 21)
        h1_ema_50 = _ema(c60, 50)
        h1_trend = (h1_ema_21 - h1_ema_50) / (h1_ema_50 + _EPS)
        h1_rsi_14 = _rsi(c60, 14)
        h1_adx = _adx_df(df60, 14)
        vol_ret = c60.pct_change(1)
        roll20 = vol_ret.rolling(20, min_periods=5).std()
        roll50 = vol_ret.rolling(50, min_periods=10).std()
        h1_vol_regime = roll20 / (roll50.rolling(100, min_periods=20).median() + _EPS)
        htf = pd.DataFrame(
            {
                "time": d60["time"],
                "h1_trend": h1_trend,
                "h1_rsi_14": h1_rsi_14,
                "h1_adx": h1_adx,
                "h1_vol_regime": h1_vol_regime,
            }
        )
        return _align_htf_to_primary(
            primary,
            htf,
            ("h1_trend", "h1_rsi_14", "h1_adx", "h1_vol_regime"),
        )
    except Exception:
        return zeros


def compute_funding_derivatives(
    fund_rate: pd.Series,
    ret_2: pd.Series,
    *,
    z_window: int = _ZSCORE_WINDOW_15M,
) -> pd.DataFrame:
    """Funding z-score, momentum, and rate-of-change on 15m bars."""
    fz_mean = fund_rate.rolling(z_window, min_periods=5).mean()
    fz_std = fund_rate.rolling(z_window, min_periods=5).std().replace(0, _EPS)
    funding_zscore = ((fund_rate - fz_mean) / fz_std).fillna(0.0).clip(-4.0, 4.0)
    funding_mom = funding_zscore * ret_2
    diff = fund_rate.diff(_FUNDING_ROC_DIFF_BARS_15M)
    roc_mu = diff.rolling(z_window, min_periods=5).mean()
    roc_std = diff.rolling(z_window, min_periods=5).std().replace(0, _EPS)
    funding_rate_roc = ((diff - roc_mu) / roc_std).fillna(0.0).clip(-4.0, 4.0)
    return pd.DataFrame(
        {
            "funding_zscore": funding_zscore,
            "funding_mom": funding_mom.fillna(0.0),
            "funding_rate_roc": funding_rate_roc,
        }
    )


def compute_oi_derivatives(
    primary: pd.DataFrame,
    *,
    z_window: int = _ZSCORE_WINDOW_15M,
    change_window: int = _OI_CHANGE_WINDOW_15M,
) -> pd.DataFrame:
    """OI-derived features on 15m bars (v43 patterns, rescaled windows)."""
    n = len(primary)
    zero = pd.DataFrame(
        {
            "oi_change_2": np.zeros(n),
            "oi_delta_z": np.zeros(n),
            "oi_price_divergence": np.zeros(n),
            "oi_acceleration": np.zeros(n),
            "oi_zscore": np.zeros(n),
        },
        index=primary.index,
    )
    if "open_interest" not in primary.columns:
        return zero

    oi_s = primary["open_interest"].astype(float)
    if oi_s.notna().sum() == 0 or float(oi_s.max()) < _EPS:
        return zero

    oi_mu = oi_s.rolling(z_window, min_periods=max(2, z_window // 4)).mean()
    oi_std = oi_s.rolling(z_window, min_periods=max(2, z_window // 4)).std().clip(
        lower=_EPS
    )
    oi_zscore = ((oi_s - oi_mu) / oi_std).fillna(0.0).clip(-4.0, 4.0)

    oi_lagged = oi_s.shift(change_window).bfill().fillna(oi_s)
    oi_change_2 = (
        ((oi_s - oi_lagged) / (oi_lagged.abs() + _EPS)).fillna(0.0).clip(-0.05, 0.05)
    )

    close_s = primary["close"].astype(float)
    close_lagged = close_s.shift(change_window).bfill().fillna(close_s)
    ret_2 = ((close_s - close_lagged) / (close_lagged.abs() + _EPS)).fillna(0.0)
    oi_price_divergence = (
        np.sign(oi_change_2.values) * -np.sign(ret_2.values)
    ).astype(np.float32)
    oi_acceleration = oi_change_2.diff().fillna(0.0).clip(-0.02, 0.02)

    oi_delta_1 = oi_s.diff(1).fillna(0.0)
    oi_delta_mu = oi_delta_1.rolling(z_window, min_periods=max(2, z_window // 4)).mean()
    oi_delta_std = oi_delta_1.rolling(z_window, min_periods=max(2, z_window // 4)).std().clip(
        lower=_EPS
    )
    oi_delta_z = ((oi_delta_1 - oi_delta_mu) / oi_delta_std).fillna(0.0).clip(-4.0, 4.0)

    return pd.DataFrame(
        {
            "oi_zscore": oi_zscore,
            "oi_change_2": oi_change_2,
            "oi_price_divergence": pd.Series(oi_price_divergence).fillna(0.0),
            "oi_acceleration": oi_acceleration,
            "oi_delta_z": oi_delta_z,
        },
        index=primary.index,
    ).replace([np.inf, -np.inf], 0.0).fillna(0.0)
