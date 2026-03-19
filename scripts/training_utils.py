"""
Training utilities for ML Pipeline Enhancement.

Provides TP/SL outcome labeling, class weight computation, regime labeling,
and feature importance monitoring for use in training scripts and notebooks.
"""

from collections import Counter
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_class_weight


def create_trade_outcome_labels(
    df: pd.DataFrame,
    tp_pct: float = 0.015,
    sl_pct: float = 0.008,
    fee_pct: float = 0.001,
    max_bars: int = 20,
) -> pd.Series:
    """
    Create labels based on simulated trade outcome (TP/SL hit first).

    For each bar t, simulate entry at close[t]. Scan forward bars t+1 to t+max_bars.
    - If TP hit first -> BUY label (2)
    - If SL hit first -> SELL label (0)
    - If neither within max_bars -> HOLD (1)

    Args:
        df: DataFrame with high, low, close columns
        tp_pct: Take-profit threshold (1.5% default)
        sl_pct: Stop-loss threshold (0.8% default)
        fee_pct: Fee per side (unused in basic version)
        max_bars: Max bars to scan forward

    Returns:
        Series of labels: 0=SELL, 1=HOLD, 2=BUY
    """
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    labels = []
    for i in range(n - max_bars):
        entry = closes[i]
        tp_long = entry * (1 + tp_pct)
        sl_long = entry * (1 - sl_pct)

        label = 1  # HOLD default
        for j in range(1, max_bars + 1):
            if highs[i + j] >= tp_long:
                label = 2  # BUY - TP hit
                break
            if lows[i + j] <= sl_long:
                label = 0  # SELL - SL hit
                break

        labels.append(label)

    # Pad tail with HOLD
    labels.extend([1] * max_bars)
    return pd.Series(labels, index=df.index)


def compute_class_weights(y: np.ndarray) -> dict:
    """
    Compute balanced class weights for XGBoost scale_pos_weight or sample_weight.

    Returns:
        Dict mapping class_id -> weight
    """
    classes = np.unique(y)
    weights = compute_class_weight("balanced", classes=classes, y=y)
    return dict(zip(classes, weights))


def get_scale_pos_weight(y_train: np.ndarray, positive_class: int = 2) -> float:
    """
    Get scale_pos_weight for XGBClassifier when positive_class is BUY (2).

    scale_pos_weight = sum(negative) / sum(positive)
    """
    weights = compute_class_weights(y_train)
    neg_weight = sum(weights.get(c, 1.0) for c in np.unique(y_train) if c != positive_class)
    pos_weight = weights.get(positive_class, 1.0)
    return neg_weight / pos_weight if pos_weight > 0 else 1.0


def label_regime(
    df: pd.DataFrame,
    adx_threshold: float = 25.0,
    atr_zscore_threshold: float = 2.0,
) -> pd.Series:
    """
    Label market regime for each bar.

    0 = Ranging (ADX < 25)
    1 = Trending (ADX >= 25)
    2 = High Volatility (ATR z-score > 2)

    Requires adx and atr columns, or will compute simplified versions.
    """
    if "adx_14" not in df.columns:
        # Simplified ADX
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        plus_dm = h.diff().where((h.diff() > -l.diff()) & (h.diff() > 0), 0)
        minus_dm = (-l.diff()).where((-l.diff() > h.diff()) & (l.diff() < 0), 0)
        atr = tr.rolling(14).mean()
        di_up = 100 * plus_dm.rolling(14).mean() / atr.replace(0, np.nan)
        di_dn = 100 * minus_dm.rolling(14).mean() / atr.replace(0, np.nan)
        adx = (100 * (di_up - di_dn).abs() / (di_up + di_dn + 1e-8)).rolling(14).mean()
    else:
        adx = df["adx_14"]

    if "atr_14" not in df.columns:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
    else:
        atr = df["atr_14"]

    atr_rolling = atr.rolling(50).mean()
    atr_std = atr.rolling(50).std()
    atr_zscore = (atr - atr_rolling) / atr_std.replace(0, np.nan)

    regime = pd.Series(0, index=df.index)
    regime[adx >= adx_threshold] = 1
    regime[atr_zscore > atr_zscore_threshold] = 2
    return regime.fillna(0).astype(int)


def log_feature_importances(
    model,
    feature_names: list,
    pattern_prefixes: tuple = ("cdl_", "chp_", "sr_", "tl_", "bo_"),
) -> None:
    """
    Log feature importances and warn if pattern features have near-zero importance.
    """
    if not hasattr(model, "feature_importances_"):
        return

    import structlog
    logger = structlog.get_logger()

    importances = pd.Series(model.feature_importances_, index=feature_names)
    zero_patterns = importances[
        (importances < 0.001) & (importances.index.str.startswith(pattern_prefixes))
    ]
    if len(zero_patterns) > 5:
        logger.warning(
            "training_many_pattern_features_zero_importance",
            count=len(zero_patterns),
            features=list(zero_patterns.index),
        )
