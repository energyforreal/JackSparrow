"""Last-bar path-edge regression bake-off. No Transformer training.

Primary target is signed path quality
``(long_mfe - long_mae) - (short_mfe - short_mae)``, not 3-class direction
and not ``|ret|``. Policy, not this module, would later threshold a scalar.
Live v11 is unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score

from feature_store.transformer_btcusd.contract import (
    FUSION_EMBARGO_BARS,
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_THETA_FROZEN,
)
from scripts.colab.direction_predictability import (
    NOISE_FLOOR,
    N_BOOT,
    VOL_TIME_COLS,
    block_bootstrap_ci,
    ci_includes,
    finite_feature_mask,
    group_column_mask,
    roc_auc_safe,
    train_only_zscore,
)
from scripts.colab.fusion_diagnostics import (
    COST_ATR,
    _jsonify,
    horizon_bars_map,
    nonoverlap_indices,
    purged_index_slices,
    walk_forward_slices,
)

CHANCE_AUC = 0.50
PATH_SIGN_FLOOR = 0.25
N_BOOT_REG = N_BOOT

PREREGISTERED_READINGS: Dict[str, str] = {
    "no_path_signal": (
        "Signed path-edge Spearman CI includes 0 and sign-AUC CI includes 0.50"
    ),
    "vol_not_edge": (
        "|path_edge| tracks rv_16 (Spearman CI excludes 0) but signed "
        "path-edge Spearman CI includes 0"
    ),
    "real_path_edge": (
        "Signed Spearman CI excludes 0, beats rv_16 by > 0.02, and "
        "path sign-AUC CI excludes 0.50"
    ),
    "endpoint_still_dead": (
        "Path-edge is real but sign-AUC vs endpoint ret on |R|>=theta "
        "includes 0.50"
    ),
}


def signed_path_edge(
    long_mfe: np.ndarray,
    long_mae: np.ndarray,
    short_mfe: np.ndarray,
    short_mae: np.ndarray,
) -> np.ndarray:
    """Long-path quality minus short-path quality (ATR units).

    Args:
        long_mfe: Upside excursion.
        long_mae: Adverse move to that upside.
        short_mfe: Downside excursion.
        short_mae: Adverse move to that downside.

    Returns:
        Positive when the long path was cleaner than the short path.
    """
    long_edge = np.asarray(long_mfe, dtype=np.float64) - np.asarray(
        long_mae, dtype=np.float64
    )
    short_edge = np.asarray(short_mfe, dtype=np.float64) - np.asarray(
        short_mae, dtype=np.float64
    )
    return long_edge - short_edge


def path_target_pack(labeled: Any, key: str) -> Dict[str, np.ndarray]:
    """Named arrays for one Label V2 horizon."""
    pack: Dict[str, np.ndarray] = {}
    ret_col = f"{key}_ret"
    if ret_col in labeled.columns:
        pack["ret"] = labeled[ret_col].to_numpy(dtype=np.float64)
    needed = ("long_mfe", "long_mae", "short_mfe", "short_mae")
    cols = {field: f"{key}_{field}" for field in needed}
    if all(col in labeled.columns for col in cols.values()):
        pack["path_signed"] = signed_path_edge(
            labeled[cols["long_mfe"]].to_numpy(dtype=np.float64),
            labeled[cols["long_mae"]].to_numpy(dtype=np.float64),
            labeled[cols["short_mfe"]].to_numpy(dtype=np.float64),
            labeled[cols["short_mae"]].to_numpy(dtype=np.float64),
        )
        pack["long_edge"] = labeled[cols["long_mfe"]].to_numpy(
            dtype=np.float64
        ) - labeled[cols["long_mae"]].to_numpy(dtype=np.float64)
        pack["short_edge"] = labeled[cols["short_mfe"]].to_numpy(
            dtype=np.float64
        ) - labeled[cols["short_mae"]].to_numpy(dtype=np.float64)
    return pack


def spearman_safe(y: np.ndarray, pred: np.ndarray) -> Optional[float]:
    """Spearman rho on finite pairs."""
    yt = np.asarray(y, dtype=np.float64)
    yp = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp)
    if int(mask.sum()) < 8:
        return None
    from scipy.stats import spearmanr

    coef, _p = spearmanr(yt[mask], yp[mask])
    if coef is None or not np.isfinite(coef):
        return None
    return float(coef)


def r2_safe(y: np.ndarray, pred: np.ndarray) -> Optional[float]:
    """R² on finite pairs; None when sklearn refuses."""
    yt = np.asarray(y, dtype=np.float64)
    yp = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp)
    if int(mask.sum()) < 8:
        return None
    try:
        return float(r2_score(yt[mask], yp[mask]))
    except ValueError:
        return None


def sign_auc(
    y: np.ndarray,
    pred: np.ndarray,
    *,
    min_abs: float,
) -> Optional[float]:
    """AUC of pred vs sign(y) on rows with |y| >= min_abs."""
    yt = np.asarray(y, dtype=np.float64)
    yp = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp) & (np.abs(yt) >= float(min_abs))
    if int(mask.sum()) < 8:
        return None
    y_bin = (yt[mask] > 0.0).astype(np.int64)
    return roc_auc_safe(y_bin, yp[mask])


def sign_expectancy_atr(
    ret: np.ndarray,
    pred: np.ndarray,
    *,
    cost: float,
    deadzone: float = 0.0,
) -> Optional[float]:
    """Mean ATR PnL from sign(pred), minus cost on non-zero sides."""
    r = np.asarray(ret, dtype=np.float64)
    p = np.asarray(pred, dtype=np.float64)
    finite = np.isfinite(r) & np.isfinite(p)
    if not np.any(finite):
        return None
    side = np.zeros(p.shape, dtype=np.float64)
    side[p > float(deadzone)] = 1.0
    side[p < -float(deadzone)] = -1.0
    pnl = side * r
    traded = finite & (side != 0.0)
    pnl[traded] -= float(cost)
    return float(np.mean(pnl[finite]))


def kept_reg_indices(
    idx: np.ndarray,
    y: np.ndarray,
    feat_ok: np.ndarray,
    horizon_bars: int,
) -> np.ndarray:
    """Finite-target, finite-feature, non-overlapping eval rows."""
    raw = np.asarray(idx, dtype=np.int64)
    raw = raw[(raw >= 0) & (raw < len(y))]
    raw = raw[np.isfinite(y[raw]) & feat_ok[raw]]
    return nonoverlap_indices(raw, int(horizon_bars))


def _new_regressors(seed: int) -> Dict[str, Any]:
    return {
        "ridge": Ridge(alpha=1.0),
        "hist_gbm": HistGradientBoostingRegressor(
            max_depth=3,
            max_iter=40,
            learning_rate=0.1,
            random_state=int(seed),
        ),
    }


def fit_predict_reg(
    name: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_eval: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    """Fit Ridge (train-only z-score) or HGB (raw)."""
    models = _new_regressors(seed)
    model = models[str(name)]
    x_tr = np.asarray(x_train, dtype=np.float64)
    x_ev = np.asarray(x_eval, dtype=np.float64)
    y_tr = np.asarray(y_train, dtype=np.float64)
    if str(name) == "ridge":
        x_tr, x_ev = train_only_zscore(x_tr, x_ev)
    model.fit(x_tr, y_tr)
    return np.asarray(model.predict(x_ev), dtype=np.float64)


def spearman_ci(
    y: np.ndarray,
    pred: np.ndarray,
    *,
    block_len: int,
    seed: int,
) -> Tuple[Optional[float], Optional[float]]:
    """Block-bootstrap CI for Spearman rho."""
    yt = np.asarray(y, dtype=np.float64)
    yp = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp)
    paired = np.stack([yt[mask], yp[mask]], axis=1)
    if paired.shape[0] < 8:
        return None, None

    def _stat(rows: np.ndarray) -> float:
        val = spearman_safe(rows[:, 0], rows[:, 1])
        return float("nan") if val is None else float(val)

    return block_bootstrap_ci(
        paired, block_len=block_len, n_boot=N_BOOT_REG, seed=seed, stat=_stat
    )


def sign_auc_ci(
    y: np.ndarray,
    pred: np.ndarray,
    *,
    min_abs: float,
    block_len: int,
    seed: int,
) -> Tuple[Optional[float], Optional[float]]:
    """Block-bootstrap CI for sign AUC."""
    yt = np.asarray(y, dtype=np.float64)
    yp = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(yt) & np.isfinite(yp) & (np.abs(yt) >= float(min_abs))
    paired = np.stack([yt[mask], yp[mask]], axis=1)
    if paired.shape[0] < 8:
        return None, None

    def _stat(rows: np.ndarray) -> float:
        val = sign_auc(rows[:, 0], rows[:, 1], min_abs=0.0)
        return float("nan") if val is None else float(val)

    return block_bootstrap_ci(
        paired, block_len=block_len, n_boot=N_BOOT_REG, seed=seed, stat=_stat
    )


def _ci_pair(raw: Any) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, None
    lo = None if raw[0] is None else float(raw[0])
    hi = None if raw[1] is None else float(raw[1])
    return lo, hi


def classify_path_reading(row: Mapping[str, Any]) -> str:
    """Map one path-edge decomposition to a pre-registered token."""
    sp_lo, sp_hi = _ci_pair(row.get("spearman_ci"))
    auc_lo, auc_hi = _ci_pair(row.get("sign_auc_path_ci"))
    ret_lo, ret_hi = _ci_pair(row.get("sign_auc_ret_ci"))
    signed_signal = not ci_includes(sp_lo, sp_hi, 0.0)
    sign_signal = not ci_includes(auc_lo, auc_hi, CHANCE_AUC)
    sp = row.get("spearman")
    rv = row.get("rv16_spearman")
    beats_rv = (
        sp is not None
        and rv is not None
        and float(sp) - float(rv) > NOISE_FLOOR
    )
    abs_lo, abs_hi = _ci_pair(row.get("abs_vs_rv16_spearman_ci"))
    vol_only = (not signed_signal) and (not ci_includes(abs_lo, abs_hi, 0.0))
    if signed_signal and sign_signal and beats_rv:
        if ci_includes(ret_lo, ret_hi, CHANCE_AUC):
            return "endpoint_still_dead"
        return "real_path_edge"
    if vol_only:
        return "vol_not_edge"
    return "no_path_signal"


def score_reg_split(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    ret: np.ndarray,
    train_idx: np.ndarray,
    eval_idx: np.ndarray,
    *,
    seed: int,
    block_len: int,
    theta: float,
    rv_idx: Optional[int],
    col_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Fit on train, decompose eval for path_signed ``y``."""
    cols = col_mask if col_mask is not None else np.ones(x.shape[1], dtype=bool)
    if not np.any(cols):
        return {"ok": False, "reason": "empty_columns"}
    pred = fit_predict_reg(
        name, x[train_idx][:, cols], y[train_idx], x[eval_idx][:, cols], seed=seed
    )
    yt = y[eval_idx]
    rt = ret[eval_idx]
    sp = spearman_safe(yt, pred)
    sp_lo, sp_hi = spearman_ci(yt, pred, block_len=block_len, seed=seed)
    path_auc = sign_auc(yt, pred, min_abs=PATH_SIGN_FLOOR)
    path_lo, path_hi = sign_auc_ci(
        yt, pred, min_abs=PATH_SIGN_FLOOR, block_len=block_len, seed=seed
    )
    ret_auc = sign_auc(rt, pred, min_abs=float(theta))
    ret_lo, ret_hi = sign_auc_ci(
        rt, pred, min_abs=float(theta), block_len=block_len, seed=seed + 1
    )
    rv_pred = None
    rv_sp = None
    if rv_idx is not None:
        rv_pred = fit_predict_reg(
            "hist_gbm",
            x[train_idx][:, [rv_idx]],
            y[train_idx],
            x[eval_idx][:, [rv_idx]],
            seed=seed + 3,
        )
        rv_sp = spearman_safe(yt, rv_pred)
    abs_y = np.abs(yt)
    abs_rv_sp = None
    abs_lo, abs_hi = None, None
    if rv_idx is not None:
        abs_rv_sp = spearman_safe(abs_y, x[eval_idx][:, rv_idx])
        abs_lo, abs_hi = spearman_ci(
            abs_y, x[eval_idx][:, rv_idx], block_len=block_len, seed=seed + 5
        )
    after_cost = {}
    for cost in COST_ATR:
        after_cost[str(cost)] = sign_expectancy_atr(rt, pred, cost=float(cost))
    row = {
        "ok": True,
        "n": int(eval_idx.size),
        "spearman": sp,
        "spearman_ci": [sp_lo, sp_hi],
        "r2": r2_safe(yt, pred),
        "rv16_spearman": rv_sp,
        "rv16_r2": r2_safe(yt, rv_pred) if rv_pred is not None else None,
        "abs_vs_rv16_spearman": abs_rv_sp,
        "abs_vs_rv16_spearman_ci": [abs_lo, abs_hi],
        "sign_auc_path": path_auc,
        "sign_auc_path_ci": [path_lo, path_hi],
        "sign_auc_ret": ret_auc,
        "sign_auc_ret_ci": [ret_lo, ret_hi],
        "theta": float(theta),
        "path_sign_floor": PATH_SIGN_FLOOR,
        "expectancy_atr_after_cost": after_cost,
    }
    row["reading"] = classify_path_reading(row)
    return _jsonify(row)


