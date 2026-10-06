"""Search a feature-mask and Label V2 target pair on the train block.

Each Optuna trial picks v14 feature groups, a SHAP keep fraction, per-horizon
theta, which horizons are trained, and whether path loss is on. Direction
labels are rebuilt from stored ``ret``. Walk-forward balanced accuracy is
scored inside the train block. The notebook validation split and the test
tail are not loaded.

This module does not train ``MtfFusionTransformer``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from feature_store.transformer_btcusd.contract import (
    FEATURE_CONTRACT_VERSION_V15,
    FUSION_EMBARGO_BARS,
    FUSION_INPUT_RESOLUTIONS,
    LABEL_V2_DIRECTION_CARDINALITY,
    LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS,
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_MINORITY_RATE,
    LABEL_V2_PATH_LOSS_WEIGHTS,
    LABEL_V2_REG_FIELDS,
    LABEL_V2_THETA_GRID,
    V14_FEATURE_GROUP_ORDER,
    V14_FEATURE_GROUPS,
    fusion_feature_cols_v14,
)
from feature_store.transformer_btcusd.mtf_features import fusion_feature_fingerprint_v14
from feature_store.transformer_btcusd.mtf_labels_v2 import direction_from_return_array
from scripts.colab.fusion_diagnostics import balanced_accuracy, walk_forward_slices
from scripts.colab.path_regression import signed_path_edge

_RET_INDEX = LABEL_V2_REG_FIELDS.index("ret")
_LONG_MFE = LABEL_V2_REG_FIELDS.index("long_mfe")
_LONG_MAE = LABEL_V2_REG_FIELDS.index("long_mae")
_SHORT_MFE = LABEL_V2_REG_FIELDS.index("short_mfe")
_SHORT_MAE = LABEL_V2_REG_FIELDS.index("short_mae")
_KEEP_FRACS: Tuple[float, ...] = (0.25, 0.50, 0.75, 1.0)
_MIN_RANK_ROWS = 32


@dataclass(frozen=True)
class LabelFeatureSpec:
    """One candidate pair. ``keep_frac`` is applied after SHAP ranking."""

    groups: Tuple[str, ...]
    keep_frac: float
    thetas: Mapping[str, float]
    active_horizons: Tuple[str, ...]
    path_on: bool


def train_block_end(n_samples: int, train_frac: float = 0.70) -> int:
    """First index excluded from the search. Matches the purged train cut."""
    end = int(int(n_samples) * float(train_frac))
    if end < 8:
        raise ValueError(f"Train block is too small: n={n_samples} frac={train_frac}")
    return end


def group_column_indices(
    groups: Sequence[str],
    names: Sequence[str],
) -> List[int]:
    """v14 column positions for ``groups``, in contract order."""
    allowed = {str(name) for name in groups}
    lookup = {str(col): i for i, col in enumerate(names)}
    indices: List[int] = []
    for group in V14_FEATURE_GROUP_ORDER:
        if group not in allowed:
            continue
        for col in V14_FEATURE_GROUPS[group]:
            indices.append(int(lookup[str(col)]))
    return indices


def select_top_columns(
    candidates: Sequence[int],
    importance: np.ndarray,
    k: int,
) -> List[int]:
    """Keep the ``k`` highest-importance candidates, returned in v14 order."""
    cols = [int(i) for i in candidates]
    if not cols:
        return []
    kk = max(1, min(int(k), len(cols)))
    if kk >= len(cols):
        return cols
    scores = np.asarray(importance, dtype=np.float64).reshape(-1)
    if int(scores.shape[0]) != len(cols):
        raise ValueError(
            f"Importance length {scores.shape[0]} != candidates {len(cols)}"
        )
    order = np.argsort(-scores, kind="mergesort")
    chosen = [cols[int(i)] for i in order[:kk]]
    return sorted(chosen)


def label_gate_ok(
    y: np.ndarray,
    ret: np.ndarray,
    theta: float,
    *,
    minority_rate: float = LABEL_V2_MINORITY_RATE,
) -> bool:
    """True when the 3-class label is usable for a balanced-accuracy search.

    Minority class must be at least ``minority_rate``. Bull mean return must
    be positive, bear mean return negative, and their gap at least ``theta``.
    """
    labels = np.asarray(y, dtype=np.int64)
    values = np.asarray(ret, dtype=np.float64)
    valid = (labels >= 0) & np.isfinite(values)
    labels = labels[valid]
    values = values[valid]
    if int(labels.size) < 30:
        return False
    rates = [
        float(np.mean(labels == c))
        for c in range(int(LABEL_V2_DIRECTION_CARDINALITY))
    ]
    if min(rates) < float(minority_rate):
        return False
    bull = values[labels == 2]
    bear = values[labels == 0]
    if bull.size == 0 or bear.size == 0:
        return False
    e_bull = float(np.mean(bull))
    e_bear = float(np.mean(bear))
    return bool(
        e_bull > 0.0
        and e_bear < 0.0
        and (e_bull - e_bear) >= abs(float(theta))
    )


def direction_matrix(ret: np.ndarray, thetas: Mapping[str, float]) -> np.ndarray:
    """``(n, H)`` classes from per-horizon theta. Non-finite return is -1."""
    values = np.asarray(ret, dtype=np.float64)
    y = np.full(values.shape, -1, dtype=np.int64)
    for j, key in enumerate(LABEL_V2_HORIZON_KEYS):
        y[:, j] = direction_from_return_array(values[:, j], float(thetas[str(key)]))
    return y


def stack_timeframes(last_bars: np.ndarray, columns: Sequence[int]) -> np.ndarray:
    """Concat last-bar columns across timeframes. Shape ``(n, n_tf * k)``."""
    idx = [int(i) for i in columns]
    picked = np.asarray(last_bars, dtype=np.float64)[:, :, idx]
    n_rows, n_tf, k = picked.shape
    return picked.reshape(n_rows, n_tf * k)


def _stride_sample(n_rows: int, k: int) -> np.ndarray:
    n = int(n_rows)
    take = max(1, min(int(k), n))
    if n <= take:
        return np.arange(n, dtype=np.int64)
    step = float(n) / float(take)
    idx = (np.arange(take, dtype=np.float64) * step).astype(np.int64)
    return np.unique(np.clip(idx, 0, n - 1))


def _new_classifier(seed: int) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_depth=3,
        max_iter=40,
        learning_rate=0.1,
        random_state=int(seed),
    )


def _class_weights(y: np.ndarray) -> np.ndarray:
    labels = np.asarray(y, dtype=np.int64)
    counts = np.bincount(labels, minlength=LABEL_V2_DIRECTION_CARDINALITY).astype(
        np.float64
    )
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts[labels]
    weights *= float(len(labels)) / float(weights.sum())
    return weights.astype(np.float64)


def _fit_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_eval: np.ndarray,
    *,
    seed: int,
) -> Optional[np.ndarray]:
    classes = np.unique(y_train)
    if int(classes.size) < 2:
        return None
    model = _new_classifier(seed)
    model.fit(x_train, y_train, sample_weight=_class_weights(y_train))
    return np.asarray(model.predict(x_eval), dtype=np.int64)


def _mean_abs_vector(values: Any, n_features: int) -> np.ndarray:
    """Mean |SHAP| over samples and classes, keeping the feature axis."""
    width = int(n_features)
    if isinstance(values, list):
        reduced = []
        for item in values:
            mat = np.asarray(item, dtype=np.float64)
            reduced.append(np.mean(np.abs(mat), axis=0) if mat.ndim > 1 else np.abs(mat))
        stacked = np.stack(reduced, axis=0)
        return np.mean(stacked, axis=0)
    raw = getattr(values, "values", values)
    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 1:
        return np.abs(arr)
    matches = [i for i, size in enumerate(arr.shape) if int(size) == width]
    if len(matches) != 1:
        raise ValueError(f"Cannot find {width} features in SHAP shape {arr.shape}")
    feature_axis = matches[0]
    reduce = tuple(i for i in range(arr.ndim) if i != feature_axis)
    return np.mean(np.abs(arr), axis=reduce)


def tree_shap_importance(
    model: HistGradientBoostingClassifier,
    rows: np.ndarray,
) -> np.ndarray:
    """Mean absolute TreeSHAP over classes and explained rows."""
    import shap

    matrix = np.asarray(rows, dtype=np.float64)
    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(matrix)
    return _mean_abs_vector(values, int(matrix.shape[1]))


def base_column_importance(
    flat_importance: np.ndarray,
    *,
    n_timeframes: int,
    n_columns: int,
) -> np.ndarray:
    """Average a stacked-timeframe importance vector down to base columns."""
    flat = np.asarray(flat_importance, dtype=np.float64).reshape(-1)
    expected = int(n_timeframes) * int(n_columns)
    if int(flat.shape[0]) != expected:
        raise ValueError(f"Expected {expected} importances, got {flat.shape[0]}")
    shaped = flat.reshape(int(n_timeframes), int(n_columns))
    return np.mean(np.abs(shaped), axis=0)


def _rank_importance(
    x_rank: np.ndarray,
    y_rank: np.ndarray,
    x_explain: np.ndarray,
    *,
    n_timeframes: int,
    n_columns: int,
    seed: int,
) -> np.ndarray:
    model = _new_classifier(seed)
    model.fit(x_rank, y_rank, sample_weight=_class_weights(y_rank))
    flat = tree_shap_importance(model, x_explain)
    return base_column_importance(
        flat, n_timeframes=n_timeframes, n_columns=n_columns
    )


def _spearman(y: np.ndarray, pred: np.ndarray) -> float:
    left = np.asarray(y, dtype=np.float64)
    right = np.asarray(pred, dtype=np.float64)
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 8:
        return 0.0
    left = left[mask]
    right = right[mask]
    if float(np.std(left)) < 1e-12 or float(np.std(right)) < 1e-12:
        return 0.0
    from scipy.stats import spearmanr

    coef, _p = spearmanr(left, right)
    if coef is None or not np.isfinite(float(coef)):
        return 0.0
    return float(coef)


def _path_beats_rv16(
    x_sel: np.ndarray,
    rv16: np.ndarray,
    path: np.ndarray,
    horizon_index: int,
    train_sl: slice,
    val_sl: slice,
    *,
    seed: int,
) -> bool:
    edge = signed_path_edge(
        path[:, horizon_index, _LONG_MFE],
        path[:, horizon_index, _LONG_MAE],
        path[:, horizon_index, _SHORT_MFE],
        path[:, horizon_index, _SHORT_MAE],
    )
    y_tr = edge[train_sl]
    y_va = edge[val_sl]
    finite_tr = np.isfinite(y_tr)
    finite_va = np.isfinite(y_va)
    if int(finite_tr.sum()) < 32 or int(finite_va.sum()) < 16:
        return False
    full = HistGradientBoostingRegressor(
        max_depth=3, max_iter=30, learning_rate=0.1, random_state=int(seed)
    )
    base = HistGradientBoostingRegressor(
        max_depth=3, max_iter=30, learning_rate=0.1, random_state=int(seed)
    )
    full.fit(x_sel[train_sl][finite_tr], y_tr[finite_tr])
    base.fit(rv16[train_sl][finite_tr], y_tr[finite_tr])
    pred_full = full.predict(x_sel[val_sl][finite_va])
    pred_base = base.predict(rv16[val_sl][finite_va])
    return _spearman(y_va[finite_va], pred_full) > _spearman(y_va[finite_va], pred_base)


def _walk_forward_accuracy(
    x_sel: np.ndarray,
    y: np.ndarray,
    *,
    folds: Sequence[Tuple[slice, slice]],
    seed: int,
) -> float:
    scores: List[float] = []
    for train_sl, val_sl in folds:
        y_tr = y[train_sl]
        y_va = y[val_sl]
        keep_tr = y_tr >= 0
        keep_va = y_va >= 0
        if int(keep_tr.sum()) < 16 or int(keep_va.sum()) < 8:
            continue
        pred = _fit_predict(
            x_sel[train_sl][keep_tr],
            y_tr[keep_tr],
            x_sel[val_sl][keep_va],
            seed=seed,
        )
        if pred is None:
            continue
        scores.append(balanced_accuracy(y_va[keep_va], pred))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def score_label_feature_pair(
    last_bars: np.ndarray,
    path: np.ndarray,
    spec: LabelFeatureSpec,
    *,
    feature_names: Sequence[str],
    folds: int = 3,
    embargo: int = FUSION_EMBARGO_BARS,
    explain_n: int = 512,
    rank_rows: int = 8000,
    seed: int = 42,
    importance: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Score one pair. ``importance`` skips TreeSHAP when provided per horizon.

    ``last_bars`` is ``(n, n_tf, n_features)`` and must already be the train
    block. ``path`` is ``(n, H, len(LABEL_V2_REG_FIELDS))``.
    """
    names = [str(col) for col in feature_names]
    candidates = group_column_indices(spec.groups, names)
    active = [str(key) for key in spec.active_horizons if str(key) in LABEL_V2_HORIZON_KEYS]
    empty: Dict[str, Any] = {
        "objective": 0.0,
        "balanced_acc": 0.0,
        "gate_passed": False,
        "selected_cols": [],
        "groups_kept": [],
        "reject_reason": "empty_spec",
    }
    if not candidates or not active:
        return empty
    ret = np.asarray(path[:, :, _RET_INDEX], dtype=np.float64)
    y_dir = direction_matrix(ret, spec.thetas)
    for key in active:
        j = list(LABEL_V2_HORIZON_KEYS).index(key)
        if not label_gate_ok(y_dir[:, j], ret[:, j], float(spec.thetas[key])):
            empty["reject_reason"] = f"label_gate:{key}"
            return empty
    n_rows = int(last_bars.shape[0])
    n_tf = int(last_bars.shape[1])
    wf = walk_forward_slices(n_rows, folds=int(folds), embargo=int(embargo))
    if not wf:
        empty["reject_reason"] = "no_walk_forward_folds"
        return empty
    keep_n = max(1, int(round(len(candidates) * float(spec.keep_frac))))
    if importance is not None:
        base_imp = np.asarray(importance, dtype=np.float64).reshape(-1)
    elif keep_n >= len(candidates):
        base_imp = np.ones(len(candidates), dtype=np.float64)
    else:
        base_imp = _shap_rank_active(
            last_bars,
            y_dir,
            candidates,
            active,
            wf[0][0],
            n_timeframes=n_tf,
            explain_n=int(explain_n),
            rank_rows=int(rank_rows),
            seed=int(seed),
        )
    chosen = select_top_columns(candidates, base_imp, keep_n)
    if not chosen:
        empty["reject_reason"] = "no_columns"
        return empty
    x_sel = stack_timeframes(last_bars, chosen)
    accs = [
        _walk_forward_accuracy(
            x_sel,
            y_dir[:, list(LABEL_V2_HORIZON_KEYS).index(key)],
            folds=wf,
            seed=int(seed) + j,
        )
        for j, key in enumerate(active)
    ]
    balanced = float(np.mean(accs)) if accs else 0.0
    path_ok = True
    if spec.path_on:
        rv_idx = names.index("rv_16")
        rv16 = np.asarray(last_bars[:, 0, rv_idx], dtype=np.float64).reshape(-1, 1)
        train_sl, val_sl = wf[-1]
        path_ok = all(
            _path_beats_rv16(
                x_sel,
                rv16,
                np.asarray(path),
                list(LABEL_V2_HORIZON_KEYS).index(key),
                train_sl,
                val_sl,
                seed=int(seed),
            )
            for key in active
        )
    selected = [names[i] for i in chosen]
    kept_groups = [
        group
        for group in V14_FEATURE_GROUP_ORDER
        if any(col in selected for col in V14_FEATURE_GROUPS[group])
    ]
    gate_passed = bool(path_ok and balanced > 0.0)
    reason = None if gate_passed else "path_below_rv16" if spec.path_on else "no_accuracy"
    return {
        "objective": balanced if gate_passed else 0.0,
        "balanced_acc": balanced,
        "gate_passed": gate_passed,
        "selected_cols": selected,
        "groups_kept": kept_groups,
        "reject_reason": reason,
    }


