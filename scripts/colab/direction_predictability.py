"""Last-bar direction predictability bake-off. No Transformer training.

Fits unweighted last-bar logistic / HGB on train, picks on val log-loss,
and scores one confirmatory test pass. Pre-registered readings decide
chance vs magnitude vs side — not ``decide_branch``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, r2_score, roc_auc_score

from feature_store.transformer_btcusd.contract import (
    FUSION_EMBARGO_BARS,
    LABEL_V2_DIRECTION_CARDINALITY,
    LABEL_V2_DIRECTION_NAMES,
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_REG_FIELDS,
    V14_FEATURE_GROUPS,
)
from scripts.colab.fusion_diagnostics import (
    COST_ATR,
    _BEAR,
    _BULL,
    _NEUTRAL,
    _jsonify,
    balanced_accuracy,
    horizon_bars_map,
    nonoverlap_indices,
    purged_index_slices,
    raw_accuracy,
    walk_forward_slices,
)

CHANCE_BALANCED_ACC = 1.0 / 3.0
CHANCE_AUC = 0.50
NOISE_FLOOR = 0.02
NEUTRAL_DUMP_RATE = 0.95
N_BOOT = 200
N_CLASSES = LABEL_V2_DIRECTION_CARDINALITY

VOL_TIME_COLS: Tuple[str, ...] = (
    "rv_16",
    "rv_96",
    "atr_contraction",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)

PREREGISTERED_READINGS: Dict[str, str] = {
    "no_direction": (
        "Balanced-acc CI includes 0.333 and BEAR-vs-BULL AUC CI includes 0.50"
    ),
    "magnitude_not_side": (
        "NEUTRAL-vs-rest AUC CI excludes 0.50; BEAR-vs-BULL AUC CI includes 0.50"
    ),
    "real_side_signal": (
        "BEAR-vs-BULL AUC CI excludes 0.50 and log-loss beats the train class-prior"
    ),
    "transformer_left_juice": (
        "Last-bar BEAR-vs-BULL AUC CI exceeds Transformer by > 0.02 "
        "and Transformer is not a NEUTRAL dump"
    ),
}


def softmax_rows(logits: np.ndarray) -> np.ndarray:
    """Row-wise softmax for (n, C) logits."""
    z = np.asarray(logits, dtype=np.float64)
    z = z - np.max(z, axis=-1, keepdims=True)
    exp = np.exp(z)
    denom = np.maximum(exp.sum(axis=-1, keepdims=True), 1e-12)
    return exp / denom


def confusion_matrix(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = N_CLASSES,
) -> np.ndarray:
    """(C, C) counts; rows are true class, columns predicted."""
    yt = np.asarray(y_true, dtype=np.int64)
    yp = np.asarray(y_pred, dtype=np.int64)
    mat = np.zeros((int(n_classes), int(n_classes)), dtype=np.int64)
    valid = (yt >= 0) & (yp >= 0)
    for t, p in zip(yt[valid], yp[valid]):
        if t < n_classes and p < n_classes:
            mat[int(t), int(p)] += 1
    return mat


def per_class_recall(mat: np.ndarray) -> Dict[str, float]:
    """Recall per LABEL_V2 class name from a confusion matrix."""
    out: Dict[str, float] = {}
    for c in range(mat.shape[0]):
        row = float(mat[c].sum())
        name = str(LABEL_V2_DIRECTION_NAMES.get(c, c))
        out[name] = float(mat[c, c] / row) if row > 0.0 else None  # type: ignore[assignment]
    return out


def train_class_prior(y: np.ndarray, n_classes: int = N_CLASSES) -> np.ndarray:
    """Mean one-hot prior on labeled rows (y >= 0)."""
    yt = np.asarray(y, dtype=np.int64)
    yt = yt[yt >= 0]
    prior = np.full(int(n_classes), 1.0 / float(n_classes), dtype=np.float64)
    if yt.size == 0:
        return prior
    counts = np.bincount(yt, minlength=int(n_classes)).astype(np.float64)
    total = float(counts.sum())
    if total <= 0.0:
        return prior
    return counts / total


def multiclass_log_loss(
    y_true: np.ndarray,
    proba: np.ndarray,
    *,
    labels: Optional[Sequence[int]] = None,
) -> float:
    """Mean NLL. Rows with y < 0 are dropped."""
    yt = np.asarray(y_true, dtype=np.int64)
    p = np.asarray(proba, dtype=np.float64)
    valid = yt >= 0
    if not np.any(valid):
        return float("nan")
    labs = list(labels) if labels is not None else list(range(N_CLASSES))
    clipped = np.clip(p[valid], 1e-12, 1.0)
    clipped = clipped / clipped.sum(axis=1, keepdims=True)
    return float(log_loss(yt[valid], clipped, labels=labs))


def prior_log_loss(y_true: np.ndarray, prior: np.ndarray) -> float:
    """NLL of a constant class-prior predictor."""
    n = int(np.asarray(y_true).shape[0])
    tiled = np.repeat(np.asarray(prior, dtype=np.float64).reshape(1, -1), n, axis=0)
    return multiclass_log_loss(y_true, tiled)


def roc_auc_safe(y_bin: np.ndarray, scores: np.ndarray) -> Optional[float]:
    """Binary AUC, or None when only one class is present."""
    yb = np.asarray(y_bin, dtype=np.int64)
    sc = np.asarray(scores, dtype=np.float64)
    if yb.size < 4 or len(np.unique(yb)) < 2:
        return None
    try:
        return float(roc_auc_score(yb, sc))
    except ValueError:
        return None


def neutral_vs_rest_auc(y: np.ndarray, proba: np.ndarray) -> Optional[float]:
    """AUC for NEUTRAL vs BEAR+BULL using P(NEUTRAL)."""
    yt = np.asarray(y, dtype=np.int64)
    p = np.asarray(proba, dtype=np.float64)
    valid = yt >= 0
    if not np.any(valid):
        return None
    y_bin = (yt[valid] == _NEUTRAL).astype(np.int64)
    return roc_auc_safe(y_bin, p[valid, _NEUTRAL])


def bear_vs_bull_auc(y: np.ndarray, proba: np.ndarray) -> Optional[float]:
    """AUC for BULL vs BEAR on non-NEUTRAL rows using P(BULL|side)."""
    yt = np.asarray(y, dtype=np.int64)
    p = np.asarray(proba, dtype=np.float64)
    mask = (yt == _BEAR) | (yt == _BULL)
    if int(mask.sum()) < 4:
        return None
    side = p[mask, _BEAR] + p[mask, _BULL]
    score = p[mask, _BULL] / np.maximum(side, 1e-12)
    y_bin = (yt[mask] == _BULL).astype(np.int64)
    return roc_auc_safe(y_bin, score)


def block_bootstrap_ci(
    values: np.ndarray,
    *,
    block_len: int,
    n_boot: int = N_BOOT,
    seed: int = 0,
    stat: Any = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Percentile CI from a moving-block bootstrap of ``stat(values[idx])``."""
    arr = np.asarray(values)
    n = int(arr.shape[0])
    if n < 8:
        return None, None
    fn = stat if stat is not None else (lambda x: float(np.mean(x)))
    bl = max(int(block_len), 1)
    rng = np.random.default_rng(int(seed))
    n_blocks = int(np.ceil(n / float(bl)))
    stats: List[float] = []
    max_start = max(n - bl + 1, 1)
    for _ in range(int(n_boot)):
        starts = rng.integers(0, max_start, size=n_blocks)
        idx = np.concatenate([np.arange(int(s), min(int(s) + bl, n)) for s in starts])
        idx = idx[:n]
        try:
            val = float(fn(arr[idx]))
        except (TypeError, ValueError):
            continue
        if np.isfinite(val):
            stats.append(val)
    if len(stats) < 8:
        return None, None
    lo, hi = np.percentile(np.asarray(stats, dtype=np.float64), [2.5, 97.5])
    return float(lo), float(hi)


