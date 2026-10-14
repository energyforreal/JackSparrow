"""Feature-label sweep for the frozen 30m / 24-bar XGBoost cell.

Fixes look-ahead in L5 eligibility and L7 scoring, ranks on R-multiples, splits
each spec into opportunity vs direction heads, and screens families plus
individual columns. Injected into the sweep notebook as ``# CELL: FL_SPECS``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

LABEL_LONG = 0
LABEL_SHORT = 1
LABEL_NO_TRADE = 2
LABEL_UNLABELED = -1
TP_FIRST = 0
SL_FIRST = 1
NEITHER = 2
AMBIGUOUS = 3
FROZEN_HORIZON_BARS = 24
FROZEN_RESOLUTION = "30m"
STAGE_B_TREES = 400
STAGE_C_TREES = 400
STAGE_C_TOP_K = 3
SCREEN_SEED = 42
FINALIST_SEEDS: Tuple[int, ...] = (42, 43, 44)
OPP_DEGENERATE_LOW = 0.05
OPP_DEGENERATE_HIGH = 0.95
R_EPS = 1e-12

CURRENT_FEATURE_COLS: Tuple[str, ...] = (
    "ret_1",
    "ret_3_atr",
    "ret_6_atr",
    "ret_12_atr",
    "ret_24_atr",
    "ret_48_atr",
    "ret_144_atr",
    "atr_pct",
    "atr_ratio_84",
    "rv_12_48",
    "rv_48_144",
    "rsi_7",
    "rsi_14",
    "rsi_28",
    "ema_dist_20_atr",
    "ema_slope_20_atr",
    "ema_dist_50_atr",
    "ema_slope_50_atr",
    "ema_dist_200_atr",
    "ema_slope_200_atr",
    "candle_body",
    "upper_wick",
    "lower_wick",
    "range_atr",
    "volume_z_20",
    "volume_z_100",
    "range_pos_24",
    "dist_high_24_atr",
    "dist_low_24_atr",
    "range_pos_72",
    "dist_high_72_atr",
    "dist_low_72_atr",
    "range_pos_144",
    "dist_high_144_atr",
    "dist_low_144_atr",
    "streak",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "ret_lag1_atr",
    "ret_lag2_atr",
    "ret_lag3_atr",
    "ret_lag4_atr",
    "ret_lag5_atr",
    "ret_lag6_atr",
)

F7_COLS: Tuple[str, ...] = (
    "efficiency_24",
    "rv24_over_tp",
    "rv_24",
    "bars_since_2atr_swing",
)

FEATURE_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "F1": (
        "ret_1",
        "ret_3_atr",
        "ret_6_atr",
        "ret_12_atr",
        "ret_24_atr",
        "ret_48_atr",
        "ret_144_atr",
        "streak",
        "ret_lag1_atr",
        "ret_lag2_atr",
        "ret_lag3_atr",
        "ret_lag4_atr",
        "ret_lag5_atr",
        "ret_lag6_atr",
    ),
    "F2": (
        "rsi_7",
        "rsi_14",
        "rsi_28",
        "ema_dist_20_atr",
        "ema_slope_20_atr",
        "ema_dist_50_atr",
        "ema_slope_50_atr",
        "ema_dist_200_atr",
        "ema_slope_200_atr",
    ),
    "F3": ("atr_pct", "atr_ratio_84", "rv_12_48", "rv_48_144"),
    "F4": (
        "range_pos_24",
        "dist_high_24_atr",
        "dist_low_24_atr",
        "range_pos_72",
        "dist_high_72_atr",
        "dist_low_72_atr",
        "range_pos_144",
        "dist_high_144_atr",
        "dist_low_144_atr",
    ),
    "F5": (
        "candle_body",
        "upper_wick",
        "lower_wick",
        "range_atr",
        "volume_z_20",
        "volume_z_100",
    ),
    "F6": ("hour_sin", "hour_cos", "dow_sin", "dow_cos"),
    "F7": F7_COLS,
}

FEATURE_FAMILY_ORDER: Tuple[str, ...] = (
    "F0",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
)

LABEL_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "L0",
        "kind": "barrier",
        "group": "L0",
        "tp_atr_mult": 4.0,
        "sl_atr_mult": 2.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L1_2_2",
        "kind": "barrier",
        "group": "L1",
        "tp_atr_mult": 2.0,
        "sl_atr_mult": 2.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L1_3_3",
        "kind": "barrier",
        "group": "L1",
        "tp_atr_mult": 3.0,
        "sl_atr_mult": 3.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L1_1p5_1p5",
        "kind": "barrier",
        "group": "L1",
        "tp_atr_mult": 1.5,
        "sl_atr_mult": 1.5,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L2_2_1",
        "kind": "barrier",
        "group": "L2",
        "tp_atr_mult": 2.0,
        "sl_atr_mult": 1.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L2_3_1p5",
        "kind": "barrier",
        "group": "L2",
        "tp_atr_mult": 3.0,
        "sl_atr_mult": 1.5,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L3",
        "kind": "barrier",
        "group": "L3",
        "tp_atr_mult": 6.0,
        "sl_atr_mult": 3.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L4",
        "kind": "percent",
        "group": "L4",
        "tp_pct": 0.008,
        "sl_pct": 0.004,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L5",
        "kind": "sign",
        "group": "L5",
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L6",
        "kind": "regression",
        "group": "L6",
        "tp_atr_mult": 4.0,
        "sl_atr_mult": 2.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L7",
        "kind": "decisive",
        "group": "L7",
        "tp_atr_mult": 4.0,
        "sl_atr_mult": 2.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
    {
        "id": "L8",
        "kind": "meta",
        "group": "L8",
        "tp_atr_mult": 4.0,
        "sl_atr_mult": 2.0,
        "horizon_bars": FROZEN_HORIZON_BARS,
    },
)

STAGE_B_REQUIRED: Tuple[str, ...] = (
    "label_id",
    "feature_family",
    "wf_r_expectancy",
    "wf_tstat",
    "wf_positive_share",
    "n_LONG",
    "n_SHORT",
)
STAGE_B_FORBIDDEN: Tuple[str, ...] = (
    "test_score",
    "test_precision_LONG",
    "test_precision_SHORT",
    "test_expectancy",
    "test_r_expectancy",
    "n_test",
    "test_n_LONG",
    "test_n_SHORT",
)

DIAGNOSIS_BARRIER_ABSENT = (
    "the 30m series over 24 bars does not contain this barrier"
)
DIAGNOSIS_FIRST_TOUCH = "the 4 ATR / 2 ATR first-touch rule is the failure"
DIAGNOSIS_VOL_FEATURES = (
    "the missing information is vol relative to the barriers"
)
DIAGNOSIS_SHORT_ABSENT = (
    "the short side is still absent; report sides separately"
)
DIAGNOSIS_INCONCLUSIVE = "inconclusive: no diagnosis rule matched"
DIAGNOSIS_NULL = "best pair does not beat the shuffled-label null"


def label_spec_by_id(spec_id: str) -> Dict[str, Any]:
    """Return a copy of one label spec."""
    for spec in LABEL_SPECS:
        if spec["id"] == spec_id:
            return dict(spec)
    raise KeyError(f"Unknown label spec {spec_id!r}")


def barrier_label_specs() -> Tuple[Dict[str, Any], ...]:
    """Specs that use a first-touch ATR or percent barrier on 24 forward bars."""
    kinds = {"barrier", "percent", "regression", "decisive", "meta"}
    return tuple(dict(s) for s in LABEL_SPECS if s["kind"] in kinds)


def family_columns(family_id: str) -> Tuple[str, ...]:
    """Column names for one feature family. F0 is the current set plus F7."""
    if family_id == "F0":
        return CURRENT_FEATURE_COLS + F7_COLS
    if family_id.startswith("F0_minus_"):
        dropped = family_id.split("F0_minus_", 1)[1]
        drop_set = set(family_columns(dropped))
        return tuple(c for c in family_columns("F0") if c not in drop_set)
    if family_id not in FEATURE_FAMILIES:
        raise KeyError(f"Unknown feature family {family_id!r}")
    return FEATURE_FAMILIES[family_id]


def disjoint_family_ids() -> Tuple[str, ...]:
    """Family ids that must be pairwise disjoint (every family except F0)."""
    return tuple(fid for fid in FEATURE_FAMILY_ORDER if fid != "F0")


def screen_column_sets() -> List[Tuple[str, Tuple[str, ...]]]:
    """Families F0–F7 plus leave-one-family-out from F0."""
    sets: List[Tuple[str, Tuple[str, ...]]] = []
    for fam in FEATURE_FAMILY_ORDER:
        sets.append((fam, family_columns(fam)))
    for fam in disjoint_family_ids():
        name = f"F0_minus_{fam}"
        sets.append((name, family_columns(name)))
    return sets


def spec_f7_kwargs(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Per-spec distances so F7 is not hard-wired to 4/2."""
    horizon = int(spec.get("horizon_bars", FROZEN_HORIZON_BARS))
    if str(spec.get("kind")) == "percent":
        return {
            "tp_pct": float(spec["tp_pct"]),
            "sl_pct": float(spec["sl_pct"]),
            "horizon_bars": horizon,
        }
    if str(spec.get("kind")) == "sign":
        return {"tp_atr_mult": 1.0, "sl_atr_mult": 1.0, "horizon_bars": horizon}
    return {
        "tp_atr_mult": float(spec.get("tp_atr_mult", 4.0)),
        "sl_atr_mult": float(spec.get("sl_atr_mult", 2.0)),
        "horizon_bars": horizon,
    }


