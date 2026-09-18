"""Label V2 path targets: ATR-normalized return, MFE, MAE, persistence.

Research-only. Live v11 fusion remains 2-class close-to-close with ignore_index
NEUTRAL. Path windows are t+1..t+k; High_t / Low_t never enter the target.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    FUSION_DURATION_ATR_MULT,
    FUSION_HORIZON_BARS_5M,
    FUSION_HORIZON_KEYS,
    LABEL_V2_COLS,
    LABEL_V2_DIRECTION_NAMES,
    LABEL_V2_DISAGREE_MIN,
    LABEL_V2_MINORITY_RATE,
    LABEL_V2_PATH_FIELDS,
    LABEL_V2_PERSIST_RANGE_MIN,
    LABEL_V2_REG_FIELDS,
    LABEL_V2_THETA_FROZEN,
    LABEL_V2_THETA_GRID,
    LABEL_V2_TP_SL_AMBIGUOUS,
    LABEL_V2_TP_SL_GRID,
    LABEL_V2_TP_SL_NAMES,
    LABEL_V2_TP_SL_NEITHER,
    LABEL_V2_TP_SL_SL_FIRST,
    LABEL_V2_TP_SL_TP_FIRST,
    MAX_FUSION_HORIZON_BARS,
)
from feature_store.transformer_btcusd.mtf_labels import trim_fusion_label_tail

_EPS = 1e-9
_QUANTILES: Tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)
_BEAR = 0
_NEUTRAL = 1
_BULL = 2


def _ensure_ohlcv_time(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    elif "timestamp" in out.columns:
        ts = out["timestamp"]
        if pd.api.types.is_numeric_dtype(ts):
            out["time"] = pd.to_datetime(ts, unit="s", utc=True)
        else:
            out["time"] = pd.to_datetime(ts, utc=True)
    else:
        raise ValueError("Label frame requires time or timestamp")
    return out.sort_values("time").reset_index(drop=True)


def _atr_series(df: pd.DataFrame) -> np.ndarray:
    """Causal ATR at t. Falls back to 14-period mean true range."""
    n = len(df)
    if "atr" in df.columns:
        atr = df["atr"].to_numpy(dtype=np.float64)
        if np.isfinite(atr).any():
            return atr
    close = df["close"].to_numpy(dtype=np.float64)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    return pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy(dtype=np.float64)


def _forward_stack(arr: np.ndarray, n_valid: int, k: int) -> np.ndarray:
    """Stack arr[i+1:i+k+1] rows for i in [0, n_valid). Shape (n_valid, k)."""
    kk = int(k)
    if n_valid <= 0 or kk <= 0:
        return np.zeros((max(n_valid, 0), max(kk, 0)), dtype=np.float64)
    return np.stack([arr[j : j + n_valid] for j in range(1, kk + 1)], axis=1)


def direction_from_return(r: float, theta: float) -> int:
    """Map ATR-normalized return to BEAR/NEUTRAL/BULL (0/1/2).

    Args:
        r: Forward return in ATR units.
        theta: Dead-zone half-width in ATR units. Must be positive.

    Returns:
        0 BEAR, 1 NEUTRAL, 2 BULL.

    Raises:
        ValueError: If ``r`` is not finite.
    """
    if not np.isfinite(r):
        raise ValueError("return must be finite")
    th = abs(float(theta))
    val = float(r)
    if val >= th:
        return _BULL
    if val <= -th:
        return _BEAR
    return _NEUTRAL


def direction_from_return_array(r: np.ndarray, theta: float) -> np.ndarray:
    """Vectorized :func:`direction_from_return`. Non-finite → -1."""
    arr = np.asarray(r, dtype=np.float64)
    th = abs(float(theta))
    out = np.ones(arr.shape, dtype=np.int64)
    finite = np.isfinite(arr)
    out[finite & (arr >= th)] = _BULL
    out[finite & (arr <= -th)] = _BEAR
    out[~finite] = -1
    return out


def _normalize_side(side: str) -> str:
    s = str(side or "LONG").strip().upper()
    if s in ("SHORT", "SELL", "BEAR", "STRONG_SELL"):
        return "SHORT"
    return "LONG"


def tp_sl_from_path(
    fwd_high: np.ndarray,
    fwd_low: np.ndarray,
    entry: float,
    atr: float,
    tp_mult: float,
    sl_mult: float,
    side: str,
) -> int:
    """Walk a future OHLC path and return TP_FIRST / SL_FIRST / NEITHER / AMBIGUOUS.

    Same-bar both-sides breach is AMBIGUOUS (not a forced winner).

    Args:
        fwd_high: Highs for bars t+1..t+k.
        fwd_low: Lows for bars t+1..t+k.
        entry: Close at t.
        atr: ATR at t.
        tp_mult: Take-profit distance in ATR.
        sl_mult: Stop-loss distance in ATR.
        side: ``LONG`` or ``SHORT``.

    Returns:
        Integer code from ``LABEL_V2_TP_SL_*``.
    """
    high = np.asarray(fwd_high, dtype=np.float64).ravel()
    low = np.asarray(fwd_low, dtype=np.float64).ravel()
    if high.size == 0 or high.size != low.size:
        return int(LABEL_V2_TP_SL_NEITHER)
    denom = max(float(atr), _EPS)
    entry_f = float(entry)
    if _normalize_side(side) == "SHORT":
        tp_level = entry_f - float(tp_mult) * denom
        sl_level = entry_f + float(sl_mult) * denom
        tp_hit = low <= tp_level
        sl_hit = high >= sl_level
    else:
        tp_level = entry_f + float(tp_mult) * denom
        sl_level = entry_f - float(sl_mult) * denom
        tp_hit = high >= tp_level
        sl_hit = low <= sl_level
    for j in range(high.size):
        hit_tp = bool(tp_hit[j])
        hit_sl = bool(sl_hit[j])
        if hit_tp and hit_sl:
            return int(LABEL_V2_TP_SL_AMBIGUOUS)
        if hit_tp:
            return int(LABEL_V2_TP_SL_TP_FIRST)
        if hit_sl:
            return int(LABEL_V2_TP_SL_SL_FIRST)
    return int(LABEL_V2_TP_SL_NEITHER)


def tp_sl_from_windows(
    fwd_high: np.ndarray,
    fwd_low: np.ndarray,
    entry: np.ndarray,
    atr: np.ndarray,
    tp_mult: float,
    sl_mult: float,
    side: str,
) -> np.ndarray:
    """Vectorized TP/SL outcome for stacked paths. Shape (n,)."""
    high = np.asarray(fwd_high, dtype=np.float64)
    low = np.asarray(fwd_low, dtype=np.float64)
    if high.ndim != 2 or low.shape != high.shape:
        raise ValueError("fwd_high and fwd_low must be (n, k)")
    n, k = high.shape
    out = np.full(n, int(LABEL_V2_TP_SL_NEITHER), dtype=np.int64)
    if n == 0 or k == 0:
        return out
    denom = np.maximum(np.asarray(atr, dtype=np.float64).reshape(n), _EPS)
    ent = np.asarray(entry, dtype=np.float64).reshape(n)
    if _normalize_side(side) == "SHORT":
        tp_hit = low <= (ent - float(tp_mult) * denom)[:, None]
        sl_hit = high >= (ent + float(sl_mult) * denom)[:, None]
    else:
        tp_hit = high >= (ent + float(tp_mult) * denom)[:, None]
        sl_hit = low <= (ent - float(sl_mult) * denom)[:, None]
    tp_idx = np.where(tp_hit.any(axis=1), tp_hit.argmax(axis=1), k)
    sl_idx = np.where(sl_hit.any(axis=1), sl_hit.argmax(axis=1), k)
    both = (tp_idx < k) & (sl_idx < k) & (tp_idx == sl_idx)
    out[(tp_idx < sl_idx) & (tp_idx < k)] = int(LABEL_V2_TP_SL_TP_FIRST)
    out[(sl_idx < tp_idx) & (sl_idx < k)] = int(LABEL_V2_TP_SL_SL_FIRST)
    out[both] = int(LABEL_V2_TP_SL_AMBIGUOUS)
    return out


def state_persistence(
    fwd_close: np.ndarray,
    entry: float,
    atr: float,
    theta: float,
) -> float:
    """Fraction of path closes matching the endpoint 3-class state."""
    path = np.asarray(fwd_close, dtype=np.float64).ravel()
    if path.size == 0:
        return 0.0
    denom = max(float(atr), _EPS)
    r_path = (path - float(entry)) / denom
    dirs = direction_from_return_array(r_path, theta)
    end = int(dirs[-1])
    if end < 0:
        return 0.0
    return float(np.mean(dirs == end))


def label_v2_future_leak_cols() -> frozenset:
    """Columns that must never appear as model inputs."""
    return frozenset(LABEL_V2_COLS)


def fusion_label_v2_matrices(
    df: pd.DataFrame,
    *,
    thetas: Optional[Mapping[str, float]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build (n, H) 3-class dirs and (n, H, 3) ret/mfe/mae path targets.

    Direction uses frozen per-horizon theta. Non-finite return maps to -1.
    """
    theta_map = dict(LABEL_V2_THETA_FROZEN)
    if thetas is not None:
        theta_map.update({str(k): float(v) for k, v in thetas.items()})
    n = int(len(df))
    n_h = len(FUSION_HORIZON_KEYS)
    y_dir = np.full((n, n_h), -1, dtype=np.int64)
    y_reg = np.full((n, n_h, len(LABEL_V2_REG_FIELDS)), np.nan, dtype=np.float32)
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        ret = df[f"{key}_ret"].to_numpy(dtype=np.float64)
        mfe = df[f"{key}_mfe"].to_numpy(dtype=np.float64)
        mae = df[f"{key}_mae"].to_numpy(dtype=np.float64)
        y_reg[:, j, 0] = ret.astype(np.float32)
        y_reg[:, j, 1] = mfe.astype(np.float32)
        y_reg[:, j, 2] = mae.astype(np.float32)
        y_dir[:, j] = direction_from_return_array(ret, float(theta_map[str(key)]))
    return y_dir, y_reg