def _shap_rank_active(
    last_bars: np.ndarray,
    y_dir: np.ndarray,
    candidates: Sequence[int],
    active: Sequence[str],
    train_sl: slice,
    *,
    n_timeframes: int,
    explain_n: int,
    rank_rows: int,
    seed: int,
) -> np.ndarray:
    x_all = stack_timeframes(last_bars[train_sl], candidates)
    rank_idx = _stride_sample(int(x_all.shape[0]), int(rank_rows))
    explain_idx = _stride_sample(int(x_all.shape[0]), int(explain_n))
    pooled = np.zeros(len(candidates), dtype=np.float64)
    used = 0
    for key in active:
        j = list(LABEL_V2_HORIZON_KEYS).index(str(key))
        y_all = y_dir[train_sl, j]
        y_rank = y_all[rank_idx]
        keep = y_rank >= 0
        if int(keep.sum()) < _MIN_RANK_ROWS or len(np.unique(y_rank[keep])) < 2:
            continue
        explain_y = y_all[explain_idx]
        explain_keep = explain_y >= 0
        rows = x_all[explain_idx][explain_keep]
        if int(rows.shape[0]) < 8:
            rows = x_all[rank_idx][keep][: int(explain_n)]
        pooled += _rank_importance(
            x_all[rank_idx][keep],
            y_rank[keep],
            rows,
            n_timeframes=n_timeframes,
            n_columns=len(candidates),
            seed=int(seed) + j,
        )
        used += 1
    if used == 0:
        return np.ones(len(candidates), dtype=np.float64)
    return pooled / float(used)


