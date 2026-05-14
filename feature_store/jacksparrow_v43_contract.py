"""Canonical v43 training contract (JackSparrow notebook ↔ agent parity).

Feature order must match exported ``metadata_v*.json`` ``features`` array and
notebook ``FEATURE_COLS_V25``. Target horizon: 120×5m bars (~10h simple return).

Train/serve map: see ``docs/feature_entrypoints_audit.md``.
"""

from __future__ import annotations

from typing import Any, Mapping

# Bump when ``V43_CANONICAL_FEATURES`` or semantics change (retrain + re-export metadata).
V43_COMPATIBLE_FEATURE_VERSION = "jacksparrow_v43_features_v1"

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


def validate_v43_metadata_compatibility(meta: Mapping[str, Any]) -> None:
    """Reject loads when feature list or optional ``compatible_feature_version`` disagrees with agent.

    Args:
        meta: Parsed ``metadata_v*.json`` for a JackSparrow v43 bundle.

    Raises:
        ValueError: On missing features, order mismatch, or incompatible version tag.
    """
    feats = meta.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("v43 metadata missing non-empty features list")
    ordered = tuple(str(x) for x in feats)
    if ordered != V43_CANONICAL_FEATURES:
        raise ValueError(
            "v43 metadata features[] does not match V43_CANONICAL_FEATURES "
            "(train-serve order-sensitive contract)"
        )
    ver = meta.get("compatible_feature_version")
    if ver is None or (isinstance(ver, str) and not ver.strip()):
        return
    if str(ver).strip() != V43_COMPATIBLE_FEATURE_VERSION:
        raise ValueError(
            f"v43 metadata compatible_feature_version={ver!r} incompatible with "
            f"agent {V43_COMPATIBLE_FEATURE_VERSION!r}; re-export metadata or align contract"
        )