def add_f7_features(
    df: pd.DataFrame,
    *,
    tp_atr_mult: float = 4.0,
    sl_atr_mult: float = 2.0,
    tp_pct: Optional[float] = None,
    sl_pct: Optional[float] = None,
    horizon_bars: int = FROZEN_HORIZON_BARS,
) -> pd.DataFrame:
    """Append causal vol-versus-barrier columns. Uses only bars at or before t."""
    out = df.copy()
    close = out["close"].astype(np.float64)
    atr = (
        out["atr"].astype(np.float64)
        if "atr" in out.columns
        else pd.Series(np.nan, index=out.index)
    )
    k = int(horizon_bars)
    log_ret = np.log(close.replace(0.0, np.nan)).diff()
    rv_h = log_ret.rolling(k, min_periods=k).std()
    net = close - close.shift(k)
    path = close.diff().abs().rolling(k, min_periods=k).sum()
    atr_safe = atr.replace(0.0, np.nan)
    close_safe = close.replace(0.0, np.nan)
    atr_pct = atr_safe / close_safe
    if tp_pct is not None:
        tp_dist = pd.Series(float(tp_pct), index=out.index)
    else:
        tp_dist = float(tp_atr_mult) * atr_pct
    move_atr = close.diff().abs() / atr_safe
    is_swing = (move_atr >= 2.0).to_numpy()
    idx = np.arange(len(out), dtype=np.float64)
    last = np.where(is_swing, idx, np.nan)
    last_swing = pd.Series(last, index=out.index).ffill()
    out["efficiency_24"] = net / path.replace(0.0, np.nan)
    out["rv24_over_tp"] = rv_h / tp_dist.replace(0.0, np.nan)
    out["rv_24"] = rv_h
    out["bars_since_2atr_swing"] = idx - last_swing.to_numpy(dtype=np.float64)
    if sl_pct is None:
        _ = sl_atr_mult
    return out


def r_multiple(pnl: np.ndarray, sl_pct: np.ndarray) -> np.ndarray:
    """P&L in stop-distance units. Causal sl_pct only."""
    sl = np.asarray(sl_pct, dtype=np.float64)
    pnl_arr = np.asarray(pnl, dtype=np.float64)
    return pnl_arr / np.where(np.abs(sl) > R_EPS, sl, np.nan)


def _named_labels(labels: np.ndarray) -> np.ndarray:
    names = np.array(["UNLABELED"] * labels.shape[0], dtype=object)
    names[labels == LABEL_LONG] = "LONG"
    names[labels == LABEL_SHORT] = "SHORT"
    names[labels == LABEL_NO_TRADE] = "NO_TRADE"
    return names