def balanced_acc_ci(
    y: np.ndarray,
    pred: np.ndarray,
    *,
    block_len: int,
    seed: int = 0,
) -> Tuple[Optional[float], Optional[float]]:
    """Bootstrap CI for balanced accuracy on paired (y, pred) rows."""
    yt = np.asarray(y, dtype=np.int64)
    yp = np.asarray(pred, dtype=np.int64)
    paired = np.stack([yt, yp], axis=1)

    def _stat(rows: np.ndarray) -> float:
        return balanced_accuracy(rows[:, 0], rows[:, 1])

    return block_bootstrap_ci(paired, block_len=block_len, seed=seed, stat=_stat)


def auc_ci(
    y_bin: np.ndarray,
    scores: np.ndarray,
    *,
    block_len: int,
    seed: int = 0,
) -> Tuple[Optional[float], Optional[float]]:
    """Bootstrap CI for binary AUC."""
    paired = np.stack(
        [np.asarray(y_bin, dtype=np.float64), np.asarray(scores, dtype=np.float64)],
        axis=1,
    )

    def _stat(rows: np.ndarray) -> float:
        val = roc_auc_safe(rows[:, 0].astype(np.int64), rows[:, 1])
        return float("nan") if val is None else float(val)

    return block_bootstrap_ci(paired, block_len=block_len, seed=seed, stat=_stat)


def ci_includes(lo: Optional[float], hi: Optional[float], value: float) -> bool:
    """True when the CI is missing or covers ``value``."""
    if lo is None or hi is None:
        return True
    return float(lo) <= float(value) <= float(hi)


