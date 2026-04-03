"""
perpetual_features.py
Computes futures-specific derived features from the merged feature matrix.
All features are designed to be train/serve consistent.
"""
import numpy as np
import pandas as pd


def compute_perpetual_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)

    # ── Basis Features ────────────────────────────────────────────────────
    out["basis"] = df["mark_price"] - df["close"]
    out["basis_pct"] = out["basis"] / df["close"].replace(0, np.nan)
    out["basis_zscore"] = (
        (out["basis_pct"] - out["basis_pct"].rolling(48).mean())
        / out["basis_pct"].rolling(48).std().replace(0, np.nan)
    )
    out["basis_direction"] = np.sign(out["basis"])

    # ── Funding Rate Features ─────────────────────────────────────────────
    out["funding_rate"] = df["funding_rate"].fillna(0.0)
    out["funding_cumsum_3"] = out["funding_rate"].rolling(3).sum()
    funding_mean = out["funding_rate"].rolling(168).mean()
    funding_std = out["funding_rate"].rolling(168).std().replace(0, np.nan)
    out["funding_zscore"] = (out["funding_rate"] - funding_mean) / funding_std
    out["funding_spike"] = (out["funding_zscore"].abs() > 2.0).astype(float)
    out["funding_sign"] = np.sign(out["funding_rate"])

    # ── Open Interest Features ────────────────────────────────────────────
    oi = df["open_interest"].ffill().fillna(0.0)
    out["oi"] = oi
    out["oi_change_pct"] = oi.pct_change().fillna(0.0)
    out["oi_change_5"] = oi.pct_change(5).fillna(0.0)
    price_dir = np.sign(df["close"].diff().fillna(0.0))
    oi_dir = np.sign(oi.diff().fillna(0.0))
    out["oi_price_confirm"] = (price_dir == oi_dir).astype(float) * 2 - 1
    oi_mean = oi.rolling(336).mean()
    oi_std = oi.rolling(336).std().replace(0, np.nan)
    out["oi_zscore"] = (oi - oi_mean) / oi_std

    # ── Squeeze Risk ──────────────────────────────────────────────────────
    out["long_squeeze_risk"] = (
        (out["funding_sign"] > 0) &
        (out["funding_spike"] > 0) &
        (out["oi_change_pct"] < -0.01)
    ).astype(float)

    out["short_squeeze_risk"] = (
        (out["funding_sign"] < 0) &
        (out["funding_spike"] > 0) &
        (out["oi_change_pct"] < -0.01)
    ).astype(float)

    return out.replace([np.inf, -np.inf], 0.0).fillna(0.0)


PERPETUAL_FEATURE_NAMES = [
    "basis", "basis_pct", "basis_zscore", "basis_direction",
    "funding_rate", "funding_cumsum_3", "funding_zscore",
    "funding_spike", "funding_sign",
    "oi", "oi_change_pct", "oi_change_5", "oi_price_confirm", "oi_zscore",
    "long_squeeze_risk", "short_squeeze_risk",
    "ob_imbalance",
]