def _causal_atr_pct(df: pd.DataFrame) -> np.ndarray:
    close = df["close"].to_numpy(dtype=np.float64)
    if "atr" in df.columns:
        atr = df["atr"].to_numpy(dtype=np.float64)
    else:
        atr = np.full(len(df), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        return atr / np.where(np.abs(close) > R_EPS, close, np.nan)


def _apply_sign_labels(df: pd.DataFrame, *, horizon_bars: int) -> pd.DataFrame:
    """LONG/SHORT from the sign of the 24-bar close-to-close return.

    ``tp_pct`` / ``sl_pct`` are causal ATR fractions, not the forward move.
    """
    out = df.copy().reset_index(drop=True)
    n = len(out)
    k = int(horizon_bars)
    close = out["close"].to_numpy(dtype=np.float64)
    fwd = np.full(n, np.nan, dtype=np.float64)
    if n > k:
        fwd[: n - k] = close[k:]
    with np.errstate(invalid="ignore", divide="ignore"):
        timeout = (fwd - close) / np.where(np.abs(close) > 1e-12, close, np.nan)
    valid = np.isfinite(timeout)
    labels = np.full(n, LABEL_UNLABELED, dtype=np.int64)
    labels[valid & (timeout > 0.0)] = LABEL_LONG
    labels[valid & (timeout < 0.0)] = LABEL_SHORT
    labels[valid & (timeout == 0.0)] = LABEL_NO_TRADE
    long_code = np.full(n, np.nan, dtype=np.float64)
    short_code = np.full(n, np.nan, dtype=np.float64)
    long_code[valid & (timeout > 0.0)] = float(TP_FIRST)
    long_code[valid & (timeout < 0.0)] = float(SL_FIRST)
    long_code[valid & (timeout == 0.0)] = float(NEITHER)
    short_code[valid & (timeout < 0.0)] = float(TP_FIRST)
    short_code[valid & (timeout > 0.0)] = float(SL_FIRST)
    short_code[valid & (timeout == 0.0)] = float(NEITHER)
    atr_pct = _causal_atr_pct(out)
    out["trade_label"] = labels
    out["trade_name"] = _named_labels(labels)
    out["long_pnl_pct"] = np.where(valid, timeout, np.nan)
    out["short_pnl_pct"] = np.where(valid, -timeout, np.nan)
    out["long_code"] = long_code
    out["short_code"] = short_code
    out["long_result"] = np.where(valid, (labels == LABEL_LONG).astype(np.float64), np.nan)
    out["short_result"] = np.where(valid, (labels == LABEL_SHORT).astype(np.float64), np.nan)
    out["timeout_ret"] = np.where(valid, timeout, np.nan)
    out["tp_pct"] = np.where(valid, atr_pct, np.nan)
    out["sl_pct"] = np.where(valid, atr_pct, np.nan)
    if "upside" not in out.columns:
        out["upside"] = np.where(valid, np.maximum(timeout, 0.0), np.nan)
    if "downside" not in out.columns:
        out["downside"] = np.where(valid, np.maximum(-timeout, 0.0), np.nan)
    return out


def _apply_meta_labels(
    labeled: pd.DataFrame, *, cost: float, momentum_col: str = "ret_1"
) -> pd.DataFrame:
    """Keep LONG/SHORT only when a simple momentum entry would have paid the cost."""
    out = labeled.copy()
    if momentum_col in out.columns:
        mom = out[momentum_col].to_numpy(dtype=np.float64)
    else:
        close = out["close"].to_numpy(dtype=np.float64)
        prev = np.where(close[:-1] == 0, np.nan, close[:-1])
        mom = np.concatenate([[np.nan], np.diff(close) / prev])
    long_pnl = out["long_pnl_pct"].to_numpy(dtype=np.float64)
    short_pnl = out["short_pnl_pct"].to_numpy(dtype=np.float64)
    old = out["trade_label"].to_numpy(dtype=np.int64)
    labels = np.full(len(out), LABEL_UNLABELED, dtype=np.int64)
    usable = old >= 0
    labels[usable] = LABEL_NO_TRADE
    long_win = (
        usable
        & np.isfinite(mom)
        & (mom > 0.0)
        & np.isfinite(long_pnl)
        & (long_pnl - float(cost) > 0.0)
    )
    short_win = (
        usable
        & np.isfinite(mom)
        & (mom < 0.0)
        & np.isfinite(short_pnl)
        & (short_pnl - float(cost) > 0.0)
    )
    labels[long_win] = LABEL_LONG
    labels[short_win] = LABEL_SHORT
    out["trade_label"] = labels
    out["trade_name"] = _named_labels(labels)
    return out


def attach_heads(
    labeled: pd.DataFrame, spec: Mapping[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Add opportunity / direction columns. Timeouts stay scored as NO_TRADE."""
    out = labeled.copy()
    labels = out["trade_label"].to_numpy(dtype=np.int64)
    long_c = out["long_code"].to_numpy(dtype=np.float64)
    short_c = out["short_code"].to_numpy(dtype=np.float64)
    valid = labels >= 0
    opp = np.full(len(out), np.nan, dtype=np.float64)
    tp_any = (long_c == float(TP_FIRST)) | (short_c == float(TP_FIRST))
    opp[valid] = tp_any[valid].astype(np.float64)
    out["opp_label"] = np.where(valid, opp, -1.0)
    dir_train = valid & ((labels == LABEL_LONG) | (labels == LABEL_SHORT))
    if str(spec.get("kind")) == "decisive":
        timeout = (
            np.isfinite(long_c)
            & np.isfinite(short_c)
            & (long_c == float(NEITHER))
            & (short_c == float(NEITHER))
        )
        labels = labels.copy()
        labels[timeout & (labels == LABEL_UNLABELED)] = LABEL_NO_TRADE
        out["trade_label"] = labels
        out["trade_name"] = _named_labels(labels)
        valid = labels >= 0
        dir_train = valid & ((labels == LABEL_LONG) | (labels == LABEL_SHORT))
        opp = np.full(len(out), np.nan, dtype=np.float64)
        opp[valid] = tp_any[valid].astype(np.float64)
        out["opp_label"] = np.where(valid, opp, -1.0)
    out["dir_train_mask"] = dir_train
    rate = float(np.nanmean(opp[valid])) if valid.any() else float("nan")
    degen = bool(
        np.isfinite(rate) and (rate >= OPP_DEGENERATE_HIGH or rate <= OPP_DEGENERATE_LOW)
    )
    out["opportunity_degenerate"] = degen
    return out, {"opportunity_rate": rate, "opportunity_degenerate": degen}


def apply_label_spec(
    featured: pd.DataFrame,
    spec: Mapping[str, Any],
    compute_opportunity_labels: Callable[..., pd.DataFrame],
    *,
    atr_period: int = 14,
    round_trip_cost_pct: float = 0.0016,
) -> pd.DataFrame:
    """Rebuild y on the same 24-bar forward path according to ``spec``."""
    horizon = int(spec["horizon_bars"])
    kind = str(spec["kind"])
    if kind == "sign":
        labeled = _apply_sign_labels(featured, horizon_bars=horizon)
    elif kind == "percent":
        tmp = featured.copy()
        tmp["atr"] = tmp["close"].astype(np.float64)
        labeled = compute_opportunity_labels(
            tmp,
            tp_mult=float(spec["tp_pct"]),
            sl_mult=float(spec["sl_pct"]),
            horizon_bars=horizon,
            atr_period=int(atr_period),
        )
        if "atr" in featured.columns:
            labeled["atr"] = featured["atr"].to_numpy(dtype=np.float64)
    else:
        labeled = compute_opportunity_labels(
            featured,
            tp_mult=float(spec["tp_atr_mult"]),
            sl_mult=float(spec["sl_atr_mult"]),
            horizon_bars=horizon,
            atr_period=int(atr_period),
        )
        if kind == "meta":
            labeled = _apply_meta_labels(labeled, cost=float(round_trip_cost_pct))
    labeled, _heads = attach_heads(labeled, spec)
    return labeled


def l7_timeouts_are_scored(labeled: pd.DataFrame) -> bool:
    """True when dual-timeout bars remain in the eval row set as NO_TRADE."""
    long_c = labeled["long_code"].to_numpy(dtype=np.float64)
    short_c = labeled["short_code"].to_numpy(dtype=np.float64)
    labels = labeled["trade_label"].to_numpy(dtype=np.int64)
    timeout = (
        np.isfinite(long_c)
        & np.isfinite(short_c)
        & (long_c == float(NEITHER))
        & (short_c == float(NEITHER))
    )
    if not timeout.any():
        return True
    return bool(np.all(labels[timeout] == LABEL_NO_TRADE))


def stage_a_should_keep(
    report: Mapping[str, Any],
    *,
    minority_rate: float = 0.15,
    allow_degenerate_opp: bool = False,
) -> bool:
    """Keep if both sides exist above the minority floor.

    Exclusive-winner expectancy is reported, never used as the keep rule.
    Degenerate opportunity (~0 or ~1) drops the spec unless it is a
    direction-only label (L5 / ``allow_degenerate_opp``).
    """
    mix = report.get("class_mix") or {}
    long_r = float(mix.get("LONG", report.get("base_long_tp_rate", 0.0)) or 0.0)
    short_r = float(mix.get("SHORT", report.get("base_short_tp_rate", 0.0)) or 0.0)
    if long_r < float(minority_rate) or short_r < float(minority_rate):
        return False
    if allow_degenerate_opp:
        return True
    degen = report.get("opportunity_degenerate")
    if degen is True:
        return False
    rate = report.get("opportunity_rate")
    if rate is not None and np.isfinite(float(rate)):
        value = float(rate)
        if value >= OPP_DEGENERATE_HIGH or value <= OPP_DEGENERATE_LOW:
            return False
    return True


def validate_stage_b_row(row: Mapping[str, Any]) -> bool:
    """Accept a screen row with walk-forward R fields and no test metrics."""
    keys = set(row.keys())
    missing = [k for k in STAGE_B_REQUIRED if k not in keys]
    if missing:
        raise ValueError(f"Stage B row missing fields: {missing}")
    forbidden = [k for k in STAGE_B_FORBIDDEN if k in keys]
    if forbidden:
        raise ValueError(f"Stage B row includes test metrics: {sorted(forbidden)}")
    return True


def select_top_pairs(
    rows: Sequence[Mapping[str, Any]], *, k: int = STAGE_C_TOP_K
) -> List[Dict[str, Any]]:
    """Highest walk-forward R-expectancy first. Percent P&L is not used."""

    def _key(row: Mapping[str, Any]) -> float:
        raw = row.get("wf_r_expectancy", row.get("val_expectancy", float("-inf")))
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return float("-inf")
        return val if np.isfinite(val) else float("-inf")

    ranked = sorted((dict(r) for r in rows), key=_key, reverse=True)
    return ranked[: max(int(k), 0)]


def _rows_for(
    rows: Sequence[Mapping[str, Any]],
    *,
    label_id: Optional[str] = None,
    group: Optional[str] = None,
) -> List[Mapping[str, Any]]:
    out: List[Mapping[str, Any]] = []
    for row in rows:
        if label_id is not None and str(row.get("label_id")) != label_id:
            continue
        if group is not None and str(row.get("label_group", "")) != group:
            lid = str(row.get("label_id", ""))
            if not (lid == group or lid.startswith(f"{group}_")):
                continue
        out.append(row)
    return out


def _wf_positive(row: Mapping[str, Any]) -> bool:
    r = float(row.get("wf_r_expectancy", float("nan")))
    return bool(np.isfinite(r) and r > 0.0)


def diagnose_sweep(
    rows: Sequence[Mapping[str, Any]],
    *,
    shuffle_best_r: Optional[float] = None,
) -> str:
    """Name the failure from walk-forward R-expectancy, not leaked val scores."""
    if not rows:
        return DIAGNOSIS_INCONCLUSIVE
    finite = [
        r
        for r in rows
        if np.isfinite(float(r.get("wf_r_expectancy", float("nan"))))
    ]
    if not finite:
        return DIAGNOSIS_INCONCLUSIVE
    best_r = max(float(r["wf_r_expectancy"]) for r in finite)
    if shuffle_best_r is not None and np.isfinite(float(shuffle_best_r)):
        if best_r <= float(shuffle_best_r):
            return DIAGNOSIS_NULL
    l0 = _rows_for(finite, label_id="L0")
    l0_pos = any(_wf_positive(r) for r in l0)
    l0_by_fam = {str(r.get("feature_family")): r for r in l0}
    vol_pos = any(
        _wf_positive(l0_by_fam[f]) for f in ("F3", "F7") if f in l0_by_fam
    )
    others_pos = any(
        _wf_positive(r)
        for fid, r in l0_by_fam.items()
        if fid not in {"F3", "F7"}
    )
    if l0 and vol_pos and not others_pos:
        return DIAGNOSIS_VOL_FEATURES
    alt = [
        r
        for r in finite
        if str(r.get("label_id")) == "L5" or str(r.get("label_id", "")).startswith("L1")
    ]
    if (not l0_pos) and any(_wf_positive(r) for r in alt):
        return DIAGNOSIS_FIRST_TOUCH
    if l0 and not l0_pos and best_r <= 0.0:
        return DIAGNOSIS_BARRIER_ABSENT
    dir_aucs = [
        float(r["dir_auc"])
        for r in finite
        if r.get("dir_auc") is not None
        and np.isfinite(float(r.get("dir_auc", float("nan"))))
    ]
    if dir_aucs and float(np.mean(dir_aucs)) < 0.52:
        return DIAGNOSIS_SHORT_ABSENT
    return DIAGNOSIS_INCONCLUSIVE


def block_shuffle(values: np.ndarray, *, block: int, rng: np.random.Generator) -> np.ndarray:
    """Permute labels in horizon-length blocks so serial dependence is kept."""
    arr = np.asarray(values)
    n = arr.shape[0]
    k = max(int(block), 1)
    parts = [arr[i : i + k] for i in range(0, n, k)]
    order = rng.permutation(len(parts))
    return np.concatenate([parts[i] for i in order], axis=0)[:n]


def _fit_scaler(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, keepdims=True)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _scale_x(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _xgb_kwargs(config: Mapping[str, Any], n_estimators: int, seed: int) -> Dict[str, Any]:
    return dict(
        n_estimators=int(n_estimators),
        max_depth=int(config["max_depth"]),
        learning_rate=float(config["learning_rate"]),
        min_child_weight=int(config["min_leaf"]),
        subsample=0.8,
        colsample_bytree=0.7,
        reg_lambda=5.0,
        tree_method="hist",
        n_jobs=int(config.get("threads_per_model", 2)),
        verbosity=0,
        random_state=int(seed),
    )


def _align_binary_proba(clf: Any, x: np.ndarray) -> np.ndarray:
    raw = np.asarray(clf.predict_proba(x), dtype=np.float64)
    if raw.ndim == 1:
        return raw.reshape(-1)
    classes = list(np.asarray(getattr(clf, "classes_", [0, 1])).reshape(-1))
    if 1 in classes:
        return raw[:, classes.index(1)]
    if True in classes:
        return raw[:, classes.index(True)]
    return raw[:, -1]


def _align_dir_proba(clf: Any, x: np.ndarray) -> np.ndarray:
    n = x.shape[0]
    full = np.zeros((n, 3), dtype=np.float64)
    if clf is None:
        full[:] = 1.0 / 3.0
        return full
    p_long = _align_binary_proba(clf, x)
    full[:, LABEL_LONG] = p_long
    full[:, LABEL_SHORT] = 1.0 - p_long
    return full


def _roc_auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y).reshape(-1)
    p = np.asarray(p, dtype=np.float64).reshape(-1)
    mask = np.isfinite(p) & np.isfinite(y)
    y, p = y[mask], p[mask]
    if y.size < 8 or len(np.unique(y)) < 2:
        return float("nan")
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y, p))
    except Exception:
        return float("nan")


def _eligible_mask(
    frame: pd.DataFrame, index: np.ndarray, config: Mapping[str, Any]
) -> np.ndarray:
    min_tp = float(config["min_tp_cost_ratio"]) * float(config["round_trip_cost_pct"])
    if "tp_pct" not in frame.columns:
        return np.ones(index.shape[0], dtype=bool)
    tp = frame["tp_pct"].to_numpy(dtype=np.float64)[index]
    finite = np.isfinite(tp)
    if not finite.any():
        return np.ones(index.shape[0], dtype=bool)
    return finite & (tp >= min_tp)


def _usable_rows(frame: pd.DataFrame, feature_cols: Sequence[str]) -> np.ndarray:
    feats = frame.loc[:, list(feature_cols)].to_numpy(dtype=np.float64)
    y = frame["trade_label"].to_numpy(dtype=np.int64)
    ok = (y >= 0) & np.isfinite(feats).all(axis=1)
    return np.flatnonzero(ok).astype(np.int64)


def _selector(all_rows: np.ndarray, split_idx: np.ndarray, n_frame: int) -> np.ndarray:
    allowed = np.zeros(n_frame, dtype=bool)
    idx = np.asarray(split_idx, dtype=np.int64)
    idx = idx[(idx >= 0) & (idx < n_frame)]
    allowed[idx] = True
    return allowed[all_rows]


def weighted_r_score(
    pred: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    sl: np.ndarray,
    min_signals: int,
) -> Dict[str, float]:
    """Trade-count-weighted R-expectancy. No n < min_signals fallback."""
    parts: List[np.ndarray] = []
    n_long = 0
    n_short = 0
    for cls, pnl in ((LABEL_LONG, pnl_long), (LABEL_SHORT, pnl_short)):
        take = pred == cls
        r = r_multiple(pnl[take], sl[take])
        r = r[np.isfinite(r)]
        if cls == LABEL_LONG:
            n_long = int(r.size)
        else:
            n_short = int(r.size)
        if r.size >= int(min_signals):
            parts.append(r)
    if not parts:
        return {
            "r_expectancy": float("-inf"),
            "tstat": float("nan"),
            "n_LONG": float(n_long),
            "n_SHORT": float(n_short),
        }
    pooled = np.concatenate(parts)
    mean_r = float(pooled.mean())
    n = int(pooled.size)
    std = float(pooled.std(ddof=1)) if n > 1 else float("nan")
    tstat = (
        float(mean_r / (std / np.sqrt(n))) if n > 1 and std > 0 else float("nan")
    )
    return {
        "r_expectancy": mean_r,
        "tstat": tstat,
        "n_LONG": float(n_long),
        "n_SHORT": float(n_short),
    }


def _class_precision(y_true: np.ndarray, y_pred: np.ndarray, cls: int) -> float:
    pred = y_pred == cls
    n = int(pred.sum())
    if n == 0:
        return float("nan")
    return float(np.mean(y_true[pred] == cls))


def _fit_opp_dir(
    x_fit: np.ndarray,
    opp_fit: np.ndarray,
    dir_y: np.ndarray,
    dir_ok: np.ndarray,
    *,
    config: Mapping[str, Any],
    n_estimators: int,
    seed: int,
    skip_opp: bool,
) -> Tuple[Any, Any]:
    from xgboost import XGBClassifier

    kwargs = _xgb_kwargs(config, n_estimators, seed)
    opp_clf: Any = None
    if not skip_opp and len(np.unique(opp_fit[np.isfinite(opp_fit)])) >= 2:
        opp_clf = XGBClassifier(
            objective="binary:logistic", eval_metric="logloss", **kwargs
        )
        y_opp = (opp_fit >= 0.5).astype(np.int64)
        opp_clf.fit(x_fit, y_opp)
    dir_clf: Any = None
    mask = np.asarray(dir_ok, dtype=bool).reshape(-1)
    if mask.any() and len(np.unique(dir_y[mask])) >= 2:
        y_dir = (np.asarray(dir_y)[mask] == LABEL_LONG).astype(np.int64)
        dir_clf = XGBClassifier(
            objective="binary:logistic", eval_metric="logloss", **kwargs
        )
        dir_clf.fit(x_fit[mask], y_dir)
    return opp_clf, dir_clf


def _predict_combined(
    opp_clf: Any,
    dir_clf: Any,
    x: np.ndarray,
    skip_opp: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    n = x.shape[0]
    if skip_opp or opp_clf is None:
        p_opp = np.ones(n, dtype=np.float64)
    else:
        p_opp = _align_binary_proba(opp_clf, x)
    p_dir = _align_dir_proba(dir_clf, x)
    return p_opp, p_dir


def _choose_combined_thresholds(
    p_opp: np.ndarray,
    p_dir: np.ndarray,
    pnl_long: np.ndarray,
    pnl_short: np.ndarray,
    sl: np.ndarray,
    eligible: np.ndarray,
    *,
    quantiles: Sequence[float],
    min_signals: int,
    skip_opp: bool,
) -> Dict[str, Optional[float]]:
    best: Dict[str, Optional[float]] = {"OPP": 0.0, "LONG": None, "SHORT": None}
    best_e = float("-inf")
    opp_qs: Sequence[float] = (0.0,) if skip_opp else (0.0, 0.5, 0.8, 0.9)
    p_long, p_short = p_dir[:, LABEL_LONG], p_dir[:, LABEL_SHORT]
    for q_opp in opp_qs:
        if skip_opp:
            thr_opp = 0.0
        elif eligible.any():
            thr_opp = float(np.quantile(p_opp[eligible], q_opp))
        else:
            thr_opp = 0.0
        opp_ok = eligible & (p_opp >= thr_opp)
        for q in quantiles:
            thr_l = float(np.quantile(p_long[opp_ok], float(q))) if opp_ok.any() else 1.0
            thr_s = float(np.quantile(p_short[opp_ok], float(q))) if opp_ok.any() else 1.0
            pred = np.full(p_opp.shape[0], LABEL_NO_TRADE, dtype=np.int64)
            pred[opp_ok & (p_long >= thr_l) & (p_long > p_short)] = LABEL_LONG
            pred[opp_ok & (p_short >= thr_s) & (p_short > p_long)] = LABEL_SHORT
            scored = weighted_r_score(pred, pnl_long, pnl_short, sl, min_signals)
            e = float(scored["r_expectancy"])
            if e > best_e:
                best_e = e
                best = {"OPP": thr_opp, "LONG": thr_l, "SHORT": thr_s}
    return best


def _apply_combined(
    p_opp: np.ndarray,
    p_dir: np.ndarray,
    thr: Mapping[str, Optional[float]],
    eligible: np.ndarray,
) -> np.ndarray:
    pred = np.full(p_opp.shape[0], LABEL_NO_TRADE, dtype=np.int64)
    p_long, p_short = p_dir[:, LABEL_LONG], p_dir[:, LABEL_SHORT]
    opp_ok = eligible & (p_opp >= float(thr.get("OPP") or 0.0))
    if thr.get("LONG") is not None:
        pred[opp_ok & (p_long >= float(thr["LONG"])) & (p_long > p_short)] = LABEL_LONG
    if thr.get("SHORT") is not None:
        pred[opp_ok & (p_short >= float(thr["SHORT"])) & (p_short > p_long)] = LABEL_SHORT
    return pred


def _fold_arrays(
    labeled: pd.DataFrame,
    cols: Sequence[str],
    all_rows: np.ndarray,
    cost: float,
) -> Dict[str, np.ndarray]:
    feats = labeled.loc[:, list(cols)].to_numpy(dtype=np.float64)[all_rows]
    y = labeled["trade_label"].to_numpy(dtype=np.int64)[all_rows]
    opp = labeled["opp_label"].to_numpy(dtype=np.float64)[all_rows]
    dir_ok = labeled["dir_train_mask"].to_numpy(dtype=bool)[all_rows]
    sl = labeled["sl_pct"].to_numpy(dtype=np.float64)[all_rows]
    long_pnl = labeled["long_pnl_pct"].to_numpy(dtype=np.float64)[all_rows] - cost
    short_pnl = labeled["short_pnl_pct"].to_numpy(dtype=np.float64)[all_rows] - cost
    return {
        "feats": feats,
        "y": y,
        "opp": opp,
        "dir_ok": dir_ok,
        "sl": sl,
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "index": labeled.index.to_numpy()[all_rows] if hasattr(labeled.index, "to_numpy") else all_rows,
    }


def walk_forward_pair(
    labeled: pd.DataFrame,
    feature_cols: Sequence[str],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    spec: Mapping[str, Any],
    config: Mapping[str, Any],
    inner_calibration_split: Callable[..., Tuple[np.ndarray, np.ndarray]],
    *,
    n_estimators: int,
    seed: int,
    skip_opp: bool,
) -> Dict[str, Any]:
    """Score one independent pair on expanding walk-forward folds only."""
    cols = [c for c in feature_cols if c in labeled.columns]
    if not cols:
        raise ValueError("No feature columns present for this family")
    all_rows = _usable_rows(labeled, cols)
    n = len(labeled)
    pack = _fold_arrays(labeled, cols, all_rows, float(config["round_trip_cost_pct"]))
    min_n = int(config.get("min_signals", 100))
    quantiles = list(config.get("signal_quantiles", [0.9, 0.8]))
    fold_r: List[float] = []
    fold_t: List[float] = []
    prec_l: List[float] = []
    prec_s: List[float] = []
    opp_aucs: List[float] = []
    dir_aucs: List[float] = []
    n_long_last = 0.0
    n_short_last = 0.0
    last_models: Dict[str, Any] = {}
    for fold_i, (tr_idx, va_idx) in enumerate(wf_folds, start=1):
        fit_idx, calib_idx = inner_calibration_split(
            tr_idx,
            calib_fraction=float(config.get("calib_fraction", 0.15)),
            purge_bars=int(config.get("purge_bars", FROZEN_HORIZON_BARS + 1)),
        )
        sel_fit = _selector(all_rows, fit_idx, n)
        sel_calib = _selector(all_rows, calib_idx, n)
        sel_eval = _selector(all_rows, va_idx, n)
        if not sel_fit.any() or not sel_eval.any() or not sel_calib.any():
            continue
        mean, std = _fit_scaler(pack["feats"][sel_fit])
        x_fit = _scale_x(pack["feats"][sel_fit], mean, std)
        opp_clf, dir_clf = _fit_opp_dir(
            x_fit,
            pack["opp"][sel_fit],
            pack["y"][sel_fit],
            pack["dir_ok"][sel_fit],
            config=config,
            n_estimators=n_estimators,
            seed=int(seed) + fold_i,
            skip_opp=skip_opp,
        )
        p_opp_c, p_dir_c = _predict_combined(
            opp_clf, dir_clf, _scale_x(pack["feats"][sel_calib], mean, std), skip_opp
        )
        p_opp_e, p_dir_e = _predict_combined(
            opp_clf, dir_clf, _scale_x(pack["feats"][sel_eval], mean, std), skip_opp
        )
        elig_c = _eligible_mask(labeled, all_rows[np.flatnonzero(sel_calib)], config)
        elig_e = _eligible_mask(labeled, all_rows[np.flatnonzero(sel_eval)], config)
        thr = _choose_combined_thresholds(
            p_opp_c,
            p_dir_c,
            pack["long_pnl"][sel_calib],
            pack["short_pnl"][sel_calib],
            pack["sl"][sel_calib],
            elig_c,
            quantiles=quantiles,
            min_signals=min_n,
            skip_opp=skip_opp,
        )
        pred = _apply_combined(p_opp_e, p_dir_e, thr, elig_e)
        scored = weighted_r_score(
            pred,
            pack["long_pnl"][sel_eval],
            pack["short_pnl"][sel_eval],
            pack["sl"][sel_eval],
            min_n,
        )
        fold_r.append(float(scored["r_expectancy"]))
        fold_t.append(float(scored["tstat"]))
        y_eval = pack["y"][sel_eval]
        prec_l.append(_class_precision(y_eval, pred, LABEL_LONG))
        prec_s.append(_class_precision(y_eval, pred, LABEL_SHORT))
        opp_aucs.append(_roc_auc((pack["opp"][sel_eval] >= 0.5).astype(int), p_opp_e))
        dec = pack["dir_ok"][sel_eval]
        if dec.any():
            dir_aucs.append(
                _roc_auc((y_eval[dec] == LABEL_LONG).astype(int), p_dir_e[dec, LABEL_LONG])
            )
        n_long_last = float(scored["n_LONG"])
        n_short_last = float(scored["n_SHORT"])
        last_models = {
            "opp_clf": opp_clf,
            "dir_clf": dir_clf,
            "mean": mean,
            "std": std,
            "thr": thr,
            "cols": cols,
        }
    finite_r = [s for s in fold_r if np.isfinite(s) and s > float("-inf") / 2]
    return {
        "wf_r_expectancy": float(np.mean(finite_r)) if finite_r else float("-inf"),
        "wf_tstat": float(np.nanmean(fold_t)) if fold_t else float("nan"),
        "wf_positive_share": (
            float(np.mean([s > 0.0 for s in finite_r])) if finite_r else float("nan")
        ),
        "wf_scores": fold_r,
        "n_LONG": n_long_last,
        "n_SHORT": n_short_last,
        "precision_LONG": float(np.nanmean(prec_l)) if prec_l else float("nan"),
        "precision_SHORT": float(np.nanmean(prec_s)) if prec_s else float("nan"),
        "opp_auc": float(np.nanmean(opp_aucs)) if opp_aucs else float("nan"),
        "dir_auc": float(np.nanmean(dir_aucs)) if dir_aucs else float("nan"),
        "n_features": len(cols),
        "models": last_models,
    }


def confirm_pair_test(
    labeled: pd.DataFrame,
    feature_cols: Sequence[str],
    splits: Mapping[str, np.ndarray],
    spec: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    n_estimators: int,
    seeds: Sequence[int],
    skip_opp: bool,
) -> Dict[str, Any]:
    """Fit on train, thresholds on val, score test once. Average finalist seeds."""
    cols = [c for c in feature_cols if c in labeled.columns]
    all_rows = _usable_rows(labeled, cols)
    n = len(labeled)
    pack = _fold_arrays(labeled, cols, all_rows, float(config["round_trip_cost_pct"]))
    sel_train = _selector(all_rows, splits["train"], n)
    sel_val = _selector(all_rows, splits["val"], n)
    sel_test = _selector(all_rows, splits["test"], n)
    min_n = int(config.get("min_signals", 100))
    quantiles = list(config.get("signal_quantiles", [0.9, 0.8]))
    seed_rows: List[Dict[str, Any]] = []
    for seed in seeds:
        mean, std = _fit_scaler(pack["feats"][sel_train])
        opp_clf, dir_clf = _fit_opp_dir(
            _scale_x(pack["feats"][sel_train], mean, std),
            pack["opp"][sel_train],
            pack["y"][sel_train],
            pack["dir_ok"][sel_train],
            config=config,
            n_estimators=n_estimators,
            seed=int(seed),
            skip_opp=skip_opp,
        )
        p_opp_v, p_dir_v = _predict_combined(
            opp_clf, dir_clf, _scale_x(pack["feats"][sel_val], mean, std), skip_opp
        )
        p_opp_t, p_dir_t = _predict_combined(
            opp_clf, dir_clf, _scale_x(pack["feats"][sel_test], mean, std), skip_opp
        )
        thr = _choose_combined_thresholds(
            p_opp_v,
            p_dir_v,
            pack["long_pnl"][sel_val],
            pack["short_pnl"][sel_val],
            pack["sl"][sel_val],
            _eligible_mask(labeled, all_rows[np.flatnonzero(sel_val)], config),
            quantiles=quantiles,
            min_signals=min_n,
            skip_opp=skip_opp,
        )
        pred = _apply_combined(
            p_opp_t,
            p_dir_t,
            thr,
            _eligible_mask(labeled, all_rows[np.flatnonzero(sel_test)], config),
        )
        scored = weighted_r_score(
            pred,
            pack["long_pnl"][sel_test],
            pack["short_pnl"][sel_test],
            pack["sl"][sel_test],
            min_n,
        )
        seed_rows.append(
            {
                "seed": int(seed),
                "test_r_expectancy": scored["r_expectancy"],
                "test_tstat": scored["tstat"],
                "test_precision_LONG": _class_precision(
                    pack["y"][sel_test], pred, LABEL_LONG
                ),
                "test_precision_SHORT": _class_precision(
                    pack["y"][sel_test], pred, LABEL_SHORT
                ),
                "test_n_LONG": scored["n_LONG"],
                "test_n_SHORT": scored["n_SHORT"],
                "n_test": int(sel_test.sum()),
                "thresholds": thr,
            }
        )
    r_vals = [float(s["test_r_expectancy"]) for s in seed_rows]
    finite = [v for v in r_vals if np.isfinite(v) and v > float("-inf") / 2]
    last = seed_rows[-1] if seed_rows else {}
    return {
        "seeds": seed_rows,
        "test_r_expectancy": float(np.mean(finite)) if finite else float("-inf"),
        "test_n_LONG": last.get("test_n_LONG", 0.0),
        "test_n_SHORT": last.get("test_n_SHORT", 0.0),
        "n_test": last.get("n_test", 0),
        "test_precision_LONG": last.get("test_precision_LONG", float("nan")),
        "test_precision_SHORT": last.get("test_precision_SHORT", float("nan")),
    }


def permutation_importance_r(
    labeled: pd.DataFrame,
    cols: Sequence[str],
    models: Mapping[str, Any],
    spec: Mapping[str, Any],
    config: Mapping[str, Any],
    eval_idx: np.ndarray,
    *,
    skip_opp: bool,
    rng: np.random.Generator,
) -> List[Dict[str, Any]]:
    """Permute one column at a time on WF eval features; no test rows."""
    if not models or (
        models.get("dir_clf") is None and models.get("opp_clf") is None
    ):
        return []
    all_rows = _usable_rows(labeled, cols)
    n = len(labeled)
    pack = _fold_arrays(labeled, cols, all_rows, float(config["round_trip_cost_pct"]))
    sel = _selector(all_rows, eval_idx, n)
    if not sel.any():
        return []
    mean, std = models["mean"], models["std"]
    x = _scale_x(pack["feats"][sel], mean, std)
    p_opp, p_dir = _predict_combined(
        models.get("opp_clf"), models.get("dir_clf"), x, skip_opp
    )
    elig = _eligible_mask(labeled, all_rows[np.flatnonzero(sel)], config)
    pred0 = _apply_combined(p_opp, p_dir, models["thr"], elig)
    base = weighted_r_score(
        pred0,
        pack["long_pnl"][sel],
        pack["short_pnl"][sel],
        pack["sl"][sel],
        int(config.get("min_signals", 100)),
    )["r_expectancy"]
    out: List[Dict[str, Any]] = []
    col_index = {c: i for i, c in enumerate(cols)}
    for col in cols:
        x_p = x.copy()
        x_p[:, col_index[col]] = rng.permutation(x_p[:, col_index[col]])
        p_o, p_d = _predict_combined(
            models.get("opp_clf"), models.get("dir_clf"), x_p, skip_opp
        )
        pred = _apply_combined(p_o, p_d, models["thr"], elig)
        scored = weighted_r_score(
            pred,
            pack["long_pnl"][sel],
            pack["short_pnl"][sel],
            pack["sl"][sel],
            int(config.get("min_signals", 100)),
        )
        out.append(
            {
                "column": col,
                "delta_r": float(base - scored["r_expectancy"])
                if np.isfinite(base) and np.isfinite(scored["r_expectancy"])
                else float("nan"),
            }
        )
    out.sort(key=lambda r: float(r["delta_r"]) if np.isfinite(r["delta_r"]) else -1e9, reverse=True)
    return out


def _print_stage_frame(name: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Print every row of a stage table (not just the top 3)."""
    print(f"\n===== {name} =====")
    if not rows:
        print("(empty)")
        return
    frame = pd.DataFrame([dict(r) for r in rows])
    nested = [
        c
        for c in frame.columns
        if frame[c].map(lambda v: isinstance(v, (dict, list))).any()
    ]
    show = frame.drop(columns=nested) if nested else frame
    with pd.option_context(
        "display.max_rows",
        None,
        "display.max_columns",
        None,
        "display.width",
        220,
    ):
        print(show.to_string(index=False))


def run_feature_label_sweep(
    featured: pd.DataFrame,
    *,
    config: Mapping[str, Any],
    compute_opportunity_labels: Callable[..., pd.DataFrame],
    summarize_label_gate: Callable[..., Dict[str, Any]],
    splits: Mapping[str, np.ndarray],
    wf_folds: Sequence[Tuple[np.ndarray, np.ndarray]],
    inner_calibration_split: Callable[..., Tuple[np.ndarray, np.ndarray]],
    export_dir: Path,
    n_estimators_stage_b: int = STAGE_B_TREES,
    n_estimators_stage_c: int = STAGE_C_TREES,
    top_k: int = STAGE_C_TOP_K,
) -> Dict[str, Any]:
    """Walk-forward screen, column search on finalists, one test look."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    seed = int(config.get("seed", SCREEN_SEED))
    rng = np.random.default_rng(seed)
    trees = int(n_estimators_stage_b)
    stage_a: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    labeled_by_id: Dict[str, pd.DataFrame] = {}
    skip_opp_by_id: Dict[str, bool] = {}
    for spec in LABEL_SPECS:
        frame = add_f7_features(featured, **spec_f7_kwargs(spec))
        labeled = apply_label_spec(
            frame,
            spec,
            compute_opportunity_labels,
            atr_period=int(config.get("atr_period", 14)),
            round_trip_cost_pct=float(config["round_trip_cost_pct"]),
        )
        valid = labeled["trade_label"].to_numpy() >= 0
        opp = labeled["opp_label"].to_numpy(dtype=np.float64)
        rate = float(np.nanmean(opp[valid])) if valid.any() else float("nan")
        degen = bool(np.asarray(labeled["opportunity_degenerate"]).reshape(-1)[0])
        heads = {"opportunity_rate": rate, "opportunity_degenerate": degen}
        report = summarize_label_gate(
            labeled,
            train_fraction=float(config["train_fraction"]),
            round_trip_cost_pct=float(config["round_trip_cost_pct"]),
            minority_rate=float(config["minority_rate"]),
            ambiguous_win_max=float(config["ambiguous_win_max"]),
            min_tp_cost_ratio=float(config["min_tp_cost_ratio"]),
        )
        report = {**report, **heads}
        keep = stage_a_should_keep(
            report,
            minority_rate=float(config["minority_rate"]),
            allow_degenerate_opp=str(spec.get("kind")) == "sign",
        )
        row = {
            "label_id": spec["id"],
            "label_group": spec.get("group", spec["id"]),
            "kind": spec["kind"],
            "horizon_bars": int(spec["horizon_bars"]),
            "kept": keep,
            **report,
        }
        stage_a.append(row)
        be = report.get("breakeven_win_rate")
        long_tp = report.get("base_long_tp_rate")
        short_tp = report.get("base_short_tp_rate")
        print(
            f"Stage A {spec['id']}: keep={keep} "
            f"opp={heads['opportunity_rate']:.3f} "
            f"degen={heads['opportunity_degenerate']} "
            f"BE={be} base_tp L/S={long_tp}/{short_tp}"
        )
        if keep:
            kept.append(dict(spec))
            labeled_by_id[spec["id"]] = labeled
            skip_opp_by_id[spec["id"]] = bool(heads["opportunity_degenerate"])

    col_sets = screen_column_sets()
    stage_b: List[Dict[str, Any]] = []
    models_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for spec in kept:
        skip_opp = skip_opp_by_id[spec["id"]]
        for fam, cols in col_sets:
            print(f"WF {spec['id']} x {fam} ({len(cols)} cols)")
            scored = walk_forward_pair(
                labeled_by_id[spec["id"]],
                cols,
                wf_folds,
                spec,
                config,
                inner_calibration_split,
                n_estimators=trees,
                seed=seed,
                skip_opp=skip_opp,
            )
            gate = next(r for r in stage_a if r["label_id"] == spec["id"])
            row = {
                "label_id": spec["id"],
                "label_group": spec.get("group", spec["id"]),
                "feature_family": fam,
                "kind": spec["kind"],
                "breakeven_win_rate": gate.get("breakeven_win_rate"),
                "opportunity_rate": gate.get("opportunity_rate"),
                "wf_r_expectancy": scored["wf_r_expectancy"],
                "wf_tstat": scored["wf_tstat"],
                "wf_positive_share": scored["wf_positive_share"],
                "n_LONG": scored["n_LONG"],
                "n_SHORT": scored["n_SHORT"],
                "precision_LONG": scored["precision_LONG"],
                "precision_SHORT": scored["precision_SHORT"],
                "opp_auc": scored["opp_auc"],
                "dir_auc": scored["dir_auc"],
                "n_features": scored["n_features"],
            }
            validate_stage_b_row(row)
            stage_b.append(row)
            models_by_pair[(spec["id"], fam)] = scored.get("models") or {}

    shuffle_best = float("-inf")
    shuffle_rows: List[Dict[str, Any]] = []
    for spec in kept:
        lab = labeled_by_id[spec["id"]].copy()
        lab["trade_label"] = block_shuffle(
            lab["trade_label"].to_numpy(), block=FROZEN_HORIZON_BARS, rng=rng
        )
        lab["opp_label"] = block_shuffle(
            lab["opp_label"].to_numpy(), block=FROZEN_HORIZON_BARS, rng=rng
        )
        lab["dir_train_mask"] = (lab["trade_label"].to_numpy() == LABEL_LONG) | (
            lab["trade_label"].to_numpy() == LABEL_SHORT
        )
        for fam, cols in col_sets:
            print(f"Shuffle WF {spec['id']} x {fam}")
            scored = walk_forward_pair(
                lab,
                cols,
                wf_folds,
                spec,
                config,
                inner_calibration_split,
                n_estimators=trees,
                seed=seed + 99,
                skip_opp=skip_opp_by_id[spec["id"]],
            )
            shuffle_rows.append(
                {
                    "label_id": spec["id"],
                    "feature_family": fam,
                    "wf_r_expectancy": scored["wf_r_expectancy"],
                }
            )
            val = float(scored["wf_r_expectancy"])
            if np.isfinite(val) and val > shuffle_best:
                shuffle_best = val

    top_pairs = select_top_pairs(stage_b, k=int(top_k))
    unique_specs: List[str] = []
    for pair in top_pairs:
        lid = str(pair["label_id"])
        if lid not in unique_specs:
            unique_specs.append(lid)
        if len(unique_specs) >= 2:
            break
    if not unique_specs and kept:
        unique_specs = [kept[0]["id"]]

    drop_rows: List[Dict[str, Any]] = []
    perm_rows: List[Dict[str, Any]] = []
    last_va = wf_folds[-1][1] if wf_folds else splits["val"]
    for spec_id in unique_specs:
        spec = label_spec_by_id(spec_id)
        spec_rows = [r for r in stage_b if r["label_id"] == spec_id]
        if not spec_rows:
            continue
        winner = select_top_pairs(spec_rows, k=1)[0]
        win_set = str(winner["feature_family"])
        win_cols = list(family_columns(win_set))
        skip_opp = skip_opp_by_id[spec_id]
        bases: List[Tuple[str, List[str]]] = [(win_set, win_cols)]
        if win_set != "F0" and win_set in FEATURE_FAMILY_ORDER:
            bases.append(("F0", list(family_columns("F0"))))
        for base_name, base_cols in bases:
            base_row = next(
                (r for r in spec_rows if r["feature_family"] == base_name),
                winner if base_name == win_set else None,
            )
            base_r = (
                float(base_row["wf_r_expectancy"])
                if base_row is not None
                else float("nan")
            )
            for drop in base_cols:
                left = [c for c in base_cols if c != drop]
                if len(left) < 2:
                    continue
                print(f"Drop-one {spec_id} {base_name} -{drop}")
                scored = walk_forward_pair(
                    labeled_by_id[spec_id],
                    left,
                    wf_folds,
                    spec,
                    config,
                    inner_calibration_split,
                    n_estimators=trees,
                    seed=seed,
                    skip_opp=skip_opp,
                )
                delta = (
                    float(base_r - scored["wf_r_expectancy"])
                    if np.isfinite(base_r) and np.isfinite(scored["wf_r_expectancy"])
                    else float("nan")
                )
                drop_rows.append(
                    {
                        "label_id": spec_id,
                        "dropped": drop,
                        "base_family": base_name,
                        "wf_r_expectancy": scored["wf_r_expectancy"],
                        "dir_auc": scored["dir_auc"],
                        "delta_r": delta,
                    }
                )
        models = models_by_pair.get((spec_id, win_set)) or {}
        perm_rows.extend(
            [
                {**r, "label_id": spec_id, "feature_family": win_set}
                for r in permutation_importance_r(
                    labeled_by_id[spec_id],
                    [c for c in win_cols if c in labeled_by_id[spec_id].columns],
                    models,
                    spec,
                    config,
                    last_va,
                    skip_opp=skip_opp,
                    rng=rng,
                )
            ]
        )

    stage_c: List[Dict[str, Any]] = []
    for pair in top_pairs:
        spec = label_spec_by_id(str(pair["label_id"]))
        cols = family_columns(str(pair["feature_family"]))
        print(f"Stage C {spec['id']} x {pair['feature_family']} seeds={FINALIST_SEEDS}")
        confirmed = confirm_pair_test(
            labeled_by_id[spec["id"]],
            cols,
            splits,
            spec,
            config,
            n_estimators=int(n_estimators_stage_c),
            seeds=FINALIST_SEEDS,
            skip_opp=skip_opp_by_id[spec["id"]],
        )
        try:
            wf_share = float(pair.get("wf_positive_share"))
        except (TypeError, ValueError):
            wf_share = 0.0
        try:
            wf_r = float(pair.get("wf_r_expectancy"))
        except (TypeError, ValueError):
            wf_r = float("nan")
        try:
            test_r = float(confirmed.get("test_r_expectancy"))
        except (TypeError, ValueError):
            test_r = float("nan")
        counts = bool(
            wf_share >= (2.0 / 3.0)
            and np.isfinite(wf_r)
            and wf_r > shuffle_best
            and np.isfinite(test_r)
            and test_r > 0.0
        )
        stage_c.append(
            {
                "label_id": spec["id"],
                "feature_family": pair["feature_family"],
                "wf_r_expectancy": pair.get("wf_r_expectancy"),
                "wf_positive_share": pair.get("wf_positive_share"),
                **{k: v for k, v in confirmed.items() if k != "seeds"},
                "seed_rows": confirmed["seeds"],
                "counts": counts,
            }
        )

    diagnosis = diagnose_sweep(stage_b, shuffle_best_r=shuffle_best)
    _print_stage_frame("Stage A", stage_a)
    _print_stage_frame("Stage B (walk-forward R)", stage_b)
    _print_stage_frame("Shuffle null", shuffle_rows)
    _print_stage_frame("Drop-one", drop_rows)
    _print_stage_frame("Permutation", perm_rows)
    _print_stage_frame("Stage C (test once)", stage_c)
    payload = {
        "resolution": str(config.get("resolution", FROZEN_RESOLUTION)),
        "horizon_bars": int(config.get("horizon_bars", FROZEN_HORIZON_BARS)),
        "model": "XGB",
        "n_estimators": trees,
        "stage_a": stage_a,
        "stage_a_kept": [s["id"] for s in kept],
        "stage_b": stage_b,
        "shuffle_best_r": shuffle_best,
        "shuffle_rows": shuffle_rows,
        "drop_one": drop_rows,
        "permutation": perm_rows,
        "top_pairs": top_pairs,
        "stage_c": stage_c,
        "diagnosis": diagnosis,
    }
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "sweep.json").write_text(
        json.dumps(payload, indent=2, default=float),
        encoding="utf-8",
    )
    print("wrote", export_dir / "sweep.json")
    print("diagnosis", diagnosis)
    return payload