def combo_fingerprint(
    selected_cols: Sequence[str],
    thetas: Mapping[str, float],
    horizon_weights: Sequence[float],
    path_weights: Mapping[str, float],
) -> str:
    """Stable hash of the frozen feature and label pair."""
    payload = {
        "selected_cols": list(selected_cols),
        "label_v2_theta": {str(k): float(v) for k, v in thetas.items()},
        "horizon_loss_weights": [float(v) for v in horizon_weights],
        "path_loss_weights": {str(k): float(v) for k, v in path_weights.items()},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build_selection_payload(
    result: Mapping[str, Any],
    *,
    n_samples: int,
    train_end: int,
    n_trials: int,
    complete: bool,
) -> Dict[str, Any]:
    """JSON document the research trainer can load later."""
    names = list(fusion_feature_cols_v14())
    selected = [str(col) for col in result.get("selected_cols") or []]
    thetas = {str(k): float(v) for k, v in dict(result.get("thetas") or {}).items()}
    horizon_weights = [float(v) for v in result.get("horizon_loss_weights") or []]
    path_weights = {
        str(k): float(v) for k, v in dict(result.get("path_loss_weights") or {}).items()
    }
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V15,
        "parent_fingerprint": fusion_feature_fingerprint_v14(),
        "selection_fingerprint": combo_fingerprint(
            selected, thetas, horizon_weights, path_weights
        ),
        "objective": "train_block_walk_forward_balanced_acc",
        "split": "train_block_walk_forward",
        "n_samples": int(n_samples),
        "train_end": int(train_end),
        "n_trials": int(n_trials),
        "complete": bool(complete),
        "gate_passed": bool(result.get("gate_passed")),
        "best_balanced_acc": float(result.get("balanced_acc") or 0.0),
        "selected_cols": selected,
        "dropped_cols": [col for col in names if col not in set(selected)],
        "groups_kept": list(result.get("groups_kept") or []),
        "n_features_full": len(names),
        "n_features_selected": len(selected),
        "label_v2_theta": thetas,
        "horizon_loss_weights": horizon_weights,
        "path_loss_weights": path_weights,
        "experiment": str(result.get("experiment") or "later_direction_only"),
        "reject_reason": result.get("reject_reason"),
    }