def train_only_zscore(
    x_train: np.ndarray,
    x_eval: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Column z-score using train mean/std only."""
    tr = np.asarray(x_train, dtype=np.float64)
    ev = np.asarray(x_eval, dtype=np.float64)
    mean = np.mean(tr, axis=0)
    std = np.std(tr, axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return (tr - mean) / std, (ev - mean) / std


def inverse_frequency_sample_weights(
    y: np.ndarray,
    n_classes: int = N_CLASSES,
) -> np.ndarray:
    """Per-row inverse-frequency weights, mean-normalized."""
    yt = np.asarray(y, dtype=np.int64)
    counts = np.bincount(yt, minlength=int(n_classes)).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts[yt]
    weights *= float(len(yt)) / float(weights.sum())
    return weights.astype(np.float32)


def _new_models(seed: int) -> Dict[str, Any]:
    return {
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


def _align_proba(model: Any, proba: np.ndarray) -> np.ndarray:
    """Map sklearn proba columns onto classes 0..C-1."""
    classes = np.asarray(getattr(model, "classes_", np.arange(N_CLASSES)), dtype=np.int64)
    out = np.zeros((proba.shape[0], N_CLASSES), dtype=np.float64)
    for j, cls in enumerate(classes):
        if 0 <= int(cls) < N_CLASSES:
            out[:, int(cls)] = proba[:, j]
    row = out.sum(axis=1, keepdims=True)
    row = np.where(row <= 0.0, 1.0, row)
    return out / row


def fit_predict_proba(
    name: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_eval: np.ndarray,
    *,
    seed: int,
    sample_weight: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit one last-bar model. Logistic uses train-only z-score."""
    models = _new_models(seed)
    model = models[str(name)]
    x_tr = np.asarray(x_train, dtype=np.float64)
    x_ev = np.asarray(x_eval, dtype=np.float64)
    if str(name) == "logistic":
        x_tr, x_ev = train_only_zscore(x_tr, x_ev)
    fit_kw: Dict[str, Any] = {}
    if sample_weight is not None:
        fit_kw["sample_weight"] = sample_weight
    model.fit(x_tr, y_train, **fit_kw)
    pred = np.asarray(model.predict(x_ev), dtype=np.int64)
    proba = _align_proba(model, np.asarray(model.predict_proba(x_ev), dtype=np.float64))
    return pred, proba


def direction_expectancy_atr(
    ret: np.ndarray,
    y_pred: np.ndarray,
    *,
    cost: float = 0.0,
) -> Optional[float]:
    """Mean ATR PnL: long ``+ret``, short ``-ret``, NEUTRAL 0, minus cost on sides."""
    r = np.asarray(ret, dtype=np.float64)
    yp = np.asarray(y_pred, dtype=np.int64)
    finite = np.isfinite(r)
    if not np.any(finite):
        return None
    pnl = np.zeros(r.shape, dtype=np.float64)
    side = finite & ((yp == _BEAR) | (yp == _BULL))
    pnl[finite & (yp == _BULL)] = r[finite & (yp == _BULL)] - float(cost)
    pnl[finite & (yp == _BEAR)] = -r[finite & (yp == _BEAR)] - float(cost)
    pnl[finite & (yp == _NEUTRAL)] = 0.0
    if not np.any(side | (finite & (yp == _NEUTRAL))):
        return None
    return float(np.mean(pnl[finite]))


def decomposition(
    y: np.ndarray,
    pred: np.ndarray,
    proba: np.ndarray,
    *,
    prior: np.ndarray,
    block_len: int,
    seed: int,
    ret: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Confusion, AUCs, log-loss vs prior, bootstrap CIs, expectancy."""
    yt = np.asarray(y, dtype=np.int64)
    yp = np.asarray(pred, dtype=np.int64)
    p = np.asarray(proba, dtype=np.float64)
    mat = confusion_matrix(yt, yp)
    nvr = neutral_vs_rest_auc(yt, p)
    bvb = bear_vs_bull_auc(yt, p)
    ll = multiclass_log_loss(yt, p)
    pll = prior_log_loss(yt, prior)
    bal = balanced_accuracy(yt, yp)
    bal_lo, bal_hi = balanced_acc_ci(yt, yp, block_len=block_len, seed=seed)
    nvr_lo = nvr_hi = bvb_lo = bvb_hi = None
    valid = yt >= 0
    if np.any(valid):
        y_nvr = (yt[valid] == _NEUTRAL).astype(np.int64)
        nvr_lo, nvr_hi = auc_ci(
            y_nvr, p[valid, _NEUTRAL], block_len=block_len, seed=seed + 1
        )
        side = (yt == _BEAR) | (yt == _BULL)
        if int(side.sum()) >= 8:
            denom = np.maximum(p[side, _BEAR] + p[side, _BULL], 1e-12)
            bvb_lo, bvb_hi = auc_ci(
                (yt[side] == _BULL).astype(np.int64),
                p[side, _BULL] / denom,
                block_len=max(int(block_len) // 2, 1),
                seed=seed + 2,
            )
    dump_rate = float(np.mean(yp == _NEUTRAL)) if yp.size else None
    after_cost = {}
    if ret is not None:
        for cost in COST_ATR:
            after_cost[str(cost)] = direction_expectancy_atr(ret, yp, cost=float(cost))
    return _jsonify(
        {
            "n": int(yt.size),
            "balanced_acc": bal,
            "balanced_acc_ci": [bal_lo, bal_hi],
            "raw_acc": raw_accuracy(yt, yp),
            "log_loss": ll,
            "prior_log_loss": pll,
            "log_loss_beats_prior": (
                bool(np.isfinite(ll) and np.isfinite(pll) and ll < pll)
                if ll is not None and pll is not None
                else False
            ),
            "neutral_vs_rest_auc": nvr,
            "neutral_vs_rest_auc_ci": [nvr_lo, nvr_hi],
            "bear_vs_bull_auc": bvb,
            "bear_vs_bull_auc_ci": [bvb_lo, bvb_hi],
            "confusion": mat.tolist(),
            "recall": per_class_recall(mat),
            "neutral_argmax_rate": dump_rate,
            "neutral_dump": (
                dump_rate is not None and float(dump_rate) >= NEUTRAL_DUMP_RATE
            ),
            "expectancy_atr_after_cost": after_cost,
        }
    )


def classify_reading(row: Mapping[str, Any]) -> str:
    """Map one decomposition to a pre-registered token."""
    bal_lo, bal_hi = _ci_pair(row.get("balanced_acc_ci"))
    nvr_lo, nvr_hi = _ci_pair(row.get("neutral_vs_rest_auc_ci"))
    bvb_lo, bvb_hi = _ci_pair(row.get("bear_vs_bull_auc_ci"))
    no_side = ci_includes(bvb_lo, bvb_hi, CHANCE_AUC)
    no_bal = ci_includes(bal_lo, bal_hi, CHANCE_BALANCED_ACC)
    nvr_signal = not ci_includes(nvr_lo, nvr_hi, CHANCE_AUC)
    side_signal = not no_side
    beats_prior = bool(row.get("log_loss_beats_prior"))
    if side_signal and beats_prior:
        return "real_side_signal"
    if nvr_signal and no_side:
        return "magnitude_not_side"
    if no_bal and no_side:
        return "no_direction"
    if nvr_signal:
        return "magnitude_not_side"
    return "no_direction"


def _ci_pair(raw: Any) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, None
    lo = None if raw[0] is None else float(raw[0])
    hi = None if raw[1] is None else float(raw[1])
    return lo, hi


def classify_transformer_juice(
    last_bar: Mapping[str, Any],
    transformer: Mapping[str, Any],
) -> bool:
    """True when last-bar BEAR-vs-BULL AUC CI clears Transformer by > 0.02."""
    if bool(transformer.get("neutral_dump")):
        return False
    lb = last_bar.get("bear_vs_bull_auc")
    xf = transformer.get("bear_vs_bull_auc")
    if lb is None or xf is None:
        return False
    lo, _hi = _ci_pair(last_bar.get("bear_vs_bull_auc_ci"))
    if lo is None:
        return float(lb) - float(xf) > NOISE_FLOOR
    return float(lo) - float(xf) > NOISE_FLOOR


def map_times_to_rows(
    labeled_times: np.ndarray,
    query_times: np.ndarray,
) -> np.ndarray:
    """Integer row positions for query timestamps; -1 when missing."""
    idx = pd_index(labeled_times)
    q = pd_index(query_times)
    return np.asarray(idx.get_indexer(q), dtype=np.int64)


def pd_index(values: np.ndarray) -> Any:
    """UTC DatetimeIndex without importing pandas at module top for tests..."""
    import pandas as pd

    return pd.DatetimeIndex(pd.to_datetime(values, utc=True))


def finite_feature_mask(features: np.ndarray) -> np.ndarray:
    """Rows that are finite on columns that are actually populated.

    All-NaN columns (OI/funding when the 5m parquet has no derivatives) are
    ignored so EMA200 warm-up is still dropped without emptying the split.
    """
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or x.size == 0:
        return np.ones(int(x.shape[0]) if x.ndim else 0, dtype=bool)
    col_rate = np.isfinite(x).mean(axis=0)
    keep_cols = col_rate >= 0.50
    if not np.any(keep_cols):
        return np.ones(x.shape[0], dtype=bool)
    return np.isfinite(x[:, keep_cols]).all(axis=1)


def column_index_map(names: Sequence[str]) -> Dict[str, int]:
    return {str(n): i for i, n in enumerate(names)}


def group_column_mask(
    names: Sequence[str],
    group: Sequence[str],
) -> np.ndarray:
    """Boolean mask over feature columns in ``group`` that exist in ``names``."""
    lookup = column_index_map(names)
    mask = np.zeros(len(names), dtype=bool)
    for col in group:
        if col in lookup:
            mask[lookup[col]] = True
    return mask


def kept_eval_indices(
    idx: np.ndarray,
    y: np.ndarray,
    feat_ok: np.ndarray,
    horizon_bars: int,
) -> np.ndarray:
    """Valid, finite-feature, non-overlapping eval rows."""
    raw = np.asarray(idx, dtype=np.int64)
    raw = raw[(raw >= 0) & (raw < len(y))]
    raw = raw[(y[raw] >= 0) & feat_ok[raw]]
    return nonoverlap_indices(raw, int(horizon_bars))


def permutation_null_balanced_acc(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    *,
    seed: int,
) -> Optional[float]:
    """HGB balanced acc after shuffling train labels."""
    if y_train.size < 16 or y_val.size < 4:
        return None
    rng = np.random.default_rng(int(seed))
    y_perm = np.array(y_train, copy=True)
    rng.shuffle(y_perm)
    if len(np.unique(y_perm)) < 2:
        return None
    pred, _proba = fit_predict_proba(
        "hist_gbm", x_train, y_perm, x_val, seed=int(seed) + 7
    )
    return balanced_accuracy(y_val, pred)


def pick_model_on_val(
    x: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    *,
    seed: int,
    sample_weight: Optional[np.ndarray] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Choose logistic vs HGB by val log-loss (unweighted bake-off)."""
    scores: Dict[str, Any] = {}
    best_name = "hist_gbm"
    best_ll = float("inf")
    prior = train_class_prior(y[train_idx])
    for name in ("logistic", "hist_gbm"):
        pred, proba = fit_predict_proba(
            name,
            x[train_idx],
            y[train_idx],
            x[val_idx],
            seed=seed,
            sample_weight=sample_weight,
        )
        ll = multiclass_log_loss(y[val_idx], proba)
        scores[name] = {
            "log_loss": ll,
            "balanced_acc": balanced_accuracy(y[val_idx], pred),
        }
        if np.isfinite(ll) and ll < best_ll:
            best_ll = ll
            best_name = name
    scores["chosen"] = best_name
    scores["train_prior"] = prior.tolist()
    return best_name, scores


def walk_forward_variance(
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_dev: int,
    horizon_bars: int,
    seed: int,
    feat_ok: np.ndarray,
) -> Dict[str, List[float]]:
    """Last-bar fold balanced acc; not used to pick the test model."""
    out: Dict[str, List[float]] = {"logistic": [], "hist_gbm": []}
    for tr_sl, va_sl in walk_forward_slices(int(n_dev), folds=3, embargo=FUSION_EMBARGO_BARS):
        tr = np.arange(tr_sl.start or 0, tr_sl.stop)
        va = np.arange(va_sl.start or 0, va_sl.stop)
        tr = tr[(tr < len(y)) & (y[tr] >= 0) & feat_ok[tr]]
        va = kept_eval_indices(va, y, feat_ok, horizon_bars)
        if tr.size < 16 or va.size < 4 or len(np.unique(y[tr])) < 2:
            continue
        for name in out:
            pred, _p = fit_predict_proba(name, x[tr], y[tr], x[va], seed=seed)
            out[name].append(balanced_accuracy(y[va], pred))
    return out


def score_split(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    ret: np.ndarray,
    train_idx: np.ndarray,
    eval_idx: np.ndarray,
    *,
    seed: int,
    block_len: int,
    col_mask: Optional[np.ndarray] = None,
    sample_weight: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Fit on train columns, decompose eval."""
    cols = col_mask if col_mask is not None else np.ones(x.shape[1], dtype=bool)
    if not np.any(cols):
        return {"ok": False, "reason": "empty_columns"}
    pred, proba = fit_predict_proba(
        name,
        x[train_idx][:, cols],
        y[train_idx],
        x[eval_idx][:, cols],
        seed=seed,
        sample_weight=sample_weight,
    )
    prior = train_class_prior(y[train_idx])
    row = decomposition(
        y[eval_idx],
        pred,
        proba,
        prior=prior,
        block_len=block_len,
        seed=seed,
        ret=ret[eval_idx],
    )
    row["ok"] = True
    row["reading"] = classify_reading(row)
    return row


def logits_decomposition(
    y: np.ndarray,
    logits: np.ndarray,
    *,
    prior: np.ndarray,
    block_len: int,
    seed: int,
    ret: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Decompose a frozen classifier from logits (no refit)."""
    proba = softmax_rows(logits)
    pred = np.argmax(proba, axis=-1).astype(np.int64)
    row = decomposition(
        y, pred, proba, prior=prior, block_len=block_len, seed=seed, ret=ret
    )
    row["ok"] = True
    row["reading"] = classify_reading(row)
    row["source"] = "logits"
    return row


def magnitude_vs_rv16(
    x: np.ndarray,
    names: Sequence[str],
    targets: Mapping[str, np.ndarray],
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    *,
    seed: int,
) -> Dict[str, Any]:
    """HGB R² / Spearman vs an rv_16-only baseline on val."""
    lookup = column_index_map(names)
    if "rv_16" not in lookup:
        return {"ok": False, "reason": "missing_rv_16"}
    rv_i = lookup["rv_16"]
    out: Dict[str, Any] = {"ok": True, "targets": {}}
    for field, arr in targets.items():
        y = np.asarray(arr, dtype=np.float64)
        tr = train_idx[np.isfinite(y[train_idx])]
        va = val_idx[np.isfinite(y[val_idx])]
        if tr.size < 16 or va.size < 8:
            out["targets"][str(field)] = {"ok": False, "reason": "insufficient_rows"}
            continue
        full = HistGradientBoostingRegressor(
            max_depth=3, max_iter=40, learning_rate=0.1, random_state=int(seed)
        )
        base = HistGradientBoostingRegressor(
            max_depth=3, max_iter=40, learning_rate=0.1, random_state=int(seed)
        )
        full.fit(x[tr], y[tr])
        base.fit(x[tr][:, [rv_i]], y[tr])
        pred_f = full.predict(x[va])
        pred_b = base.predict(x[va][:, [rv_i]])
        yv = y[va]
        out["targets"][str(field)] = {
            "ok": True,
            "r2": _r2(yv, pred_f),
            "spearman": _spearman(yv, pred_f),
            "rv16_r2": _r2(yv, pred_b),
            "rv16_spearman": _spearman(yv, pred_b),
            "n": int(va.size),
        }
    return _jsonify(out)


def _r2(y: np.ndarray, pred: np.ndarray) -> Optional[float]:
    if y.size < 4:
        return None
    try:
        return float(r2_score(y, pred))
    except ValueError:
        return None


def _spearman(y: np.ndarray, pred: np.ndarray) -> Optional[float]:
    if y.size < 4:
        return None
    from scipy.stats import spearmanr

    coef, _p = spearmanr(y, pred)
    if coef is None or not np.isfinite(coef):
        return None
    return float(coef)


def ablation_table(
    chosen: str,
    x: np.ndarray,
    y: np.ndarray,
    ret: np.ndarray,
    names: Sequence[str],
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    *,
    seed: int,
    block_len: int,
) -> Dict[str, Any]:
    """Val-only knockout, add-one-in, and vol+time null."""
    full_mask = np.ones(x.shape[1], dtype=bool)
    full = score_split(
        chosen, x, y, ret, train_idx, val_idx, seed=seed, block_len=block_len
    )
    knockouts: Dict[str, Any] = {}
    add_one: Dict[str, Any] = {}
    for group, cols in V14_FEATURE_GROUPS.items():
        gmask = group_column_mask(names, cols)
        if not np.any(gmask):
            continue
        drop = score_split(
            chosen,
            x,
            y,
            ret,
            train_idx,
            val_idx,
            seed=seed,
            block_len=block_len,
            col_mask=full_mask & ~gmask,
        )
        only = score_split(
            chosen,
            x,
            y,
            ret,
            train_idx,
            val_idx,
            seed=seed,
            block_len=block_len,
            col_mask=gmask,
        )
        full_bal = float(full.get("balanced_acc") or 0.0)
        drop_bal = float(drop.get("balanced_acc") or 0.0)
        delta = full_bal - drop_bal
        knockouts[str(group)] = {
            **drop,
            "delta_vs_full": delta,
            "readable": abs(delta) >= NOISE_FLOOR,
        }
        add_one[str(group)] = only
    vol_mask = group_column_mask(names, VOL_TIME_COLS)
    vol_time = score_split(
        chosen,
        x,
        y,
        ret,
        train_idx,
        val_idx,
        seed=seed,
        block_len=block_len,
        col_mask=vol_mask,
    )
    return {
        "full": full,
        "knockout": knockouts,
        "add_one_in": add_one,
        "vol_time_null": vol_time,
        "noise_floor": NOISE_FLOOR,
    }


def run_direction_predictability(
    features: np.ndarray,
    names: Sequence[str],
    labels: np.ndarray,
    returns: np.ndarray,
    labeled_times: np.ndarray,
    *,
    seed: int = 42,
    score_test: bool = True,
    ablate_groups: bool = True,
    decision_times: Optional[np.ndarray] = None,
    transformer_test: Optional[Mapping[str, Any]] = None,
    transformer_logits: Optional[Mapping[str, np.ndarray]] = None,
    transformer_y: Optional[Mapping[str, np.ndarray]] = None,
    transformer_window_logits: Optional[np.ndarray] = None,
    transformer_window_times: Optional[np.ndarray] = None,
    class_weight_sensitivity: bool = False,
    mag_targets: Optional[Mapping[str, Dict[str, np.ndarray]]] = None,
) -> Dict[str, Any]:
    """Last-bar bake-off for all Label V2 horizons."""
    raw = np.asarray(features, dtype=np.float64)
    feat_ok = finite_feature_mask(raw)
    x = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
    y_all = np.asarray(labels, dtype=np.int64)
    ret_all = np.asarray(returns, dtype=np.float64)
    n = int(x.shape[0])
    slices = purged_index_slices(n)
    bars = horizon_bars_map()
    report: Dict[str, Any] = {
        "preregistered_readings": dict(PREREGISTERED_READINGS),
        "noise_floor": NOISE_FLOOR,
        "use_class_weights": False,
        "split": {
            "train": [slices["train"].start or 0, slices["train"].stop],
            "val": [slices["val"].start, slices["val"].stop],
            "test": [slices["test"].start, slices["test"].stop],
        },
        "horizons": {},
        "transformer_json": dict(transformer_test or {}),
    }
    stride_pos: Optional[np.ndarray] = None
    time_align: Dict[str, Any] = {"ok": False}
    if decision_times is not None:
        stride_pos = map_times_to_rows(labeled_times, decision_times)
        test_sl = slices["test"]
        mapped = stride_pos[stride_pos >= 0]
        in_test = mapped[
            (mapped >= int(test_sl.start or 0)) & (mapped < int(test_sl.stop or n))
        ]
        test_times = pd_index(
            labeled_times[int(test_sl.start or 0) : int(test_sl.stop or n)]
        )
        if in_test.size and len(test_times):
            in_test_times = pd_index(labeled_times[in_test])
            inside = bool(
                in_test_times.min() >= test_times.min()
                and in_test_times.max() <= test_times.max()
            )
            time_align = {
                "ok": inside,
                "n_mapped": int((stride_pos >= 0).sum()),
                "n_mapped_in_calendar_test": int(in_test.size),
                "stride_test_min": str(in_test_times.min()),
                "stride_test_max": str(in_test_times.max()),
                "calendar_test_min": str(test_times.min()),
                "calendar_test_max": str(test_times.max()),
            }
        else:
            time_align = {"ok": False, "reason": "empty_join"}
    report["time_align"] = time_align

    train_sl = slices["train"]
    val_sl = slices["val"]
    test_sl = slices["test"]
    n_dev = int(val_sl.stop or 0)

    for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
        print(
            f"  horizon {key} ({j + 1}/{len(LABEL_V2_HORIZON_KEYS)}) "
            f"score_test={score_test} ablate={ablate_groups}"
        )
        y = y_all[:, j] if y_all.ndim == 2 else y_all
        ret = ret_all[:, j] if ret_all.ndim == 2 else ret_all
        h_bars = int(bars[str(key)])
        block_len = max(h_bars, 12)
        train_idx = np.arange(train_sl.start or 0, train_sl.stop or 0)
        train_idx = train_idx[(y[train_idx] >= 0) & feat_ok[train_idx]]
        val_idx = kept_eval_indices(
            np.arange(val_sl.start or 0, val_sl.stop or 0), y, feat_ok, h_bars
        )
        test_idx = kept_eval_indices(
            np.arange(test_sl.start or 0, test_sl.stop or n), y, feat_ok, h_bars
        )
        horizon: Dict[str, Any] = {
            "horizon_bars": h_bars,
            "n_train": int(train_idx.size),
            "n_val": int(val_idx.size),
            "n_test": int(test_idx.size),
        }
        if train_idx.size < 16 or val_idx.size < 4 or len(np.unique(y[train_idx])) < 2:
            horizon["ok"] = False
            horizon["reason"] = "insufficient_rows"
            report["horizons"][str(key)] = horizon
            print(f"  horizon {key} skipped n_train={train_idx.size} n_val={val_idx.size}")
            continue
        chosen, pick = pick_model_on_val(
            x, y, train_idx, val_idx, seed=seed
        )
        horizon["model_selection"] = pick
        horizon["chosen"] = chosen
        horizon["walk_forward"] = {
            name: {
                "mean": float(np.mean(vals)) if vals else None,
                "std": float(np.std(vals)) if len(vals) > 1 else None,
                "n_folds": int(len(vals)),
            }
            for name, vals in walk_forward_variance(
                x, y, n_dev=n_dev, horizon_bars=h_bars, seed=seed, feat_ok=feat_ok
            ).items()
        }
        horizon["val"] = score_split(
            chosen,
            x,
            y,
            ret,
            train_idx,
            val_idx,
            seed=seed,
            block_len=block_len,
        )
        horizon["val"]["permutation_null_balanced_acc"] = permutation_null_balanced_acc(
            x[train_idx], y[train_idx], x[val_idx], y[val_idx], seed=seed
        )
        if ablate_groups:
            horizon["ablation_val"] = ablation_table(
                chosen,
                x,
                y,
                ret,
                names,
                train_idx,
                val_idx,
                seed=seed,
                block_len=block_len,
            )
        if score_test and test_idx.size >= 4:
            horizon["test"] = score_split(
                chosen,
                x,
                y,
                ret,
                train_idx,
                test_idx,
                seed=seed,
                block_len=block_len,
            )
            vol_mask = group_column_mask(names, VOL_TIME_COLS)
            horizon["test_vol_time_null"] = score_split(
                chosen,
                x,
                y,
                ret,
                train_idx,
                test_idx,
                seed=seed,
                block_len=block_len,
                col_mask=vol_mask,
            )
        else:
            horizon["test_unused"] = True
        if stride_pos is not None:
            stride_test = stride_pos[stride_pos >= 0]
            stride_test = stride_test[
                (stride_test >= int(test_sl.start or 0))
                & (stride_test < int(test_sl.stop or n))
            ]
            stride_test = kept_eval_indices(stride_test, y, feat_ok, h_bars)
            if stride_test.size >= 4:
                horizon["test_stride4"] = score_split(
                    chosen,
                    x,
                    y,
                    ret,
                    train_idx,
                    stride_test,
                    seed=seed,
                    block_len=block_len,
                )
        if class_weight_sensitivity:
            weights = inverse_frequency_sample_weights(y[train_idx])
            horizon["class_weight_sensitivity_val"] = score_split(
                chosen,
                x,
                y,
                ret,
                train_idx,
                val_idx,
                seed=seed,
                block_len=block_len,
                sample_weight=weights,
            )
        if mag_targets is not None and str(key) in mag_targets:
            horizon["magnitude"] = magnitude_vs_rv16(
                x,
                names,
                mag_targets[str(key)],
                train_idx,
                val_idx,
                seed=seed,
            )
        prior = train_class_prior(y[train_idx])

        def _window_logits_for(sl: slice) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
            if transformer_window_logits is None or transformer_window_times is None:
                return None, None
            wpos = map_times_to_rows(labeled_times, transformer_window_times)
            keep = (
                (wpos >= int(sl.start or 0))
                & (wpos < int(sl.stop or n))
                & (wpos >= 0)
                & feat_ok[np.clip(wpos, 0, n - 1)]
                & (y[np.clip(wpos, 0, n - 1)] >= 0)
            )
            if int(keep.sum()) < 4:
                return None, None
            return transformer_window_logits[keep, j, :], y[wpos[keep]]

        xf_val_logits, xf_val_y = _window_logits_for(val_sl)
        if xf_val_logits is not None and xf_val_y is not None:
            horizon["transformer_val"] = logits_decomposition(
                xf_val_y,
                xf_val_logits,
                prior=prior,
                block_len=block_len,
                seed=seed,
            )
        xf_logits = (transformer_logits or {}).get(str(key))
        xf_y = (transformer_y or {}).get(str(key))
        if xf_logits is None:
            xf_logits, xf_y = _window_logits_for(test_sl)
        if xf_logits is not None and xf_y is not None:
            horizon["transformer"] = logits_decomposition(
                xf_y,
                xf_logits,
                prior=prior,
                block_len=block_len,
                seed=seed,
            )
            lb_cmp = horizon.get("test_stride4") or horizon.get("test") or {}
            horizon["transformer_left_juice"] = classify_transformer_juice(
                lb_cmp, horizon["transformer"]
            )
        elif transformer_test:
            raw_json = (transformer_test.get("test_metrics") or {}).get(str(key)) or {}
            horizon["transformer_json"] = dict(raw_json)
            horizon["transformer_confusion"] = False
        horizon["discovery_reading"] = (horizon.get("val") or {}).get("reading")
        horizon["confirmatory_reading"] = (horizon.get("test") or {}).get("reading")
        report["horizons"][str(key)] = horizon
        print(f"  horizon {key} done reading={horizon.get('confirmatory_reading')}")
    return _jsonify(report)


def path_magnitude_targets(
    labeled: Any,
) -> Dict[str, Dict[str, np.ndarray]]:
    """``|ret|`` and path MFE/MAE columns per horizon."""
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for key in LABEL_V2_HORIZON_KEYS:
        pack: Dict[str, np.ndarray] = {}
        ret_col = f"{key}_ret"
        if ret_col in labeled.columns:
            pack["abs_ret"] = np.abs(labeled[ret_col].to_numpy(dtype=np.float64))
        for field in LABEL_V2_REG_FIELDS:
            col = f"{key}_{field}"
            if col in labeled.columns:
                pack[str(field)] = labeled[col].to_numpy(dtype=np.float64)
        if pack:
            out[str(key)] = pack
    return out


def return_matrix(labeled: Any) -> np.ndarray:
    """``(n, H)`` ATR-normalized endpoint returns."""
    n = len(labeled)
    r = np.full((n, len(LABEL_V2_HORIZON_KEYS)), np.nan, dtype=np.float64)
    for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
        col = f"{key}_ret"
        if col in labeled.columns:
            r[:, j] = labeled[col].to_numpy(dtype=np.float64)
    return r
