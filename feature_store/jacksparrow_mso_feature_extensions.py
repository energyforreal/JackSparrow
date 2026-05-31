"""MSO structural features (real-data only) and train/serve feature column contract."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES

# Live-only microstructure — excluded from MSO (no historical real data).
MSO_EXCLUDED_V43_FEATURES: Tuple[str, ...] = (
    "bid_ask_imbalance",
    "spread_bps",
    "funding_predicted_zscore",
)

MSO_STRUCTURAL_FEATURES: Tuple[str, ...] = (
    "atr_expansion_ratio",
    "bb_width_pct",
    "candle_body_compression",
    "oi_velocity",
    "oi_acceleration_mso",
    "wick_rejection_ratio",
    "funding_acceleration",
    "realized_vol_ratio",
    "range_expansion_rate",
    "compression_score",
    "oi_funding_pressure",
    "stop_hunt_score",
)

MSO_BASE_V43_FEATURES: Tuple[str, ...] = tuple(
    f for f in V43_CANONICAL_FEATURES if f not in MSO_EXCLUDED_V43_FEATURES
)

MSO_FEATURE_COLS: Tuple[str, ...] = MSO_BASE_V43_FEATURES + MSO_STRUCTURAL_FEATURES

_EPS = 1e-12


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=max(2, window // 2)).mean()


def build_mso_structural_features(
    df_feat: pd.DataFrame,
    *,
    df_ohlcv: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Append MSO structural columns; NaN where windows insufficient (no fillna)."""
    out = pd.DataFrame(index=df_feat.index)
    ohlcv = df_ohlcv if df_ohlcv is not None else df_feat
    for col in ("open", "high", "low", "close"):
        if col not in ohlcv.columns:
            raise ValueError(f"build_mso_structural_features requires OHLCV column {col!r}")

    o = pd.to_numeric(ohlcv["open"], errors="coerce")
    h = pd.to_numeric(ohlcv["high"], errors="coerce")
    l = pd.to_numeric(ohlcv["low"], errors="coerce")
    c = pd.to_numeric(ohlcv["close"], errors="coerce")
    body = (c - o).abs()

    atr5 = _atr(h, l, c, 5)
    atr20 = _atr(h, l, c, 20)
    out["atr_expansion_ratio"] = atr5 / atr20.replace(0, np.nan)

    bb_w = pd.to_numeric(df_feat.get("bb_width", np.nan), errors="coerce")
    out["bb_width_pct"] = bb_w.rolling(200, min_periods=30).apply(
        lambda x: float((x.iloc[-1] <= x).mean()) if len(x) else np.nan,
        raw=False,
    )

    body5 = body.rolling(5, min_periods=3).mean()
    body20 = body.rolling(20, min_periods=10).mean()
    out["candle_body_compression"] = body5 / body20.replace(0, np.nan)

    oi = pd.to_numeric(df_feat.get("oi_zscore", np.nan), errors="coerce")
    if "oi_contracts" in df_feat.columns:
        oi_raw = pd.to_numeric(df_feat["oi_contracts"], errors="coerce")
        oi_vel = oi_raw.pct_change(1).clip(-0.05, 0.05)
        out["oi_velocity"] = oi_vel
        out["oi_acceleration_mso"] = oi_vel.diff(1).clip(-0.05, 0.05)
    else:
        oi_vel = oi.diff(1)
        oi_std = oi.rolling(200, min_periods=30).std().replace(0, np.nan)
        out["oi_velocity"] = (oi_vel / oi_std).clip(-5, 5)
        oi_chg = pd.to_numeric(df_feat.get("oi_change_6", np.nan), errors="coerce")
        oi_acc = oi_chg.diff(1)
        out["oi_acceleration_mso"] = (oi_acc / oi_std).clip(-5, 5)

    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    rng = (h - l).replace(0, np.nan)
    out["wick_rejection_ratio"] = (upper_wick / rng).clip(0, 1)

    fund = pd.to_numeric(df_feat.get("funding_zscore", np.nan), errors="coerce")
    out["funding_acceleration"] = fund.diff(1).diff(1)

    ret = c.pct_change(fill_method=None)
    rv5 = ret.rolling(5, min_periods=3).std()
    rv60 = ret.rolling(60, min_periods=20).std()
    out["realized_vol_ratio"] = rv5 / rv60.replace(0, np.nan)

    out["range_expansion_rate"] = rng.pct_change(3, fill_method=None)

    bb_pct = out["bb_width_pct"]
    atr_exp = out["atr_expansion_ratio"]
    out["compression_score"] = (1.0 - bb_pct) * (1.0 - atr_exp.clip(0, 1))

    fz = pd.to_numeric(df_feat.get("funding_zscore", np.nan), errors="coerce")
    oz = pd.to_numeric(df_feat.get("oi_zscore", np.nan), errors="coerce")
    out["oi_funding_pressure"] = oz * fz

    wick_asym = pd.to_numeric(df_feat.get("wick_asym", np.nan), errors="coerce")
    oi_div = pd.to_numeric(df_feat.get("oi_price_divergence", np.nan), errors="coerce")
    out["stop_hunt_score"] = wick_asym * oi_div

    return out.replace([np.inf, -np.inf], np.nan)


def build_mso_feature_matrix(
    df_v43: pd.DataFrame,
    *,
    df_ohlcv: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Combine v43 base columns (subset) + structural features."""
    base_cols = [c for c in MSO_BASE_V43_FEATURES if c in df_v43.columns]
    missing = [c for c in MSO_BASE_V43_FEATURES if c not in df_v43.columns]
    if missing:
        raise ValueError(f"MSO feature matrix missing v43 columns: {missing[:8]}...")
    base = df_v43[base_cols].copy()
    struct = build_mso_structural_features(df_v43, df_ohlcv=df_ohlcv)
    return pd.concat([base, struct], axis=1)


def build_mso_last_row(
    df_feat: pd.DataFrame,
    *,
    df_ohlcv: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Last row of MSO feature matrix for live inference."""
    full = build_mso_feature_matrix(df_feat, df_ohlcv=df_ohlcv)
    cols = [c for c in MSO_FEATURE_COLS if c in full.columns]
    row = full[cols].iloc[[-1]]
    if row.isna().any(axis=None):
        bad = list(row.columns[row.iloc[0].isna()])
        raise ValueError(
            f"MSO last row has NaN (insufficient history or missing real data): {bad[:6]}"
        )
    return row


def validate_mso_feature_row(row: pd.DataFrame) -> None:
    """Raise if any required MSO feature is NaN."""
    for col in MSO_FEATURE_COLS:
        if col not in row.columns:
            raise ValueError(f"MSO feature row missing column {col!r}")
        val = row[col].iloc[-1]
        if pd.isna(val):
            raise ValueError(f"MSO feature {col!r} is NaN — prediction blocked")