def valid_label_v2_mask(y_dir: np.ndarray, y_reg: np.ndarray) -> np.ndarray:
    """Keep rows with at least one finite path return (any horizon)."""
    del y_dir
    ret = np.asarray(y_reg, dtype=np.float32)[:, :, 0]
    return np.any(np.isfinite(ret), axis=1)


def label_v2_class_mix(y_dir: np.ndarray) -> Dict[str, Dict[str, float]]:
    """Per-horizon 3-class counts. Invalid dirs (<0) are unlabeled."""
    report: Dict[str, Dict[str, float]] = {}
    mat = np.asarray(y_dir, dtype=np.int64)
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        col = mat[:, j] if mat.ndim == 2 else mat
        n = int(len(col))
        unlabeled = int(np.sum(col < 0))
        counts: Dict[str, float] = {
            name: float(np.sum(col == int(cid)))
            for cid, name in LABEL_V2_DIRECTION_NAMES.items()
        }
        counts["UNLABELED"] = float(unlabeled)
        counts["n"] = float(n)
        counts["unlabeled_rate"] = float(unlabeled) / float(max(n, 1))
        report[str(key)] = counts
    return report


def compute_fusion_path_targets(df5m: pd.DataFrame) -> pd.DataFrame:
    """ATR-normalized path targets on the 5m decision clock.

    For each fusion horizon k, at bar t:

    * ``ret`` = (Close[t+k] - Close[t]) / ATR[t]
    * ``mfe`` = max(0, (max(High[t+1:t+k]) - Close[t]) / ATR[t])
    * ``mae`` = min(0, (min(Low[t+1:t+k]) - Close[t]) / ATR[t])
    * ``persist`` = mean(sign(Close[t+j] - Close[t])) for j=1..k
    * ``t_mfe`` / ``t_mae`` = 1-based bar index of the first extreme

    The last ``MAX_FUSION_HORIZON_BARS`` rows are NaN (insufficient +2h future).
    """
    out = _ensure_ohlcv_time(df5m)
    n = len(out)
    close = out["close"].to_numpy(dtype=np.float64)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    atr = _atr_series(out)
    max_k = int(MAX_FUSION_HORIZON_BARS)
    n_valid = max(n - max_k, 0)
    denom = np.maximum(atr[:n_valid], _EPS) if n_valid else np.zeros(0)
    entry = close[:n_valid] if n_valid else np.zeros(0)

    for field in LABEL_V2_PATH_FIELDS:
        for key in FUSION_HORIZON_KEYS:
            out[f"{key}_{field}"] = np.full(n, np.nan, dtype=np.float64)

    if n_valid == 0:
        return out

    for key, k in zip(FUSION_HORIZON_KEYS, FUSION_HORIZON_BARS_5M):
        kk = int(k)
        fwd_close = _forward_stack(close, n_valid, kk)
        fwd_high = _forward_stack(high, n_valid, kk)
        fwd_low = _forward_stack(low, n_valid, kk)
        raw_up = (fwd_high.max(axis=1) - entry) / denom
        raw_dn = (fwd_low.min(axis=1) - entry) / denom
        ret = (fwd_close[:, -1] - entry) / denom
        delta = fwd_close - entry[:, None]
        persist = np.sign(delta).mean(axis=1)
        t_mfe = fwd_high.argmax(axis=1).astype(np.float64) + 1.0
        t_mae = fwd_low.argmin(axis=1).astype(np.float64) + 1.0
        atr_ok = np.isfinite(atr[:n_valid]) & (atr[:n_valid] > _EPS)
        nan_bad = ~atr_ok
        ret[nan_bad] = np.nan
        raw_up[nan_bad] = np.nan
        raw_dn[nan_bad] = np.nan
        persist[nan_bad] = np.nan
        t_mfe[nan_bad] = np.nan
        t_mae[nan_bad] = np.nan
        out.loc[: n_valid - 1, f"{key}_ret"] = ret
        out.loc[: n_valid - 1, f"{key}_mfe"] = np.maximum(raw_up, 0.0)
        out.loc[: n_valid - 1, f"{key}_mae"] = np.minimum(raw_dn, 0.0)
        out.loc[: n_valid - 1, f"{key}_persist"] = persist
        out.loc[: n_valid - 1, f"{key}_t_mfe"] = t_mfe
        out.loc[: n_valid - 1, f"{key}_t_mae"] = t_mae
    return out


