"""KS-based feature drift detection (aligned with JackSparrow Colab Cell 8)."""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats


def detect_drift(
    df_past: pd.DataFrame,
    df_recent: pd.DataFrame,
    feature_cols: Sequence[str],
    *,
    alpha: float = 0.01,
    stat_threshold: float = 0.10,
) -> List[Tuple[str, float, float]]:
    """Compare past vs recent distributions per feature using two-sample KS.

    Args:
        df_past: Older window (rows).
        df_recent: Recent window (rows).
        feature_cols: Columns to test (must exist in both frames).
        alpha: Significance; drift if p-value < alpha.
        stat_threshold: Minimum KS statistic to count as drifted.

    Returns:
        List of (column_name, p_value, statistic) for drifted features.
    """
    drifted: List[Tuple[str, float, float]] = []
    for col in feature_cols:
        if col not in df_past.columns or col not in df_recent.columns:
            continue
        a = df_past[col].dropna().values.astype(np.float64, copy=False)
        b = df_recent[col].dropna().values.astype(np.float64, copy=False)
        if a.size < 50 or b.size < 50:
            continue
        try:
            result = stats.ks_2samp(a, b)
        except Exception:
            continue
        stat = float(result.statistic)
        p_val = float(result.pvalue)
        if p_val < alpha and stat > stat_threshold:
            drifted.append((col, p_val, stat))
    return drifted


def should_retrain_from_drift(
    drifted: Sequence[Tuple[str, float, float]],
    feature_limit: int,
) -> bool:
    """True when drifted feature count exceeds the configured limit."""
    return len(list(drifted)) > int(feature_limit)


def _psi_1d(
    expected: np.ndarray,
    actual: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    """Population Stability Index (PSI) for two 1-D samples."""
    e = np.asarray(expected, dtype=np.float64).ravel()
    a = np.asarray(actual, dtype=np.float64).ravel()
    e = e[np.isfinite(e)]
    a = a[np.isfinite(a)]
    if e.size < 10 or a.size < 10:
        return 0.0
    qs = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if qs.size < 3:
        return 0.0
    e_counts, _ = np.histogram(e, bins=qs)
    a_counts, _ = np.histogram(a, bins=qs)
    e_tot = max(int(e_counts.sum()), 1)
    a_tot = max(int(a_counts.sum()), 1)
    e_pct = e_counts.astype(np.float64) / e_tot
    a_pct = a_counts.astype(np.float64) / a_tot
    eps = 1e-6
    e_pct = np.clip(e_pct, eps, 1.0)
    a_pct = np.clip(a_pct, eps, 1.0)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def detect_drift_psi(
    df_past: pd.DataFrame,
    df_recent: pd.DataFrame,
    feature_cols: Sequence[str],
    *,
    psi_threshold: float = 0.25,
    bins: int = 10,
) -> List[Tuple[str, float]]:
    """Flag features whose PSI (past vs recent) exceeds ``psi_threshold``."""
    out: List[Tuple[str, float]] = []
    thr = float(psi_threshold)
    for col in feature_cols:
        if col not in df_past.columns or col not in df_recent.columns:
            continue
        a = df_past[col].dropna().values.astype(np.float64, copy=False)
        b = df_recent[col].dropna().values.astype(np.float64, copy=False)
        if a.size < 50 or b.size < 50:
            continue
        psi = _psi_1d(a, b, bins=bins)
        if psi > thr:
            out.append((col, psi))
    return out


def should_retrain_from_psi(
    drifted_psi: Sequence[Tuple[str, float]],
    feature_limit: int,
) -> bool:
    """True when high-PSI feature count exceeds the configured limit."""
    return len(list(drifted_psi)) > int(feature_limit)