def write_selection(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write ``selection.json``."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(dest)


def load_train_block(
    windows_dir: Path,
    *,
    train_frac: float = 0.70,
) -> Tuple[np.ndarray, np.ndarray, int, int]:
    """Last bars and Label V2 path targets for the train block only.

    Returns ``(last_bars, path, n_samples, train_end)``. Validation and test
    rows are not read from the window files.
    """
    root = Path(windows_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    n_samples = int(manifest["n_samples"])
    train_end = train_block_end(n_samples, train_frac)
    names = list(fusion_feature_cols_v14())
    n_feat = len(names)
    if int(manifest.get("n_features") or n_feat) != n_feat:
        raise ValueError(
            f"Cache n_features={manifest.get('n_features')} != contract {n_feat}"
        )
    blocks: List[np.ndarray] = []
    for res in FUSION_INPUT_RESOLUTIONS:
        arr = np.load(root / f"windows_{res}.npy", mmap_mode="r")
        if int(arr.shape[0]) < train_end or int(arr.shape[-1]) != n_feat:
            raise ValueError(f"Unexpected window shape for {res}: {arr.shape}")
        blocks.append(np.array(arr[:train_end, -1, :], dtype=np.float32, copy=True))
        del arr
    last_bars = np.stack(blocks, axis=1)
    np.nan_to_num(last_bars, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    y_reg = np.load(root / "labels_reg.npy", mmap_mode="r")
    if int(y_reg.shape[0]) < train_end:
        raise ValueError(f"labels_reg rows {y_reg.shape[0]} < train_end {train_end}")
    path = np.array(y_reg[:train_end], dtype=np.float32, copy=True)
    del y_reg
    return last_bars, path, n_samples, train_end


def _spec_from_trial(trial: Any) -> LabelFeatureSpec:
    groups = tuple(
        group
        for group in V14_FEATURE_GROUP_ORDER
        if int(trial.suggest_categorical(f"g_{group}", [0, 1])) == 1
    )
    thetas = {
        str(key): float(trial.suggest_categorical(f"theta_{key}", list(LABEL_V2_THETA_GRID)))
        for key in LABEL_V2_HORIZON_KEYS
    }
    active = tuple(
        str(key)
        for key in LABEL_V2_HORIZON_KEYS
        if int(trial.suggest_categorical(f"h_{key}", [0, 1])) == 1
    )
    path_on = int(trial.suggest_categorical("path_on", [0, 1])) == 1
    keep_frac = float(trial.suggest_categorical("keep_frac", list(_KEEP_FRACS)))
    return LabelFeatureSpec(
        groups=groups,
        keep_frac=keep_frac,
        thetas=thetas,
        active_horizons=active,
        path_on=path_on,
    )


def _weights_for_spec(spec: LabelFeatureSpec) -> Tuple[List[float], Dict[str, float], str]:
    horizon_weights = [
        1.0 if str(key) in set(spec.active_horizons) else 0.0
        for key in LABEL_V2_HORIZON_KEYS
    ]
    if spec.path_on:
        return horizon_weights, dict(LABEL_V2_PATH_LOSS_WEIGHTS), "direction_and_path"
    return (
        horizon_weights,
        dict(LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS),
        "later_direction_only",
    )


def run_feature_label_search(
    last_bars: np.ndarray,
    path: np.ndarray,
    *,
    n_samples: int,
    train_end: int,
    n_trials: int,
    output_path: Path,
    feature_names: Sequence[str] = (),
    folds: int = 3,
    embargo: int = FUSION_EMBARGO_BARS,
    explain_n: int = 512,
    rank_rows: int = 8000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Maximize train-block balanced accuracy. Writes the best pair as it goes."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    names = list(feature_names) if feature_names else list(fusion_feature_cols_v14())
    best: Dict[str, Any] = {
        "balanced_acc": 0.0,
        "gate_passed": False,
        "selected_cols": [],
        "groups_kept": [],
        "thetas": {str(k): 0.50 for k in LABEL_V2_HORIZON_KEYS},
        "horizon_loss_weights": [1.0, 1.0, 1.0, 1.0],
        "path_loss_weights": dict(LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS),
        "experiment": "later_direction_only",
        "reject_reason": "no_trial",
    }

    def _persist(complete: bool) -> None:
        payload = build_selection_payload(
            best,
            n_samples=n_samples,
            train_end=train_end,
            n_trials=int(n_trials),
            complete=complete,
        )
        write_selection(output_path, payload)

    def objective(trial: Any) -> float:
        spec = _spec_from_trial(trial)
        scored = score_label_feature_pair(
            last_bars,
            path,
            spec,
            feature_names=names,
            folds=folds,
            embargo=embargo,
            explain_n=explain_n,
            rank_rows=rank_rows,
            seed=seed,
        )
        horizon_weights, path_weights, experiment = _weights_for_spec(spec)
        trial.set_user_attr("balanced_acc", float(scored["balanced_acc"]))
        trial.set_user_attr("gate_passed", bool(scored["gate_passed"]))
        trial.set_user_attr("selected_cols", list(scored["selected_cols"]))
        trial.set_user_attr("reject_reason", scored.get("reject_reason"))
        objective_value = float(scored["objective"])
        if objective_value > float(best["balanced_acc"]):
            best.update(
                {
                    "balanced_acc": float(scored["balanced_acc"]),
                    "gate_passed": bool(scored["gate_passed"]),
                    "selected_cols": list(scored["selected_cols"]),
                    "groups_kept": list(scored["groups_kept"]),
                    "thetas": {str(k): float(v) for k, v in spec.thetas.items()},
                    "horizon_loss_weights": horizon_weights,
                    "path_loss_weights": path_weights,
                    "experiment": experiment,
                    "reject_reason": scored.get("reject_reason"),
                }
            )
            _persist(False)
        print(
            f"trial {trial.number}: objective={objective_value:.4f} "
            f"balanced_acc={float(scored['balanced_acc']):.4f} "
            f"gate={bool(scored['gate_passed'])} "
            f"cols={len(scored['selected_cols'])} "
            f"reason={scored.get('reject_reason')}"
        )
        return objective_value

    sampler = optuna.samplers.TPESampler(seed=int(seed))
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=max(1, int(n_trials)), catch=(Exception,))
    _persist(True)
    payload = build_selection_payload(
        best,
        n_samples=n_samples,
        train_end=train_end,
        n_trials=int(n_trials),
        complete=True,
    )
    print(
        "best balanced_acc",
        f"{payload['best_balanced_acc']:.4f}",
        "cols",
        payload["n_features_selected"],
        "experiment",
        payload["experiment"],
    )
    return payload
