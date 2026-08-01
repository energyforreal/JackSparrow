"""Funding and OI derivative features scaled per resolution."""

from __future__ import annotations

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import scale_period

_EPS = 1e-9


def compute_funding_derivatives(
    fund_rate: pd.Series,
    ret_2: pd.Series,
    *,
    resolution_minutes: int,
) -> pd.DataFrame:
    """Funding z-score, momentum, and rate-of-change on native TF bars."""
    z_window = scale_period(16, resolution_minutes)
    roc_diff = max(1, scale_period(1, resolution_minutes))
    fz_mean = fund_rate.rolling(z_window, min_periods=5).mean()
    fz_std = fund_rate.rolling(z_window, min_periods=5).std().replace(0, _EPS)
    funding_zscore = ((fund_rate - fz_mean) / fz_std).fillna(0.0).clip(-4.0, 4.0)
    funding_mom = funding_zscore * ret_2
    diff = fund_rate.diff(roc_diff)
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
    resolution_minutes: int,
) -> pd.DataFrame:
    """OI-derived features on native TF bars."""
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

    z_window = scale_period(16, resolution_minutes)
    change_window = max(1, scale_period(2, resolution_minutes))

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
