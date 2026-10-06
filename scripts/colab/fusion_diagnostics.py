"""v15 fusion diagnostics. No Transformer training.

Answers whether chance-level Colab direction skill is a label bug, a
lookahead leak, or a state that does not determine the frozen-theta class.
Walk-forward Transformer, Optuna, SHAP, and ONNX export stay out of this
module.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import NearestNeighbors

from feature_store.transformer_btcusd.contract import (
    FUSION_EMBARGO_BARS,
    FUSION_INPUT_RESOLUTIONS,
    LABEL_V2_DIRECTION_CARDINALITY,
    LABEL_V2_DIRECTION_NAMES,
    LABEL_V2_DURATION_ATR_MULT,
    LABEL_V2_HORIZON_BARS_5M,
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_THETA_FROZEN,
    RESOLUTION_MINUTES,
    fusion_feature_cols_v14,
)
from feature_store.transformer_btcusd.mtf_features import (
    add_native_tf_features,
    scale_v14_feature_window,
)
from feature_store.transformer_btcusd.mtf_frames import (
    assert_no_lookahead,
    build_10m_ohlcv_from_5m,
)
from feature_store.transformer_btcusd.mtf_labels import trim_label_v2_tail
from feature_store.transformer_btcusd.mtf_labels_v2 import (
    compute_fusion_path_targets,
    direction_from_return_array,
    summarize_label_v2,
)

_EPS = 1e-9
_BEAR = 0
_NEUTRAL = 1
_BULL = 2

DIAG_THETA_GRID: Tuple[float, ...] = (
    0.20,
    0.25,
    0.30,
    0.40,
    0.50,
    0.60,
    0.75,
    0.80,
    1.00,
)
COST_ATR: Tuple[float, ...] = (0.0, 0.02, 0.05, 0.10)
BASELINE_MARGIN = 0.02
KNN_TV_NEAR = 0.10
TRANSFORMER_CHANCE_MAX = 0.40
# Validation balanced accuracy from the v14 Colab run this gate replaces.
PUBLISHED_TRANSFORMER_BALANCED_ACC: Dict[str, float] = {
    "h30m": 0.337,
    "h1h": 0.365,
}
MOMENTUM_COL = "rsi_14"
RETURN_COL = "ret_1"
FeatureFn = Callable[[pd.DataFrame], pd.DataFrame]


def _jsonify(value: Any) -> Any:
    """Cast numpy scalars so the report dumps as JSON."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        val = float(value)
        return val if np.isfinite(val) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [_jsonify(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    return value


def _causal_atr(df: pd.DataFrame) -> np.ndarray:
    """Causal ATR at t. Uses an ``atr`` column when present."""
    n = len(df)
    if "atr" in df.columns:
        atr = df["atr"].to_numpy(dtype=np.float64)
        if np.isfinite(atr).any():
            return atr
    close = df["close"].to_numpy(dtype=np.float64)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    prev = np.concatenate([[close[0]], close[:-1]]) if n else close
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    return (
        pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy(dtype=np.float64)
    )


def _pair_key(sl_mult: float, tp_mult: float) -> str:
    return f"sl{float(sl_mult):.2f}_tp{float(tp_mult):.2f}"


def _theta_key(theta: float) -> str:
    return f"{float(theta):.2f}"


def purged_index_slices(
    n: int,
    *,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
    embargo_bars: int = FUSION_EMBARGO_BARS,
) -> Dict[str, slice]:
    """Match ``split_purged_windows`` in ``mtf_fusion_research`` (no torch)."""
    train_end = int(n * float(train_frac))
    val_end = train_end + int(n * float(val_frac))
    embargo = int(embargo_bars)
    return {
        "train": slice(0, train_end),
        "val": slice(train_end + embargo, val_end),
        "test": slice(val_end + embargo, n),
    }


def walk_forward_slices(
    n: int,
    *,
    folds: int = 3,
    embargo: int = FUSION_EMBARGO_BARS,
) -> List[Tuple[slice, slice]]:
    """Match ``walk_forward_slices`` in ``mtf_fusion_research`` (no torch)."""
    folds_n = max(int(folds), 1)
    out: List[Tuple[slice, slice]] = []
    for i in range(folds_n):
        train_end = max(2, int(n * (0.50 + 0.10 * i)))
        val_end = min(n, train_end + max(int(n * 0.12), 8))
        gap = min(max(int(embargo), 0), max(0, val_end - train_end - 1))
        val_start = train_end + gap
        if val_start >= val_end:
            continue
        out.append((slice(0, train_end), slice(val_start, val_end)))
    return out


def balanced_accuracy(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = LABEL_V2_DIRECTION_CARDINALITY,
) -> float:
    """Mean per-class recall. Empty classes are skipped."""
    scores: List[float] = []
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_pred, dtype=np.int64)
    for c in range(int(n_classes)):
        mask = yt == c
        if not np.any(mask):
            continue
        scores.append(float(np.mean(yp[mask] == c)))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def raw_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Share of matching labels on rows with ``y_true >= 0``."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_pred, dtype=np.int64)
    valid = yt >= 0
    if not np.any(valid):
        return 0.0
    return float(np.mean(yp[valid] == yt[valid]))


def nonoverlap_indices(indices: np.ndarray, min_gap: int) -> np.ndarray:
    """Keep increasing indices at least ``min_gap`` bars apart."""
    ordered = np.asarray(indices, dtype=np.int64)
    if ordered.size == 0:
        return ordered
    ordered = np.sort(ordered)
    keep: List[int] = []
    last = None
    gap = max(int(min_gap), 1)
    for idx in ordered:
        if last is None or int(idx) - int(last) >= gap:
            keep.append(int(idx))
            last = int(idx)
    return np.asarray(keep, dtype=np.int64)


def horizon_bars_map() -> Dict[str, int]:
    """Horizon key to 5m bar count."""
    return {str(k): int(b) for k, b in zip(LABEL_V2_HORIZON_KEYS, LABEL_V2_HORIZON_BARS_5M)}


def recompute_horizon_return(
    close: np.ndarray,
    atr: np.ndarray,
    index: int,
    bars: int,
) -> float:
    """``(Close[t+k] - Close[t]) / ATR[t]``. Path starts at t+1; uses Close[t+k]."""
    i = int(index)
    k = int(bars)
    if i < 0 or k <= 0 or i + k >= len(close):
        return float("nan")
    denom = max(float(atr[i]), _EPS)
    return float((float(close[i + k]) - float(close[i])) / denom)


def audit_label_index(
    labeled: pd.DataFrame,
    *,
    sample_indices: Sequence[int],
    thetas: Optional[Mapping[str, float]] = None,
    atol: float = 1e-6,
) -> Dict[str, Any]:
    """Recompute stored ``{h}_ret`` and frozen-theta class at sample rows.

    Args:
        labeled: Output of ``compute_fusion_path_targets``.
        sample_indices: Row positions on the 5m clock.
        thetas: Per-horizon dead zone. Defaults to frozen theta.
        atol: Absolute tolerance on ATR-normalized return.

    Returns:
        JSON-ready audit with ``ok`` false on any mismatch.
    """
    theta_map = dict(LABEL_V2_THETA_FROZEN)
    if thetas is not None:
        theta_map.update({str(k): float(v) for k, v in thetas.items()})
    close = labeled["close"].to_numpy(dtype=np.float64)
    atr = _causal_atr(labeled)
    bars = horizon_bars_map()
    mismatches: List[Dict[str, Any]] = []
    checked = 0
    for idx in sample_indices:
        i = int(idx)
        if i < 0 or i >= len(labeled):
            continue
        for key, k in bars.items():
            stored = float(labeled.iloc[i][f"{key}_ret"])
            recomputed = recompute_horizon_return(close, atr, i, k)
            if not np.isfinite(stored) or not np.isfinite(recomputed):
                if np.isfinite(stored) != np.isfinite(recomputed):
                    mismatches.append(
                        {
                            "index": i,
                            "horizon": key,
                            "reason": "finite_mismatch",
                            "stored": stored,
                            "recomputed": recomputed,
                        }
                    )
                continue
            checked += 1
            if abs(stored - recomputed) > float(atol):
                mismatches.append(
                    {
                        "index": i,
                        "horizon": key,
                        "reason": "return_mismatch",
                        "stored": stored,
                        "recomputed": recomputed,
                    }
                )
                continue
            stored_dir = int(
                direction_from_return_array(np.array([stored]), theta_map[key])[0]
            )
            recompute_dir = int(
                direction_from_return_array(np.array([recomputed]), theta_map[key])[0]
            )
            if stored_dir != recompute_dir:
                mismatches.append(
                    {
                        "index": i,
                        "horizon": key,
                        "reason": "class_mismatch",
                        "stored_dir": stored_dir,
                        "recomputed_dir": recompute_dir,
                    }
                )
    return _jsonify(
        {
            "ok": len(mismatches) == 0,
            "checked": checked,
            "n_samples": int(len(sample_indices)),
            "mismatches": mismatches[:50],
            "n_mismatches": len(mismatches),
        }
    )


def class_intervals_disjoint(
    ret: np.ndarray,
    dirs: np.ndarray,
    *,
    theta: float,
    atol: float = 1e-9,
) -> Dict[str, Any]:
    """True when BEAR / NEUTRAL / BULL are disjoint cuts of ``ret``.

    Overlap is an indexing bug, not evidence the classes are noisy.
    """
    r = np.asarray(ret, dtype=np.float64)
    d = np.asarray(dirs, dtype=np.int64)
    th = abs(float(theta))
    by_class: Dict[str, Dict[str, Any]] = {}
    extrema: Dict[int, Tuple[float, float]] = {}
    for cid, name in LABEL_V2_DIRECTION_NAMES.items():
        vals = r[(d == int(cid)) & np.isfinite(r)]
        if vals.size == 0:
            by_class[name] = {"n": 0, "min": None, "max": None}
            continue
        lo = float(np.min(vals))
        hi = float(np.max(vals))
        extrema[int(cid)] = (lo, hi)
        by_class[name] = {"n": int(vals.size), "min": lo, "max": hi}
    flags: List[str] = []
    bear = extrema.get(_BEAR)
    neu = extrema.get(_NEUTRAL)
    bull = extrema.get(_BULL)
    if bear is not None and bear[1] > -th + float(atol):
        flags.append("bear_crosses_theta")
    if bull is not None and bull[0] < th - float(atol):
        flags.append("bull_crosses_theta")
    if neu is not None and (neu[0] < -th - float(atol) or neu[1] > th + float(atol)):
        flags.append("neutral_outside_deadzone")
    if bear is not None and neu is not None and bear[1] >= neu[0] - float(atol):
        flags.append("bear_overlaps_neutral")
    if neu is not None and bull is not None and neu[1] >= bull[0] - float(atol):
        flags.append("neutral_overlaps_bull")
    if bear is not None and bull is not None and bear[1] >= bull[0] - float(atol):
        flags.append("bear_overlaps_bull")
    return _jsonify(
        {
            "ok": len(flags) == 0,
            "theta": th,
            "classes": by_class,
            "flags": flags,
        }
    )


def audit_class_intervals(
    labeled: pd.DataFrame,
    *,
    thetas: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Run :func:`class_intervals_disjoint` on each frozen-theta horizon."""
    theta_map = dict(LABEL_V2_THETA_FROZEN)
    if thetas is not None:
        theta_map.update({str(k): float(v) for k, v in thetas.items()})
    per: Dict[str, Any] = {}
    ok = True
    for key in LABEL_V2_HORIZON_KEYS:
        ret = labeled[f"{key}_ret"].to_numpy(dtype=np.float64)
        dirs = direction_from_return_array(ret, float(theta_map[str(key)]))
        row = class_intervals_disjoint(ret, dirs, theta=float(theta_map[str(key)]))
        per[str(key)] = row
        ok = ok and bool(row.get("ok"))
    return {"ok": ok, "horizons": per}


def extra_theta_mix(labeled: pd.DataFrame) -> Dict[str, Any]:
    """Class-mix table at DIAG_THETA_GRID. Does not train a model."""
    report = summarize_label_v2(
        labeled, thetas=DIAG_THETA_GRID, already_labeled=True
    )
    mix: Dict[str, Any] = {}
    for key in LABEL_V2_HORIZON_KEYS:
        by_theta = (report.get("horizons") or {}).get(key, {}).get("by_theta") or {}
        mix[str(key)] = {}
        for tkey, row in by_theta.items():
            classes = row.get("classes") or {}
            mix[str(key)][str(tkey)] = {
                name: {
                    "rate": (classes.get(name) or {}).get("rate"),
                    "e_r": (classes.get(name) or {}).get("e_r"),
                }
                for name in LABEL_V2_DIRECTION_NAMES.values()
            }
    return {
        "overall": report.get("overall"),
        "thetas": list(DIAG_THETA_GRID),
        "mix": mix,
        "table": report,
    }


def expectancy_minus_cost(
    label_report: Mapping[str, Any],
    *,
    costs: Sequence[float] = COST_ATR,
    thetas: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Live-bracket ``expectancy_atr`` minus stated cost in ATR units.

    Does not block later diagnostics. Negative after-cost expectancy means
    classifying this label cannot be a trading system at that cost.
    """
    theta_map = dict(LABEL_V2_THETA_FROZEN)
    if thetas is not None:
        theta_map.update({str(k): float(v) for k, v in thetas.items()})
    out: Dict[str, Any] = {}
    for key in LABEL_V2_HORIZON_KEYS:
        sl_m, tp_m = LABEL_V2_DURATION_ATR_MULT[str(key)]
        live_key = _pair_key(sl_m, tp_m)
        tkey = _theta_key(float(theta_map[str(key)]))
        hrow = (label_report.get("horizons") or {}).get(key) or {}
        tp_sl = (
            ((hrow.get("by_theta") or {}).get(tkey) or {}).get("tp_sl") or {}
        )
        exp = (tp_sl.get(live_key) or {}).get("expectancy_atr")
        after = {}
        for cost in costs:
            if exp is None:
                after[str(cost)] = None
            else:
                after[str(cost)] = float(exp) - float(cost)
        out[str(key)] = {
            "theta": float(theta_map[str(key)]),
            "live_bracket": {"sl": float(sl_m), "tp": float(tp_m)},
            "expectancy_atr": exp,
            "after_cost": after,
        }
    return _jsonify(out)


def compare_row_values(
    full_row: Mapping[str, Any],
    truncated_row: Mapping[str, Any],
    cols: Sequence[str],
    *,
    atol: float = 1e-5,
) -> List[str]:
    """Column names whose truncated last row disagrees with the full series."""
    mismatches: List[str] = []
    for col in cols:
        left = full_row.get(col)
        right = truncated_row.get(col)
        if left is None and right is None:
            continue
        try:
            lv = float(left) if left is not None else float("nan")
            rv = float(right) if right is not None else float("nan")
        except (TypeError, ValueError):
            if left != right:
                mismatches.append(str(col))
            continue
        if np.isfinite(lv) and np.isfinite(rv):
            if abs(lv - rv) > float(atol):
                mismatches.append(str(col))
            continue
        if np.isfinite(lv) != np.isfinite(rv):
            mismatches.append(str(col))
    return mismatches


def default_native_feature_fn(frame: pd.DataFrame) -> pd.DataFrame:
    """Causal 5m native features for truncation audits."""
    return add_native_tf_features(frame, resolution="5m")


def audit_feature_truncation(
    frame: pd.DataFrame,
    *,
    sample_indices: Sequence[int],
    feature_fn: FeatureFn,
    cols: Sequence[str],
    atol: float = 1e-5,
    full_featured: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Rebuild features on ``df[: t]`` and compare the last row to the full series.

    Args:
        frame: Time-sorted OHLCV (or a synthetic frame with the audited columns).
        sample_indices: Decision rows. Each uses the prefix through that row.
        feature_fn: Maps a prefix frame to a featured frame.
        cols: Columns that must match.
        atol: Absolute tolerance.
        full_featured: Precomputed ``feature_fn(frame)``. Computed when omitted.

    Returns:
        ``ok`` is false when any sampled last row mismatches.
    """
    full_feat = full_featured if full_featured is not None else feature_fn(frame)
    mismatches: List[Dict[str, Any]] = []
    n_ok = 0
    for idx in sample_indices:
        i = int(idx)
        if i < 0 or i >= len(frame):
            continue
        prefix = frame.iloc[: i + 1].copy()
        trunc_feat = feature_fn(prefix)
        if trunc_feat.empty or full_feat.empty:
            mismatches.append({"index": i, "cols": ["empty_features"]})
            continue
        full_row = full_feat.iloc[min(i, len(full_feat) - 1)]
        trunc_row = trunc_feat.iloc[-1]
        bad = compare_row_values(full_row, trunc_row, cols, atol=atol)
        if bad:
            mismatches.append({"index": i, "cols": bad[:20]})
        else:
            n_ok += 1
    return _jsonify(
        {
            "ok": len(mismatches) == 0,
            "n_ok": n_ok,
            "n_checked": int(len(sample_indices)),
            "mismatches": mismatches[:20],
            "n_mismatches": len(mismatches),
        }
    )


def audit_10m_truncation(
    df5m: pd.DataFrame,
    *,
    sample_indices: Sequence[int],
) -> Dict[str, Any]:
    """Last complete 10m bar on a 5m prefix must match the full 10m series."""
    full_10 = build_10m_ohlcv_from_5m(df5m)
    mismatches = 0
    checked = 0
    for idx in sample_indices:
        i = int(idx)
        if i < 1 or i >= len(df5m):
            continue
        prefix = df5m.iloc[: i + 1]
        trunc_10 = build_10m_ohlcv_from_5m(prefix)
        if trunc_10.empty:
            continue
        checked += 1
        last_time = trunc_10["time"].iloc[-1]
        full_hit = full_10.loc[full_10["time"] == last_time]
        if full_hit.empty:
            mismatches += 1
            continue
        for col in ("open", "high", "low", "close", "volume"):
            if col not in trunc_10.columns or col not in full_hit.columns:
                continue
            if not np.isclose(
                float(trunc_10[col].iloc[-1]),
                float(full_hit[col].iloc[0]),
                atol=1e-8,
                equal_nan=True,
            ):
                mismatches += 1
                break
    return _jsonify(
        {
            "ok": mismatches == 0,
            "checked": checked,
            "mismatches": mismatches,
        }
    )


def audit_asof_no_lookahead(
    frames: Mapping[str, pd.DataFrame],
    decision_times: Sequence[pd.Timestamp],
) -> Dict[str, Any]:
    """``assert_no_lookahead`` on each provided TF at sampled decision times."""
    failures: List[str] = []
    checked = 0
    for t in decision_times:
        ts = pd.Timestamp(t)
        for res, df in frames.items():
            minutes = int(RESOLUTION_MINUTES.get(str(res), 0) or 0)
            if minutes <= 0 or df is None or df.empty:
                continue
            checked += 1
            try:
                assert_no_lookahead(df, ts, resolution_minutes=minutes)
            except AssertionError as exc:
                failures.append(f"{res}@{ts.isoformat()}: {exc}")
    return _jsonify(
        {
            "ok": len(failures) == 0,
            "checked": checked,
            "failures": failures[:20],
        }
    )


def channel_scale_is_per_window(
    window: np.ndarray,
    longer: np.ndarray,
    *,
    feature_cols: Sequence[str],
    resolution_minutes: int = 5,
) -> bool:
    """v14 ``ret_1`` z-score uses the window, not a longer series."""
    cols = list(feature_cols)
    if "ret_1" not in cols:
        return True
    idx = cols.index("ret_1")
    scaled_win = scale_v14_feature_window(
        window,
        feature_cols=cols,
        resolution_minutes=int(resolution_minutes),
        zscore_returns=True,
    )
    scaled_long = scale_v14_feature_window(
        longer,
        feature_cols=cols,
        resolution_minutes=int(resolution_minutes),
        zscore_returns=True,
    )
    t = int(window.shape[0])
    same_as_prefix = np.allclose(
        scaled_win[:, idx], scaled_long[:t, idx], atol=1e-5
    )
    return not bool(same_as_prefix)


def last_bar_matrix(
    featured: pd.DataFrame,
    *,
    cols: Optional[Sequence[str]] = None,
    fill_nonfinite: bool = True,
) -> Tuple[np.ndarray, Tuple[str, ...]]:
    """Last-bar v14 continuous features. No sequence flatten."""
    names = tuple(cols) if cols is not None else fusion_feature_cols_v14()
    frame = featured
    missing = [c for c in names if c not in frame.columns]
    if missing:
        zeros = pd.DataFrame(0.0, index=frame.index, columns=missing)
        frame = pd.concat([frame, zeros], axis=1)
    values = frame.loc[:, list(names)].to_numpy(dtype=np.float64)
    if fill_nonfinite:
        values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return values.astype(np.float32, copy=False), names


def direction_matrix(
    labeled: pd.DataFrame,
    *,
    thetas: Optional[Mapping[str, float]] = None,
) -> np.ndarray:
    """``(n, H)`` frozen-theta classes. Non-finite return is -1."""
    theta_map = dict(LABEL_V2_THETA_FROZEN)
    if thetas is not None:
        theta_map.update({str(k): float(v) for k, v in thetas.items()})
    n = len(labeled)
    y = np.full((n, len(LABEL_V2_HORIZON_KEYS)), -1, dtype=np.int64)
    for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
        col = f"{key}_ret"
        if col not in labeled.columns:
            continue
        y[:, j] = direction_from_return_array(
            labeled[col].to_numpy(dtype=np.float64),
            float(theta_map[str(key)]),
        )
    return y


def embargoed_neighbor_probs(
    features: np.ndarray,
    labels: np.ndarray,
    train_idx: np.ndarray,
    query_idx: np.ndarray,
    *,
    horizon_bars: int,
    embargo_bars: int = FUSION_EMBARGO_BARS,
    n_neighbors: int = 32,
    train_cap: int = 8000,
    query_cap: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    """``P(class | neighbors)`` with time embargo and non-overlapping paths.

    Neighbors whose index is within ``max(embargo, horizon_bars)`` of the query
    are dropped. Train-only fit. Query rows should be validation indices.
    """
    rng = np.random.default_rng(int(seed))
    x = np.nan_to_num(np.asarray(features, dtype=np.float64), nan=0.0)
    y = np.asarray(labels, dtype=np.int64)
    train = np.asarray(train_idx, dtype=np.int64)
    query = np.asarray(query_idx, dtype=np.int64)
    if train.size > int(train_cap):
        pick = np.sort(rng.choice(train.size, size=int(train_cap), replace=False))
        train = train[pick]
    if query.size > int(query_cap):
        pick = np.sort(rng.choice(query.size, size=int(query_cap), replace=False))
        query = query[pick]
    valid_train = train[y[train] >= 0]
    if valid_train.size < 8 or query.size == 0:
        return {
            "ok": False,
            "reason": "insufficient_rows",
            "near_base_rate": True,
            "mean_probs": None,
            "base_rate": None,
            "total_variation": None,
        }
    n_ask = min(max(int(n_neighbors) * 8, int(n_neighbors)), int(valid_train.size))
    nn = NearestNeighbors(n_neighbors=n_ask, algorithm="auto")
    nn.fit(x[valid_train])
    _, ind = nn.kneighbors(x[query])
    min_gap = max(int(embargo_bars), int(horizon_bars), 1)
    k_keep = int(n_neighbors)
    counts = np.zeros(LABEL_V2_DIRECTION_CARDINALITY, dtype=np.float64)
    n_used = 0
    skipped = 0
    for q_i, neigh in enumerate(ind):
        q_pos = int(query[q_i])
        if y[q_pos] < 0:
            continue
        kept: List[int] = []
        for local in neigh:
            t_pos = int(valid_train[int(local)])
            if abs(t_pos - q_pos) < min_gap:
                continue
            kept.append(t_pos)
            if len(kept) >= k_keep:
                break
        if len(kept) < 8:
            skipped += 1
            continue
        n_used += 1
        for t_pos in kept:
            cid = int(y[t_pos])
            if 0 <= cid < LABEL_V2_DIRECTION_CARDINALITY:
                counts[cid] += 1.0
    total = float(counts.sum())
    if total <= 0.0:
        mean_p = np.full(LABEL_V2_DIRECTION_CARDINALITY, 1.0 / 3.0)
    else:
        mean_p = counts / total
    train_y = y[valid_train]
    base = np.array(
        [
            float(np.mean(train_y == c)) if train_y.size else 1.0 / 3.0
            for c in range(LABEL_V2_DIRECTION_CARDINALITY)
        ],
        dtype=np.float64,
    )
    tv = 0.5 * float(np.abs(mean_p - base).sum())
    names = {
        LABEL_V2_DIRECTION_NAMES[c]: float(mean_p[c])
        for c in range(LABEL_V2_DIRECTION_CARDINALITY)
    }
    base_names = {
        LABEL_V2_DIRECTION_NAMES[c]: float(base[c])
        for c in range(LABEL_V2_DIRECTION_CARDINALITY)
    }
    return _jsonify(
        {
            "ok": True,
            "n_queries": n_used,
            "n_skipped": skipped,
            "k": k_keep,
            "min_gap": min_gap,
            "mean_probs": names,
            "base_rate": base_names,
            "total_variation": tv,
            "near_base_rate": tv < float(KNN_TV_NEAR),
        }
    )


def _sign_class(values: np.ndarray) -> np.ndarray:
    out = np.full(values.shape, _NEUTRAL, dtype=np.int64)
    finite = np.isfinite(values)
    out[finite & (values > 0.0)] = _BULL
    out[finite & (values < 0.0)] = _BEAR
    return out


def naive_baselines(
    y: np.ndarray,
    features: np.ndarray,
    feature_names: Sequence[str],
    eval_idx: np.ndarray,
    *,
    horizon_bars: int,
) -> Dict[str, Any]:
    """Always-class, last-return sign, and RSI momentum on non-overlapping rows."""
    names = [str(n) for n in feature_names]
    x = np.asarray(features, dtype=np.float64)
    yt_all = np.asarray(y, dtype=np.int64)
    kept = nonoverlap_indices(np.asarray(eval_idx, dtype=np.int64), int(horizon_bars))
    kept = kept[(kept >= 0) & (kept < len(yt_all)) & (yt_all[kept] >= 0)]
    if kept.size == 0:
        return {"ok": False, "reason": "empty_eval", "best_balanced_acc": 0.0}
    yt = yt_all[kept]
    preds: Dict[str, np.ndarray] = {
        "always_bear": np.full(kept.shape, _BEAR, dtype=np.int64),
        "always_neutral": np.full(kept.shape, _NEUTRAL, dtype=np.int64),
        "always_bull": np.full(kept.shape, _BULL, dtype=np.int64),
    }
    if RETURN_COL in names:
        preds["last_return_sign"] = _sign_class(x[kept, names.index(RETURN_COL)])
    if MOMENTUM_COL in names:
        preds["rsi_momentum"] = _sign_class(x[kept, names.index(MOMENTUM_COL)] - 50.0)
    scores: Dict[str, Any] = {}
    best = -1.0
    best_name = ""
    for name, pred in preds.items():
        bal = balanced_accuracy(yt, pred)
        raw = raw_accuracy(yt, pred)
        scores[name] = {"balanced_acc": bal, "raw_acc": raw, "n": int(kept.size)}
        if bal > best:
            best = bal
            best_name = name
    return _jsonify(
        {
            "ok": True,
            "n": int(kept.size),
            "horizon_bars": int(horizon_bars),
            "baselines": scores,
            "best_name": best_name,
            "best_balanced_acc": best,
        }
    )


def _fit_predict(
    model: Any,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_eval: np.ndarray,
) -> np.ndarray:
    model.fit(x_train, y_train)
    return np.asarray(model.predict(x_eval), dtype=np.int64)


def simple_model_scores(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    horizon_bars: int,
    n_dev: int,
    seed: int = 42,
    folds: int = 3,
    embargo_bars: int = FUSION_EMBARGO_BARS,
) -> Dict[str, Any]:
    """Last-bar logistic and histogram GBM. Test indices are never used."""
    x = np.nan_to_num(np.asarray(features, dtype=np.float64), nan=0.0)
    y = np.asarray(labels, dtype=np.int64)
    models = {
        "logistic": LogisticRegression(
            max_iter=300,
            solver="lbfgs",
            random_state=int(seed),
        ),
        "hist_gbm": HistGradientBoostingClassifier(
            max_depth=3,
            max_iter=40,
            learning_rate=0.1,
            random_state=int(seed),
        ),
    }
    fold_rows: Dict[str, List[float]] = {name: [] for name in models}
    for tr_sl, va_sl in walk_forward_slices(
        int(n_dev), folds=int(folds), embargo=int(embargo_bars)
    ):
        tr = np.arange(tr_sl.start or 0, tr_sl.stop)
        va = np.arange(va_sl.start or 0, va_sl.stop)
        tr = tr[y[tr] >= 0]
        va = nonoverlap_indices(va[y[va] >= 0], int(horizon_bars))
        if tr.size < 16 or va.size < 4:
            continue
        if len(np.unique(y[tr])) < 2:
            continue
        for name, proto in models.items():
            pred = _fit_predict(proto, x[tr], y[tr], x[va])
            fold_rows[name].append(balanced_accuracy(y[va], pred))
    val_kept = nonoverlap_indices(
        np.asarray(val_idx, dtype=np.int64)[y[val_idx] >= 0],
        int(horizon_bars),
    )
    train_kept = np.asarray(train_idx, dtype=np.int64)
    train_kept = train_kept[y[train_kept] >= 0]
    val_scores: Dict[str, Any] = {}
    best_val = -1.0
    best_name = ""
    if train_kept.size >= 16 and val_kept.size >= 4 and len(np.unique(y[train_kept])) >= 2:
        for name, proto in models.items():
            pred = _fit_predict(proto, x[train_kept], y[train_kept], x[val_kept])
            bal = balanced_accuracy(y[val_kept], pred)
            val_scores[name] = {
                "balanced_acc": bal,
                "raw_acc": raw_accuracy(y[val_kept], pred),
                "n": int(val_kept.size),
                "walk_forward_mean": (
                    float(np.mean(fold_rows[name])) if fold_rows[name] else None
                ),
            }
            if bal > best_val:
                best_val = bal
                best_name = name
    return _jsonify(
        {
            "ok": bool(val_scores),
            "val": val_scores,
            "best_name": best_name,
            "best_val_balanced_acc": best_val if val_scores else 0.0,
            "test_unused": True,
        }
    )


def decide_branch(report: Mapping[str, Any]) -> str:
    """Single next-action token. No Transformer retrain is implied except later_."""
    d1 = dict(report.get("d1_index_audit") or {})
    if d1 and not d1.get("ok", True):
        return "fail_index_audit"
    d2 = dict(report.get("d2_intervals") or {})
    if d2 and not d2.get("ok", True):
        return "fail_class_intervals"
    d9 = dict(report.get("d9_truncation") or {})
    if d9 and not d9.get("ok", True):
        return "fix_leakage"
    d5 = dict(report.get("d5_knn") or {})
    d6 = dict(report.get("d6_baselines") or {})
    d7 = dict(report.get("d7_simple_models") or {})
    if not d5 or not d6 or not d7:
        return "review"
    near = True
    for key in LABEL_V2_HORIZON_KEYS:
        row = (d5.get("horizons") or {}).get(key) or {}
        if not bool(row.get("near_base_rate", True)):
            near = False
    d6_best = max(
        float(((d6.get("horizons") or {}).get(k) or {}).get("best_balanced_acc") or 0.0)
        for k in LABEL_V2_HORIZON_KEYS
    )
    d7_best = max(
        float(
            ((d7.get("horizons") or {}).get(k) or {}).get("best_val_balanced_acc") or 0.0
        )
        for k in LABEL_V2_HORIZON_KEYS
    )
    lift = d7_best - d6_best
    transformer_max = max(float(v) for v in PUBLISHED_TRANSFORMER_BALANCED_ACC.values())
    if near and lift < float(BASELINE_MARGIN):
        return "stop_target_or_features"
    if lift >= float(BASELINE_MARGIN) and transformer_max < float(TRANSFORMER_CHANCE_MAX):
        return "later_direction_only"
    return "review"


def _spread_indices(n: int, k: int, *, lo: int = 0, hi: Optional[int] = None) -> np.ndarray:
    end = int(n if hi is None else hi)
    start = max(int(lo), 0)
    if end <= start:
        return np.zeros(0, dtype=np.int64)
    count = min(int(k), end - start)
    if count <= 0:
        return np.zeros(0, dtype=np.int64)
    return np.linspace(start, end - 1, num=count, dtype=np.int64)


def run_fusion_diagnostics(
    df5m: pd.DataFrame,
    *,
    frames: Optional[Mapping[str, pd.DataFrame]] = None,
    seed: int = 42,
    n_index_samples: int = 100,
    n_truncation_samples: int = 20,
    knn_train_cap: int = 8000,
    knn_val_cap: int = 2000,
    knn_k: int = 32,
    fit_simple_models: bool = True,
    feature_fn: Optional[FeatureFn] = None,
    featured: Optional[pd.DataFrame] = None,
    score_test: bool = False,
    ablate_groups: bool = False,
    transformer_test: Optional[Mapping[str, Any]] = None,
    decision_times: Optional[np.ndarray] = None,
    transformer_logits: Optional[Mapping[str, np.ndarray]] = None,
    transformer_y: Optional[Mapping[str, np.ndarray]] = None,
    transformer_window_logits: Optional[np.ndarray] = None,
    transformer_window_times: Optional[np.ndarray] = None,
    class_weight_sensitivity: bool = False,
    score_path_regression: bool = False,
) -> Dict[str, Any]:
    """Run D1–D7 / D9 / expectancy. Never fits ``MtfFusionTransformer``.

    Args:
        df5m: 5m OHLCV with ``time`` / OHLC (optional ``atr``).
        frames: Optional native TF frames for as-of lookahead checks.
        seed: RNG seed for neighbor subsamples and sklearn models.
        n_index_samples: D1 rows drawn from the train portion.
        n_truncation_samples: D9 prefix recomputes.
        knn_train_cap: Train-neighbor subsample size.
        knn_val_cap: Validation query subsample size.
        knn_k: Neighbors kept after embargo.
        fit_simple_models: When false, skip D5–D7 (tests / leakage abort).
        feature_fn: Override for D9. Defaults to native 5m features.
        featured: Precomputed 5m features aligned to ``df5m``. Skips a second
            full ``add_native_tf_features`` when provided.
        score_test: Run the last-bar direction-predictability bake-off.
        ablate_groups: Val-only knockout / add-one-in / vol+time (needs score_test).
        transformer_test: Optional v15 JSON metrics (not used as a stop token).
        decision_times: Stride-4 window timestamps for an aligned test row.
        transformer_logits: Optional per-horizon (n, C) logits on stride rows.
        transformer_y: Optional per-horizon labels aligned to those logits.
        transformer_window_logits: Optional (n_windows, H, C) checkpoint logits.
        transformer_window_times: Window timestamps aligned to those logits.
        class_weight_sensitivity: Extra val fit with inverse-frequency weights.
        score_path_regression: Last-bar signed path-edge regression bake-off.

    Returns:
        JSON-ready dict with a ``branch`` token.
    """
    labeled_full = compute_fusion_path_targets(df5m)
    labeled = trim_label_v2_tail(labeled_full)
    n = len(labeled)
    slices = purged_index_slices(n)
    train_sl = slices["train"]
    train_hi = train_sl.stop or 0
    d1_idx = _spread_indices(
        n, int(n_index_samples), lo=0, hi=max(train_hi - 24, 1)
    )
    report: Dict[str, Any] = {
        "n_labeled": n,
        "split": {
            "train": [train_sl.start or 0, train_sl.stop],
            "val": [slices["val"].start, slices["val"].stop],
            "test": [slices["test"].start, slices["test"].stop],
            "test_unused": not bool(score_test),
        },
        "d1_index_audit": audit_label_index(labeled_full, sample_indices=d1_idx),
        "d2_intervals": audit_class_intervals(labeled),
    }
    if not report["d1_index_audit"]["ok"] or not report["d2_intervals"]["ok"]:
        report["branch"] = decide_branch(report)
        report["notes"] = "Label index or class-interval audit failed. Stop."
        return _jsonify(report)
    theta_pack = extra_theta_mix(labeled)
    report["theta_mix"] = {
        "overall": theta_pack.get("overall"),
        "thetas": theta_pack.get("thetas"),
        "mix": theta_pack.get("mix"),
    }
    report["expectancy_minus_cost"] = expectancy_minus_cost(theta_pack["table"])
    fn = feature_fn if feature_fn is not None else default_native_feature_fn
    trunc_lo = max(min(train_hi // 4, max(train_hi - 1, 0)), 0)
    trunc_idx = _spread_indices(
        n, int(n_truncation_samples), lo=trunc_lo, hi=max(train_hi, 1)
    )
    feat_cols = list(fusion_feature_cols_v14())
    if featured is not None and feature_fn is None:
        feat_frame = featured
        d9_native = {
            "ok": True,
            "skipped": "precomputed_featured",
            "n_checked": 0,
        }
    else:
        feat_frame = featured if featured is not None else fn(labeled)
        d9_native = audit_feature_truncation(
            labeled if featured is None else feat_frame,
            sample_indices=trunc_idx,
            feature_fn=fn,
            cols=feat_cols if featured is None else list(feat_frame.columns),
            full_featured=feat_frame,
        )
    d9_10m = audit_10m_truncation(labeled, sample_indices=trunc_idx)
    asof_frames: Dict[str, pd.DataFrame] = {"5m": labeled}
    asof_frames["10m"] = build_10m_ohlcv_from_5m(labeled)
    if frames:
        for res in FUSION_INPUT_RESOLUTIONS:
            if res in frames and frames[res] is not None:
                asof_frames[str(res)] = frames[res]
    times = pd.to_datetime(labeled["time"], utc=True)
    asof_times = [times.iloc[int(i)] for i in trunc_idx if 0 <= int(i) < n]
    d9_asof = audit_asof_no_lookahead(asof_frames, asof_times)
    dummy_win = np.linspace(-1.0, 1.0, 16, dtype=np.float32).reshape(16, 1)
    dummy_win = np.repeat(dummy_win, max(len(feat_cols), 1), axis=1)
    dummy_long = np.vstack([dummy_win, dummy_win * 2.0])
    scale_ok = channel_scale_is_per_window(
        dummy_win, dummy_long, feature_cols=feat_cols[: dummy_win.shape[1]]
    )
    report["d9_truncation"] = {
        "ok": bool(d9_native.get("ok"))
        and bool(d9_10m.get("ok"))
        and bool(d9_asof.get("ok")),
        "native": d9_native,
        "ten_minute": d9_10m,
        "asof": d9_asof,
        "channel_scale_per_window": bool(scale_ok),
    }
    d9_ok = bool(report["d9_truncation"]["ok"])
    run_path = bool(score_path_regression)
    run_direction = bool(score_test) or bool(ablate_groups)
    run_d5d7 = bool(fit_simple_models) and (run_direction or not run_path)
    if not d9_ok:
        report["branch"] = decide_branch(report)
        report["notes"] = (
            "Ignore D5–D7 accuracy until truncation matches. "
            "Do not train MtfFusionTransformer."
        )
        return _jsonify(report)
    if not run_d5d7 and not run_path and not run_direction:
        report["branch"] = decide_branch(report)
        report["notes"] = (
            "Ignore D5–D7 accuracy until truncation matches. "
            "Do not train MtfFusionTransformer."
        )
        return _jsonify(report)

    if len(feat_frame) != n:
        feat_frame = feat_frame.iloc[:n].reset_index(drop=True)
    x, names = last_bar_matrix(feat_frame)
    raw_x, _raw_names = last_bar_matrix(feat_frame, fill_nonfinite=False)
    y = direction_matrix(labeled)
    train_idx = np.arange(slices["train"].start or 0, slices["train"].stop or 0)
    val_idx = np.arange(slices["val"].start or 0, slices["val"].stop or 0)
    n_dev = int(slices["val"].stop or 0)
    bars = horizon_bars_map()
    if run_d5d7:
        print("D5–D7 last-bar classifiers (knn / baselines / logistic+HGB)...")
        d5_h: Dict[str, Any] = {}
        d6_h: Dict[str, Any] = {}
        d7_h: Dict[str, Any] = {}
        for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
            print(f"  D5–D7 {key} ({j + 1}/{len(LABEL_V2_HORIZON_KEYS)})")
            d5_h[str(key)] = embargoed_neighbor_probs(
                x,
                y[:, j],
                train_idx,
                val_idx,
                horizon_bars=int(bars[str(key)]),
                n_neighbors=int(knn_k),
                train_cap=int(knn_train_cap),
                query_cap=int(knn_val_cap),
                seed=int(seed) + j,
            )
            d6_h[str(key)] = naive_baselines(
                y[:, j],
                x,
                names,
                val_idx,
                horizon_bars=int(bars[str(key)]),
            )
            d7_h[str(key)] = simple_model_scores(
                x,
                y[:, j],
                train_idx=train_idx,
                val_idx=val_idx,
                horizon_bars=int(bars[str(key)]),
                n_dev=n_dev,
                seed=int(seed),
            )
        report["d5_knn"] = {"horizons": d5_h}
        report["d6_baselines"] = {"horizons": d6_h}
        report["d7_simple_models"] = {"horizons": d7_h}
        print("D5–D7 last-bar baselines done.")
    else:
        print("Skipping D5–D7 (path-regression does not need classifiers).")
        report["d5_knn"] = {"skipped": True}
        report["d6_baselines"] = {"skipped": True}
        report["d7_simple_models"] = {"skipped": True}
    report["published_transformer_val_balanced_acc"] = dict(
        PUBLISHED_TRANSFORMER_BALANCED_ACC
    )
    if transformer_test:
        report["transformer_test_report"] = dict(transformer_test)
    if bool(score_test) or bool(ablate_groups):
        from scripts.colab.direction_predictability import (
            path_magnitude_targets,
            return_matrix,
            run_direction_predictability,
        )

        print("Running last-bar direction-predictability bake-off...")
        report["direction_predictability"] = run_direction_predictability(
            raw_x,
            names,
            y,
            return_matrix(labeled),
            labeled["time"].to_numpy(),
            seed=int(seed),
            score_test=bool(score_test),
            ablate_groups=bool(ablate_groups),
            decision_times=decision_times,
            transformer_test=transformer_test,
            transformer_logits=transformer_logits,
            transformer_y=transformer_y,
            transformer_window_logits=transformer_window_logits,
            transformer_window_times=transformer_window_times,
            class_weight_sensitivity=bool(class_weight_sensitivity),
            mag_targets=path_magnitude_targets(labeled),
        )
    if bool(score_path_regression):
        from scripts.colab.path_regression import run_path_regression

        print("Running last-bar path-edge regression bake-off...")
        report["path_regression"] = run_path_regression(
            raw_x,
            names,
            labeled,
            seed=int(seed),
            score_test=True,
        )
    report["branch"] = decide_branch(report)
    report["notes"] = (
        "stop_target_or_features: do not retrain the Transformer. "
        "later_direction_only: one direction-only run with path weights at 0 "
        "and class weights off. Live stays v11. "
        "direction_predictability readings are pre-registered and are not "
        "a decide_branch token. path_regression is a last-bar path-edge "
        "experiment, not a fused retrain."
    )
    return _jsonify(report)