def pick_regressor_on_val(
    x: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    *,
    seed: int,
) -> Tuple[str, Dict[str, Any]]:
    """Choose ridge vs HGB by val Spearman of the primary target."""
    scores: Dict[str, Any] = {}
    best_name = "hist_gbm"
    best_sp = float("-inf")
    for name in ("ridge", "hist_gbm"):
        pred = fit_predict_reg(name, x[train_idx], y[train_idx], x[val_idx], seed=seed)
        sp = spearman_safe(y[val_idx], pred)
        scores[name] = {"spearman": sp, "r2": r2_safe(y[val_idx], pred)}
        if sp is not None and float(sp) > best_sp:
            best_sp = float(sp)
            best_name = name
    scores["chosen"] = best_name
    return best_name, scores


def permutation_null_spearman(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    *,
    seed: int,
) -> Optional[float]:
    """HGB Spearman after shuffling train targets."""
    if y_train.size < 16 or y_val.size < 8:
        return None
    rng = np.random.default_rng(int(seed))
    y_perm = np.array(y_train, copy=True)
    rng.shuffle(y_perm)
    pred = fit_predict_reg("hist_gbm", x_train, y_perm, x_val, seed=int(seed) + 9)
    return spearman_safe(y_val, pred)


def run_path_regression(
    features: np.ndarray,
    names: Sequence[str],
    labeled: Any,
    *,
    seed: int = 42,
    score_test: bool = True,
) -> Dict[str, Any]:
    """Last-bar path-edge bake-off for all Label V2 horizons."""
    raw = np.asarray(features, dtype=np.float64)
    feat_ok = finite_feature_mask(raw)
    x = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
    n = int(x.shape[0])
    slices = purged_index_slices(n)
    bars = horizon_bars_map()
    lookup = {str(name): i for i, name in enumerate(names)}
    rv_idx = lookup.get("rv_16")
    train_sl = slices["train"]
    val_sl = slices["val"]
    test_sl = slices["test"]
    n_dev = int(val_sl.stop or 0)
    report: Dict[str, Any] = {
        "preregistered_readings": dict(PREREGISTERED_READINGS),
        "noise_floor": NOISE_FLOOR,
        "primary_target": "path_signed",
        "not_primary": ["abs_ret", "direction_class"],
        "split": {
            "train": [train_sl.start or 0, train_sl.stop],
            "val": [val_sl.start, val_sl.stop],
            "test": [test_sl.start, test_sl.stop],
        },
        "horizons": {},
    }
    vol_mask = group_column_mask(names, VOL_TIME_COLS)
    for key in LABEL_V2_HORIZON_KEYS:
        print(f"  path-regression horizon {key}")
        pack = path_target_pack(labeled, str(key))
        y = pack.get("path_signed")
        ret = pack.get("ret")
        horizon: Dict[str, Any] = {"horizon_bars": int(bars[str(key)])}
        if y is None or ret is None:
            horizon["ok"] = False
            horizon["reason"] = "missing_path_columns"
            report["horizons"][str(key)] = horizon
            continue
        h_bars = int(bars[str(key)])
        block_len = max(h_bars, 12)
        theta = float(LABEL_V2_THETA_FROZEN.get(str(key), 0.50))
        train_idx = np.arange(train_sl.start or 0, train_sl.stop or 0)
        train_idx = train_idx[np.isfinite(y[train_idx]) & feat_ok[train_idx]]
        val_idx = kept_reg_indices(
            np.arange(val_sl.start or 0, val_sl.stop or 0), y, feat_ok, h_bars
        )
        test_idx = kept_reg_indices(
            np.arange(test_sl.start or 0, test_sl.stop or n), y, feat_ok, h_bars
        )
        horizon["n_train"] = int(train_idx.size)
        horizon["n_val"] = int(val_idx.size)
        horizon["n_test"] = int(test_idx.size)
        if train_idx.size < 16 or val_idx.size < 8:
            horizon["ok"] = False
            horizon["reason"] = "insufficient_rows"
            report["horizons"][str(key)] = horizon
            continue
        chosen, pick = pick_regressor_on_val(
            x, y, train_idx, val_idx, seed=seed
        )
        horizon["model_selection"] = pick
        horizon["chosen"] = chosen
        wf: List[float] = []
        for tr_sl, va_sl in walk_forward_slices(
            n_dev, folds=3, embargo=FUSION_EMBARGO_BARS
        ):
            tr = np.arange(tr_sl.start or 0, tr_sl.stop)
            va = np.arange(va_sl.start or 0, va_sl.stop)
            tr = tr[(tr < len(y)) & np.isfinite(y[tr]) & feat_ok[tr]]
            va = kept_reg_indices(va, y, feat_ok, h_bars)
            if tr.size < 16 or va.size < 8:
                continue
            pred = fit_predict_reg(chosen, x[tr], y[tr], x[va], seed=seed)
            sp = spearman_safe(y[va], pred)
            if sp is not None:
                wf.append(sp)
        horizon["walk_forward_spearman"] = {
            "mean": float(np.mean(wf)) if wf else None,
            "std": float(np.std(wf)) if len(wf) > 1 else None,
            "n_folds": int(len(wf)),
        }
        horizon["val"] = score_reg_split(
            chosen,
            x,
            y,
            ret,
            train_idx,
            val_idx,
            seed=seed,
            block_len=block_len,
            theta=theta,
            rv_idx=rv_idx,
        )
        horizon["val"]["permutation_null_spearman"] = permutation_null_spearman(
            x[train_idx], y[train_idx], x[val_idx], y[val_idx], seed=seed
        )
        horizon["val_vol_time_null"] = score_reg_split(
            chosen,
            x,
            y,
            ret,
            train_idx,
            val_idx,
            seed=seed,
            block_len=block_len,
            theta=theta,
            rv_idx=rv_idx,
            col_mask=vol_mask,
        )
        if score_test and test_idx.size >= 8:
            horizon["test"] = score_reg_split(
                chosen,
                x,
                y,
                ret,
                train_idx,
                test_idx,
                seed=seed,
                block_len=block_len,
                theta=theta,
                rv_idx=rv_idx,
            )
            horizon["test_vol_time_null"] = score_reg_split(
                chosen,
                x,
                y,
                ret,
                train_idx,
                test_idx,
                seed=seed,
                block_len=block_len,
                theta=theta,
                rv_idx=rv_idx,
                col_mask=vol_mask,
            )
        else:
            horizon["test_unused"] = True
        if "ret" in pack:
            ret_val = score_reg_split(
                chosen,
                x,
                pack["ret"],
                ret,
                train_idx,
                val_idx,
                seed=seed,
                block_len=block_len,
                theta=theta,
                rv_idx=rv_idx,
            )
            horizon["val_endpoint_ret_control"] = {
                "spearman": ret_val.get("spearman"),
                "spearman_ci": ret_val.get("spearman_ci"),
                "sign_auc_ret": ret_val.get("sign_auc_ret"),
                "reading": ret_val.get("reading"),
                "note": "Same last-bar model trained on signed R_h, not path_edge.",
            }
        horizon["discovery_reading"] = (horizon.get("val") or {}).get("reading")
        horizon["confirmatory_reading"] = (horizon.get("test") or {}).get("reading")
        report["horizons"][str(key)] = horizon
        print(f"  path {key} done reading={horizon.get('confirmatory_reading')}")
    return _jsonify(report)
