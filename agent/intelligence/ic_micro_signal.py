"""Feature-based expected_return fallback when IC thesis is flat (NO-ML path)."""

from __future__ import annotations

from typing import Dict

from agent.core.config import settings


def _feat(features: Dict[str, float], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def micro_expected_return_from_features(
    closed_feats: Dict[str, float],
    *,
    threshold: float,
    short_enabled: bool,
) -> float:
    """
    Derive a small signed expected_return from closed-bar momentum when thesis is HOLD.

    Magnitude is sized to clear v43 raw threshold and typical gate-5 edge hurdles.
    """
    ret_1 = _feat(closed_feats, "ret_1")
    trend_mom = _feat(closed_feats, "trend_mom")
    macd = _feat(closed_feats, "macd_hist_n")
    di = _feat(closed_feats, "di_spread")
    body_dir = _feat(closed_feats, "body_dir")

    composite = (
        0.40 * ret_1
        + 0.35 * trend_mom
        + 0.15 * (macd * 1e-4 if abs(macd) > 10.0 else macd)
        + 0.07 * (di * 1e-4)
        + 0.03 * body_dir * 1e-3
    )
    if abs(composite) < 1e-9:
        return 0.0

    thr = max(float(threshold), 1e-6)
    min_mag = thr + 0.0025
    mag = max(min_mag, min(0.015, abs(composite) * 80.0))

    if composite > 0:
        return mag
    if not short_enabled:
        return 0.0
    return -mag


def apply_ic_micro_momentum_er(
    thesis_signal: str,
    primary_er: float,
    closed_feats: Dict[str, float],
    *,
    threshold: float,
    short_enabled: bool,
) -> float:
    """Apply micro-momentum ER only for flat IC thesis with negligible primary_er."""
    if not bool(getattr(settings, "ic_mode", True)):
        return primary_er
    if not bool(getattr(settings, "ic_micro_momentum_enabled", True)):
        return primary_er
    if str(thesis_signal or "").upper() != "HOLD":
        return primary_er
    thr = max(float(threshold), 1e-6)
    if abs(float(primary_er)) >= thr * 0.25:
        return primary_er
    micro = micro_expected_return_from_features(
        closed_feats,
        threshold=thr,
        short_enabled=short_enabled,
    )
    return micro if micro != 0.0 else primary_er