def _py(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        val = float(value)
        return val if np.isfinite(val) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [_py(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): _py(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_py(v) for v in value]
    return value


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 3:
        return float("nan")
    ra = pd.Series(a[mask]).rank()
    rb = pd.Series(b[mask]).rank()
    return float(ra.corr(rb))


def _quantile_map(arr: np.ndarray) -> Dict[str, Optional[float]]:
    finite = np.asarray(arr, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {f"p{int(q * 100)}": None for q in _QUANTILES}
    qs = np.quantile(finite, _QUANTILES)
    return {f"p{int(q * 100)}": _py(v) for q, v in zip(_QUANTILES, qs)}


def _outcome_mix(codes: np.ndarray) -> Dict[str, float]:
    n = int(len(codes))
    mix: Dict[str, float] = {}
    for cid, name in LABEL_V2_TP_SL_NAMES.items():
        mix[name] = float(np.sum(codes == int(cid))) / float(max(n, 1))
        mix[f"{name}_n"] = float(np.sum(codes == int(cid)))
    mix["n"] = float(n)
    return mix


def _expectancy_atr(
    codes: np.ndarray,
    ret: np.ndarray,
    tp_mult: float,
    sl_mult: float,
) -> Optional[float]:
    valid = codes != int(LABEL_V2_TP_SL_AMBIGUOUS)
    if not np.any(valid):
        return None
    pnl = np.full(codes.shape, np.nan, dtype=np.float64)
    pnl[codes == int(LABEL_V2_TP_SL_TP_FIRST)] = float(tp_mult)
    pnl[codes == int(LABEL_V2_TP_SL_SL_FIRST)] = -float(sl_mult)
    neither = codes == int(LABEL_V2_TP_SL_NEITHER)
    pnl[neither] = ret[neither]
    use = valid & np.isfinite(pnl)
    if not np.any(use):
        return None
    return float(np.mean(pnl[use]))


def _class_block(
    mask: np.ndarray,
    ret: np.ndarray,
    mfe: np.ndarray,
    mae: np.ndarray,
    persist: np.ndarray,
    state_persist: np.ndarray,
    n_total: int,
) -> Dict[str, Any]:
    n = int(np.sum(mask))
    block: Dict[str, Any] = {
        "n": n,
        "rate": float(n) / float(max(n_total, 1)),
    }
    if n == 0:
        block.update(
            {
                "e_r": None,
                "r_q": _quantile_map(np.array([])),
                "mfe_q": _quantile_map(np.array([])),
                "mae_q": _quantile_map(np.array([])),
                "persist_mean": None,
                "state_persist_mean": None,
            }
        )
        return block
    block["e_r"] = _py(np.mean(ret[mask]))
    block["r_q"] = _quantile_map(ret[mask])
    block["mfe_q"] = _quantile_map(mfe[mask])
    block["mae_q"] = _quantile_map(mae[mask])
    block["persist_mean"] = _py(np.mean(persist[mask]))
    block["state_persist_mean"] = _py(np.mean(state_persist[mask]))
    return block


def _theta_key(theta: float) -> str:
    return f"{float(theta):.2f}"


def _pair_key(sl_mult: float, tp_mult: float) -> str:
    return f"sl{float(sl_mult):.2f}_tp{float(tp_mult):.2f}"


def _gate_one_horizon(
    by_theta: Mapping[str, Mapping[str, Any]],
    live_pair_key: str,
) -> Dict[str, Any]:
    """Apply the five Label V2 promotion checks per theta."""
    ranked: list[Dict[str, Any]] = []
    for tkey, row in by_theta.items():
        flags: list[str] = []
        rates = {
            name: float((row.get("classes") or {}).get(name, {}).get("rate") or 0.0)
            for name in LABEL_V2_DIRECTION_NAMES.values()
        }
        minority = min(rates.values()) if rates else 0.0
        if minority < float(LABEL_V2_MINORITY_RATE):
            flags.append(f"minority_class<{LABEL_V2_MINORITY_RATE:.2f}")
        e_bull = (row.get("classes") or {}).get("BULL", {}).get("e_r")
        e_bear = (row.get("classes") or {}).get("BEAR", {}).get("e_r")
        theta = float(row.get("theta") or 0.0)
        separated = (
            e_bull is not None
            and e_bear is not None
            and float(e_bull) > 0.0
            and float(e_bear) < 0.0
            and (float(e_bull) - float(e_bear)) >= theta
        )
        if not separated:
            flags.append("return_classes_not_separated")
        disagree = float(row.get("disagreement_rate") or 0.0)
        if disagree < float(LABEL_V2_DISAGREE_MIN):
            flags.append("path_redundant_with_endpoint")
        tp_grid = row.get("tp_sl") or {}
        live = tp_grid.get(live_pair_key) or {}
        long_mix = live.get("long") or {}
        tp_n = float(long_mix.get("TP_FIRST_n") or 0.0)
        amb_n = float(long_mix.get("AMBIGUOUS_n") or 0.0)
        wins = tp_n + amb_n
        if wins > 0 and (amb_n / wins) >= 0.5:
            flags.append("ambiguous_majority_of_tp_wins")
        persist_vals = [
            (row.get("classes") or {}).get(name, {}).get("persist_mean")
            for name in LABEL_V2_DIRECTION_NAMES.values()
        ]
        finite_p = [float(v) for v in persist_vals if v is not None]
        persist_range = (max(finite_p) - min(finite_p)) if len(finite_p) >= 2 else 0.0
        if persist_range < float(LABEL_V2_PERSIST_RANGE_MIN):
            flags.append("persistence_flat")
        ranked.append(
            {
                "theta": theta,
                "theta_key": tkey,
                "pass": len(flags) == 0,
                "flags": flags,
                "minority_rate": minority,
                "disagreement_rate": disagree,
                "persist_range": persist_range,
            }
        )
    passing = [r for r in ranked if r["pass"]]
    chosen = None
    status = "no-go"
    if passing:
        prefer = [r for r in passing if abs(float(r["theta"]) - 0.50) < 1e-9]
        chosen = prefer[0] if prefer else passing[0]
        status = "go"
    return {
        "status": status,
        "chosen_theta": None if chosen is None else chosen["theta"],
        "candidates": ranked,
    }


def summarize_label_v2(
    df5m: pd.DataFrame,
    *,
    thetas: Sequence[float] = LABEL_V2_THETA_GRID,
    tp_sl_grid: Sequence[Tuple[float, float]] = LABEL_V2_TP_SL_GRID,
    already_labeled: bool = False,
) -> Dict[str, Any]:
    """θ and TP/SL distribution report. Does not train a model.

    Args:
        df5m: 5m OHLCV (and optional ATR). Path columns are computed unless
            ``already_labeled`` is true.
        thetas: Dead-zone grid.
        tp_sl_grid: ``(sl_mult, tp_mult)`` pairs.
        already_labeled: Skip :func:`compute_fusion_path_targets` when columns exist.

    Returns:
        Nested JSON-ready dict with per-horizon stats and a go/no-go gate.
    """
    labeled = df5m if already_labeled else compute_fusion_path_targets(df5m)
    labeled = _ensure_ohlcv_time(labeled)
    n_source = len(labeled)
    close_all = labeled["close"].to_numpy(dtype=np.float64)
    high_all = labeled["high"].to_numpy(dtype=np.float64)
    low_all = labeled["low"].to_numpy(dtype=np.float64)
    atr_all = _atr_series(labeled)
    trimmed = trim_fusion_label_tail(labeled)
    n = len(trimmed)
    close = close_all[:n]
    atr = atr_all[:n]
    span: Dict[str, Any] = {"n": n, "n_source": n_source}
    if n and "time" in trimmed.columns:
        span["start"] = str(trimmed["time"].iloc[0])
        span["end"] = str(trimmed["time"].iloc[-1])

    horizons: Dict[str, Any] = {}
    stacks: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for key, k in zip(FUSION_HORIZON_KEYS, FUSION_HORIZON_BARS_5M):
        stacks[str(key)] = (
            _forward_stack(high_all, n, int(k)),
            _forward_stack(low_all, n, int(k)),
            _forward_stack(close_all, n, int(k)),
        )

    for key, k in zip(FUSION_HORIZON_KEYS, FUSION_HORIZON_BARS_5M):
        kk = int(k)
        ret = trimmed[f"{key}_ret"].to_numpy(dtype=np.float64)
        mfe = trimmed[f"{key}_mfe"].to_numpy(dtype=np.float64)
        mae = trimmed[f"{key}_mae"].to_numpy(dtype=np.float64)
        persist = trimmed[f"{key}_persist"].to_numpy(dtype=np.float64)
        valid = np.isfinite(ret) & np.isfinite(mfe) & np.isfinite(mae)
        n_valid = int(np.sum(valid))
        fwd_high, fwd_low, fwd_close = stacks[str(key)]
        entry = close
        denom = np.maximum(atr, _EPS)
        live_sl, live_tp = FUSION_DURATION_ATR_MULT[str(key)]
        live_key = _pair_key(live_sl, live_tp)
        by_theta: Dict[str, Any] = {}
        stride = np.zeros(n, dtype=bool)
        if n:
            stride[::kk] = True

        for theta in thetas:
            dirs = direction_from_return_array(ret, float(theta))
            r_path = (fwd_close - entry[:, None]) / denom[:, None]
            path_dirs = direction_from_return_array(r_path, float(theta))
            end_dir = path_dirs[:, -1] if path_dirs.size else np.zeros(n, dtype=np.int64)
            state_p = np.mean(path_dirs == end_dir[:, None], axis=1) if n else np.zeros(0)
            long_live = tp_sl_from_windows(
                fwd_high, fwd_low, entry, atr, live_tp, live_sl, "LONG"
            )
            short_live = tp_sl_from_windows(
                fwd_high, fwd_low, entry, atr, live_tp, live_sl, "SHORT"
            )
            bear = (dirs == _BEAR) & valid
            bull = (dirs == _BULL) & valid
            n_dir = int(np.sum(bear | bull))
            disagree_n = int(
                np.sum(bear & (long_live == int(LABEL_V2_TP_SL_TP_FIRST)))
                + np.sum(bull & (short_live == int(LABEL_V2_TP_SL_TP_FIRST)))
            )
            classes = {}
            for cid, name in LABEL_V2_DIRECTION_NAMES.items():
                mask = (dirs == int(cid)) & valid
                classes[name] = _class_block(
                    mask, ret, mfe, mae, persist, state_p, n_valid
                )
                mask_stride = mask & stride
                n_stride = int(np.sum(valid & stride))
                classes[name]["nonoverlap"] = _class_block(
                    mask_stride, ret, mfe, mae, persist, state_p, n_stride
                )
            tp_sl_stats: Dict[str, Any] = {}
            for sl_m, tp_m in tp_sl_grid:
                long_c = tp_sl_from_windows(
                    fwd_high, fwd_low, entry, atr, tp_m, sl_m, "LONG"
                )
                short_c = tp_sl_from_windows(
                    fwd_high, fwd_low, entry, atr, tp_m, sl_m, "SHORT"
                )
                chosen = np.full(n, int(LABEL_V2_TP_SL_NEITHER), dtype=np.int64)
                chosen[bull] = long_c[bull]
                chosen[bear] = short_c[bear]
                tp_sl_stats[_pair_key(sl_m, tp_m)] = {
                    "sl_mult": float(sl_m),
                    "tp_mult": float(tp_m),
                    "live_bracket": abs(float(sl_m) - float(live_sl)) < 1e-12
                    and abs(float(tp_m) - float(live_tp)) < 1e-12,
                    "long": _outcome_mix(long_c[valid]),
                    "short": _outcome_mix(short_c[valid]),
                    "side_from_direction": _outcome_mix(chosen[bear | bull]),
                    "expectancy_atr": _expectancy_atr(
                        chosen[bear | bull],
                        ret[bear | bull],
                        float(tp_m),
                        float(sl_m),
                    ),
                }
            by_theta[_theta_key(float(theta))] = {
                "theta": float(theta),
                "n_valid": n_valid,
                "classes": classes,
                "corr_r_mfe": _py(_spearman(ret[valid], mfe[valid])),
                "corr_r_abs_mae": _py(_spearman(ret[valid], np.abs(mae[valid]))),
                "disagreement_rate": float(disagree_n) / float(max(n_dir, 1)),
                "disagreement_n": disagree_n,
                "n_directional": n_dir,
                "bear_long_tp_first": float(
                    np.sum(bear & (long_live == int(LABEL_V2_TP_SL_TP_FIRST)))
                )
                / float(max(int(np.sum(bear)), 1)),
                "bull_short_tp_first": float(
                    np.sum(bull & (short_live == int(LABEL_V2_TP_SL_TP_FIRST)))
                )
                / float(max(int(np.sum(bull)), 1)),
                "tp_sl": tp_sl_stats,
            }

        cross: Dict[str, Any] = {}
        r30 = trimmed["h30m_ret"].to_numpy(dtype=np.float64)
        r1h = trimmed["h1h_ret"].to_numpy(dtype=np.float64)
        r2h = trimmed["h2h_ret"].to_numpy(dtype=np.float64)
        both = np.isfinite(r30) & np.isfinite(r1h) & np.isfinite(r2h)
        for theta in thetas:
            d30 = direction_from_return_array(r30, float(theta))
            d1h = direction_from_return_array(r1h, float(theta))
            d2h = direction_from_return_array(r2h, float(theta))
            n30 = int(np.sum(both & (d30 == _BULL)))
            cross[_theta_key(float(theta))] = {
                "p_30m_bull_and_1h_bull": float(
                    np.sum(both & (d30 == _BULL) & (d1h == _BULL))
                )
                / float(max(n30, 1)),
                "p_30m_bull_and_2h_not_bull": float(
                    np.sum(both & (d30 == _BULL) & (d2h != _BULL))
                )
                / float(max(n30, 1)),
                "n_30m_bull": n30,
            }

        gate = _gate_one_horizon(by_theta, live_key)
        if str(key) == "h2h" and gate["status"] == "no-go":
            gate["status"] = "regression-only"
        horizons[str(key)] = {
            "bars": kk,
            "live_sl_atr": float(live_sl),
            "live_tp_atr": float(live_tp),
            "corr_r_mfe": _py(_spearman(ret[valid], mfe[valid])),
            "corr_r_abs_mae": _py(_spearman(ret[valid], np.abs(mae[valid]))),
            "by_theta": by_theta,
            "cross_horizon": cross,
            "gate": gate,
        }

    overall = "go"
    chosen: Dict[str, Any] = {}
    for key, row in horizons.items():
        gate = row["gate"]
        chosen[key] = gate.get("chosen_theta")
        if key != "h2h" and gate.get("status") != "go":
            overall = "no-go"
        if key == "h2h" and gate.get("status") == "no-go":
            overall = "no-go"
    if overall == "go" and horizons.get("h2h", {}).get("gate", {}).get("status") == (
        "regression-only"
    ):
        overall = "go_with_2h_regression_only"

    return _py(
        {
            "span": span,
            "thetas": [float(t) for t in thetas],
            "tp_sl_grid": [{"sl": a, "tp": b} for a, b in tp_sl_grid],
            "horizons": horizons,
            "chosen_theta": chosen,
            "overall": overall,
        }
    )


def format_label_v2_table(report: Mapping[str, Any]) -> str:
    """Compact stdout table for the Label V2 sweep."""
    lines = [
        f"overall={report.get('overall')}  n={((report.get('span') or {}).get('n'))}",
        f"{'h':<6} {'th':>5} {'BEAR':>6} {'NEU':>6} {'BULL':>6} "
        f"{'E[R+/-]':>11} {'disagree':>8} {'gate':<16}",
    ]
    for key in FUSION_HORIZON_KEYS:
        hrow = (report.get("horizons") or {}).get(key) or {}
        by_theta = hrow.get("by_theta") or {}
        gate = hrow.get("gate") or {}
        chosen = gate.get("chosen_theta")
        for _tkey, row in by_theta.items():
            classes = row.get("classes") or {}
            e_b = (classes.get("BULL") or {}).get("e_r")
            e_s = (classes.get("BEAR") or {}).get("e_r")
            sep = ""
            if e_b is not None and e_s is not None:
                sep = f"{float(e_b):+.2f}/{float(e_s):+.2f}"
            chosen_hit = (
                chosen is not None
                and abs(float(row["theta"]) - float(chosen)) < 1e-9
            )
            mark = "*" if chosen_hit else " "
            status = str(gate.get("status") or "")
            lines.append(
                f"{mark}{key:<5} {float(row['theta']):5.2f} "
                f"{(classes.get('BEAR') or {}).get('rate', 0):6.1%} "
                f"{(classes.get('NEUTRAL') or {}).get('rate', 0):6.1%} "
                f"{(classes.get('BULL') or {}).get('rate', 0):6.1%} "
                f"{sep:>11} {float(row.get('disagreement_rate') or 0):8.1%} "
                f"{status:<16}"
            )
    lines.append("(* = chosen theta)")
    return "\n".join(lines)


def iter_theta_grid(
    thetas: Optional[Iterable[float]] = None,
) -> Tuple[float, ...]:
    if thetas is None:
        return tuple(float(t) for t in LABEL_V2_THETA_GRID)
    return tuple(float(t) for t in thetas)
