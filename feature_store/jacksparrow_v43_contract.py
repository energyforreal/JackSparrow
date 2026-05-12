"""Canonical v43 training contract (JackSparrow notebook ↔ agent parity).

Feature order must match exported ``metadata_v*.json`` ``features`` array and
notebook ``FEATURE_COLS_V25``. Target horizon: 120×5m bars (~10h simple return).
"""

from __future__ import annotations

# Forward return label in training: close[t+h]/close[t] - 1 on 5m bars
V43_FORWARD_TARGET_BARS = 120

# Ordered list — do not reorder without retraining and re-exporting metadata
V43_CANONICAL_FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_6",
    "ret_24",
    "mom_accel",
    "ema_21_50_cross",
    "price_ema21",
    "price_ema100",
    "rsi_14",
    "rsi_mom",
    "macd_hist_n",
    "bb_width",
    "bb_pos",
    "atr_pct",
    "vol_regime",
    "adx_14",
    "di_spread",
    "kauf_er_20",
    "obv_ret",
    "cmf_20",
    "session_vwap_dev",
    "body",
    "body_dir",
    "wick_asym",
    "sr_compression",
    "hour_sin",
    "hour_cos",
    "hurst_60",
    "trend_mom",
    "trend_conf",
    "funding_zscore",
    "funding_mom",
    "h_ret_1",
    "h_trend",
    "h_trend_200",
    "h_rsi_14",
    "h1_trend",
    "h1_rsi_14",
    "h1_adx",
    "h1_vol_regime",
    "bull_bar",
)

V43_EXPECTED_FEATURE_COUNT = len(V43_CANONICAL_FEATURES)
