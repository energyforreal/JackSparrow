"""Training, walk-forward validation, and ONNX export for the fused MTF model.

Walk-forward and Optuna see only development/validation folds. The held-out
test split is scored once after freeze.
"""

from __future__ import annotations

import gc
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from feature_store.transformer_btcusd.contract import (
    FUSION_BUNDLE_DIR_NAME,
    FUSION_DIRECTION_CARDINALITY,
    FUSION_DIRECTION_NAMES,
    FUSION_GRADE_HIGH,
    FUSION_GRADE_LOW,
    FUSION_GRADE_MEDIUM,
    FUSION_HIGH_BALANCED_ACC,
    FUSION_HIGH_MAX_ECE,
    FUSION_HORIZON_KEYS,
    FUSION_DIR_COLS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_MEDIUM_BALANCED_ACC,
    FUSION_MIN_PROBABILITY,
    FUSION_MODEL_FAMILY,
    FUSION_ONNX_FILENAME,
    FUSION_TARGET_WINDOW_MINUTES,
    FUSION_WINDOW_LEN,
    FEATURE_CONTRACT_VERSION_V11,
    ONNX_OUTPUT_NAMES_V11,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    default_fusion_training_config,
    resolve_fusion_window_lens,
)
from feature_store.transformer_btcusd.mtf_features import (
    collect_training_windows,
    fusion_feature_cols,
    fusion_feature_fingerprint,
    precompute_featured_frames,
    save_featured_frames,
    try_load_featured_frames,
)
from feature_store.transformer_btcusd.mtf_frames import bar_close_time
from feature_store.transformer_btcusd.mtf_labels import (
    compute_fusion_horizon_labels,
    fusion_future_leak_cols,
    fusion_label_matrix,
    label_class_mix,
    trim_fusion_label_tail,
    valid_label_mask,
)
from scripts.colab.mtf_fusion_model import (
    MtfFusionDataset,
    MtfFusionTransformer,
    fusion_model_from_config,
    inverse_frequency_class_weights,
    train_mtf_fusion,
)


def set_research_seed(seed: int) -> None:
    """Seed numpy and torch for Colab reproducibility."""
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def walk_forward_slices(
    n: int,
    *,
    folds: int,
    embargo: int,
) -> List[Tuple[slice, slice]]:
    """Expanding train, trailing val; never includes a held-out final test."""
    folds = max(int(folds), 1)
    out: List[Tuple[slice, slice]] = []
    for i in range(folds):
        train_end = max(2, int(n * (0.50 + 0.10 * i)))
        val_end = min(n, train_end + max(int(n * 0.12), 8))
        gap = min(max(int(embargo), 0), max(0, val_end - train_end - 1))
        val_start = train_end + gap
        if val_start >= val_end:
            continue
        out.append((slice(0, train_end), slice(val_start, val_end)))
    return out


def split_purged_windows(
    arrays: Mapping[str, np.ndarray],
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, Dict[str, np.ndarray]]:
    """Time-ordered train/val/test split with embargo gaps between segments."""
    if not arrays:
        raise ValueError("split_purged_windows requires at least one array")
    lengths = {k: len(v) for k, v in arrays.items()}
    n = next(iter(lengths.values()))
    if any(length != n for length in lengths.values()):
        raise ValueError(f"Array length mismatch: {lengths}")
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    embargo = int(embargo_bars)
    slices = {
        "train": slice(0, train_end),
        "val": slice(train_end + embargo, val_end),
        "test": slice(val_end + embargo, n),
    }
    splits = {
        split: {k: v[sl] for k, v in arrays.items()} for split, sl in slices.items()
    }
    first_key = next(iter(arrays))
    if len(splits["train"][first_key]) == 0 or len(splits["val"][first_key]) == 0:
        raise ValueError(
            f"Insufficient windows after split: train={len(splits['train'][first_key])}, "
            f"val={len(splits['val'][first_key])}, test={len(splits['test'][first_key])}"
        )
    return splits


def development_prefix(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    train_frac: float,
    val_frac: float,
) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    """Contiguous samples from t=0 through val; test tail excluded.

    Includes the train/val embargo rows so walk-forward stays on calendar time
    instead of concatenating purged splits (which drops the gap).
    """
    if not windows:
        raise ValueError("development_prefix requires windows")
    n = int(len(labels))
    lengths = {k: len(v) for k, v in windows.items()}
    if any(length != n for length in lengths.values()):
        raise ValueError(f"Array length mismatch: {lengths} vs labels={n}")
    train_end = int(n * float(train_frac))
    val_end = train_end + int(n * float(val_frac))
    if val_end <= 0 or val_end > n:
        raise ValueError(f"Invalid development end {val_end} for n={n}")
    sl = slice(0, val_end)
    return {str(k): v[sl] for k, v in windows.items()}, labels[sl]


def leakage_audit(feature_cols: Sequence[str]) -> None:
    """Raise if any target or future column leaked into the input feature list.

    Causal structure fields such as ``last_swing_dir`` are valid inputs. Only
    horizon targets, resampled HTF columns, and explicit future_* names are banned.
    """
    banned = set(fusion_future_leak_cols())
    leaked: List[str] = []
    for col in feature_cols:
        name = str(col)
        if (
            name in banned
            or name.startswith("htf_")
            or name.startswith("future_")
            or name.startswith("horizon_")
        ):
            leaked.append(name)
    if leaked:
        raise RuntimeError(f"Future/HTF/target columns in inputs: {leaked}")
    print("Leakage audit passed: no horizon dirs, no resampled HTF structure in X.")


def confusion_counts(pred: np.ndarray, true: np.ndarray, n_classes: int) -> np.ndarray:
    """Integer confusion matrix (rows=true, cols=pred)."""
    mat = np.zeros((n_classes, n_classes), dtype=np.int64)
    pred_i = np.asarray(pred, dtype=np.int64)
    true_i = np.asarray(true, dtype=np.int64)
    for t, p in zip(true_i, pred_i):
        if 0 <= t < n_classes and 0 <= p < n_classes:
            mat[t, p] += 1
    return mat


def feature_finite_report(
    values: np.ndarray,
    feature_cols: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Print finite-rate before training. Does not mutate caller arrays."""
    arr = np.asarray(values, dtype=np.float64)
    finite_rate = float(np.isfinite(arr).mean()) if arr.size else 1.0
    n_inf = int(np.isinf(arr).sum())
    n_nan = int(np.isnan(arr).sum())
    print(f"feature finite_rate={finite_rate:.4f} inf={n_inf} nan={n_nan}")
    if feature_cols is not None:
        print(f"n_features={len(feature_cols)}")
    return {"finite_rate": finite_rate, "inf": n_inf, "nan": n_nan}


def fusion_feature_groups(feature_cols: Sequence[str]) -> Dict[str, List[str]]:
    """Partition fusion columns into candle / chart / trend / vol / other.

    ``htf_resample`` must stay empty — resampled HTF columns are leakage.
    """
    names = [str(c) for c in feature_cols]
    assigned: set[str] = set()
    groups: Dict[str, List[str]] = {
        "candle": [],
        "chart": [],
        "trend": [],
        "vol": [],
        "other": [],
        "htf_resample": [],
    }
    trend_exact = {"macd_hist", "adx_14", "rsi_14"}
    for col in names:
        if col.startswith("htf_"):
            groups["htf_resample"].append(col)
            assigned.add(col)
            continue
        if "cdl_" in col or "body" in col or "wick" in col:
            groups["candle"].append(col)
            assigned.add(col)
            continue
        if col.startswith(("sr_", "tl_", "chp_")):
            groups["chart"].append(col)
            assigned.add(col)
            continue
        if "ema" in col or col in trend_exact:
            groups["trend"].append(col)
            assigned.add(col)
            continue
        if "atr" in col or col.startswith("rv_"):
            groups["vol"].append(col)
            assigned.add(col)
            continue
    groups["other"] = [c for c in names if c not in assigned]
    if groups["htf_resample"]:
        raise RuntimeError(
            f"htf_ columns must not appear in fusion inputs: {groups['htf_resample']}"
        )
    return groups


class StackedHorizonScorer(nn.Module):
    """Map (B, n_tf, T, F) stacked windows to BULL−BEAR logit for one head."""

    def __init__(self, model: MtfFusionTransformer, horizon_index: int) -> None:
        super().__init__()
        self.inner = model
        self.horizon_index = int(horizon_index)

    def forward(self, stacked: torch.Tensor) -> torch.Tensor:
        n_tfs = int(stacked.size(1))
        windows = [stacked[:, i, :, :].contiguous() for i in range(n_tfs)]
        outputs = self.inner(*windows)
        logits = outputs[self.horizon_index]
        # (B, 1) so GradientExplainer can index outputs[:, idx].
        return (logits[:, 1] - logits[:, 0]).reshape(-1, 1)


def _windows_to_stacked(windows: Mapping[str, np.ndarray]) -> np.ndarray:
    mats: List[np.ndarray] = []
    n: Optional[int] = None
    for res in FUSION_INPUT_RESOLUTIONS:
        arr = np.asarray(windows[res], dtype=np.float32)
        if n is None:
            n = int(arr.shape[0])
        elif int(arr.shape[0]) != n:
            raise ValueError(f"val window length mismatch for {res}")
        mats.append(arr)
    return np.stack(mats, axis=1)


def _print_shap_tables(
    groups: Mapping[str, List[str]],
    per_feature: Mapping[str, float],
    group_totals: Mapping[str, float],
    *,
    horizon_key: str,
    top_k: int = 20,
) -> None:
    total = float(sum(group_totals.values())) or 1.0
    print(f"Gradient SHAP groups ({horizon_key}, mean |SHAP|):")
    for name in ("candle", "chart", "trend", "vol", "other"):
        val = float(group_totals.get(name) or 0.0)
        share = val / total
        n_cols = len(groups.get(name) or [])
        print(f"  {name}: {val:.6f}  share={share:.3f}  n={n_cols}")
    ranked = sorted(per_feature.items(), key=lambda kv: kv[1], reverse=True)
    print(f"Top {min(int(top_k), len(ranked))} features ({horizon_key}):")
    for name, val in ranked[: int(top_k)]:
        print(f"  {name}: {float(val):.6f}")


def _shap_values_to_array(raw: Any, expected_ndim: int = 4) -> np.ndarray:
    """Coerce GradientExplainer output to (B, n_tf, T, F).

    Some SHAP builds add a singleton output axis (rank 5) when the scorer
    returns (B, 1) instead of (B,). Squeeze size-1 axes until rank matches.
    """
    if isinstance(raw, (list, tuple)):
        raw = raw[0]
    if torch.is_tensor(raw):
        raw = raw.detach().cpu().tolist()
    arr = np.asarray(raw, dtype=np.float64)
    while arr.ndim > expected_ndim:
        squeezed = False
        for axis in range(arr.ndim):
            if int(arr.shape[axis]) == 1:
                arr = np.squeeze(arr, axis=axis)
                squeezed = True
                break
        if not squeezed:
            break
    if arr.ndim != expected_ndim:
        raise ValueError(f"SHAP values rank {arr.ndim} != {expected_ndim}")
    return arr


def run_gradient_shap(
    feature_cols: Sequence[str],
    *,
    model: torch.nn.Module,
    val_windows: Mapping[str, np.ndarray],
    device: torch.device,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Gradient SHAP on a validation subsample. Never reads the test split."""
    cfg = dict(config or {})
    cols = [str(c) for c in feature_cols]
    groups = fusion_feature_groups(cols)
    try:
        import shap  # type: ignore[import-not-found]
    except ImportError:
        print("SHAP skipped: package 'shap' is not installed.")
        return {
            "ok": False,
            "reason": "shap not installed",
            "groups": {k: list(v) for k, v in groups.items() if k != "htf_resample"},
            "horizons": {},
        }

    stacked = _windows_to_stacked(val_windows)
    n = int(stacked.shape[0])
    if n < 2:
        print("SHAP skipped: need at least 2 validation windows.")
        return {
            "ok": False,
            "reason": "insufficient val windows",
            "groups": {k: list(v) for k, v in groups.items() if k != "htf_resample"},
            "horizons": {},
        }

    seed = int(cfg.get("seed") or 42)
    rng = np.random.default_rng(seed)
    n_bg = max(2, min(int(cfg.get("shap_background") or 32), n))
    n_ex = max(2, min(int(cfg.get("shap_explain_n") or 64), n))
    bg_idx = rng.choice(n, size=n_bg, replace=False)
    ex_idx = rng.choice(n, size=n_ex, replace=False)

    model.eval()
    n_horizons = int(getattr(model, "n_horizons", len(FUSION_HORIZON_KEYS)))
    horizon_keys = list(FUSION_HORIZON_KEYS)[:n_horizons]
    device_t = torch.device(device)
    horizons_out: Dict[str, Any] = {}

    explain_sizes = [n_ex]
    halved = n_ex
    while halved > 8:
        halved = max(8, halved // 2)
        if halved not in explain_sizes:
            explain_sizes.append(halved)

    for h_idx, key in enumerate(horizon_keys):
        scorer = StackedHorizonScorer(model, h_idx).to(device_t)
        scorer.eval()
        shap_arr: Optional[np.ndarray] = None
        used_ex = n_ex
        used_bg = n_bg
        last_err = ""
        for try_ex in explain_sizes:
            try_bg = min(used_bg, try_ex, n_bg)
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                bg = torch.as_tensor(
                    stacked[bg_idx[:try_bg]], dtype=torch.float32, device=device_t
                )
                ex = torch.as_tensor(
                    stacked[ex_idx[:try_ex]], dtype=torch.float32, device=device_t
                )
                explainer = shap.GradientExplainer(scorer, bg)
                raw = explainer.shap_values(ex)
                shap_arr = _shap_values_to_array(raw)
                used_ex = try_ex
                used_bg = try_bg
                last_err = ""
                break
            except (RuntimeError, MemoryError, ValueError, IndexError) as exc:
                last_err = str(exc)
                print(
                    f"SHAP {key} failed at explain_n={try_ex} "
                    f"({type(exc).__name__}); retrying smaller subsample."
                )
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        if shap_arr is None:
            print(f"SHAP skipped for {key}: {last_err}")
            horizons_out[key] = {"ok": False, "reason": last_err}
            continue
        per_feat_arr = np.mean(np.abs(shap_arr), axis=(0, 1, 2))
        if per_feat_arr.shape[0] != len(cols):
            print(
                f"SHAP {key}: feature dim {per_feat_arr.shape[0]} != {len(cols)}; skip."
            )
            horizons_out[key] = {"ok": False, "reason": "feature dim mismatch"}
            continue
        per_feature = {
            cols[i]: float(per_feat_arr[i]) for i in range(len(cols))
        }
        group_totals = {
            gname: float(sum(per_feature.get(c, 0.0) for c in gcols))
            for gname, gcols in groups.items()
            if gname != "htf_resample"
        }
        _print_shap_tables(
            groups, per_feature, group_totals, horizon_key=key
        )
        ranked = sorted(per_feature.items(), key=lambda kv: kv[1], reverse=True)
        horizons_out[key] = {
            "ok": True,
            "background_n": int(used_bg),
            "explain_n": int(used_ex),
            "features": per_feature,
            "groups": group_totals,
            "top_features": [
                {"name": n, "mean_abs_shap": float(v)} for n, v in ranked[:20]
            ],
        }

    any_ok = any(bool(row.get("ok")) for row in horizons_out.values())
    report = {
        "ok": bool(any_ok),
        "reason": "gradient shap on val subsample" if any_ok else "all heads failed",
        "groups": {k: list(v) for k, v in groups.items() if k != "htf_resample"},
        "horizons": horizons_out,
        "split": "val",
    }
    return report


def shap_grouped_stub(
    feature_cols: Sequence[str],
    *,
    enabled: bool,
    model: Optional[torch.nn.Module] = None,
    val_windows: Optional[Mapping[str, np.ndarray]] = None,
    device: Optional[torch.device] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Grouped SHAP entry point. Computes Gradient SHAP only when enabled."""
    groups = fusion_feature_groups(feature_cols)
    group_lists = {k: list(v) for k, v in groups.items() if k != "htf_resample"}
    if not enabled:
        print("SHAP skipped (CONFIG run_shap=False). Fusion feature groups:")
        for name, cols in group_lists.items():
            print(f"  {name}: {len(cols)} cols")
        return {
            "ok": False,
            "enabled": False,
            "reason": "run_shap=False",
            "groups": group_lists,
            "horizons": {},
        }
    if model is None or val_windows is None:
        print("SHAP enabled but model/val_windows missing; skip compute.")
        return {
            "ok": False,
            "enabled": True,
            "reason": "model or val_windows missing",
            "groups": group_lists,
            "horizons": {},
        }
    dev = device if device is not None else torch.device("cpu")
    print("Gradient SHAP on validation subsample (test split unused).")
    try:
        report = run_gradient_shap(
            feature_cols,
            model=model,
            val_windows=val_windows,
            device=dev,
            config=config,
        )
    except Exception as exc:
        print(
            f"SHAP failed (export continues): {type(exc).__name__}: {exc}"
        )
        return {
            "ok": False,
            "enabled": True,
            "reason": f"{type(exc).__name__}: {exc}",
            "groups": group_lists,
            "horizons": {},
        }
    report["enabled"] = True
    return report


def _fusion_train_extra(config: Mapping[str, Any]) -> Dict[str, Any]:
    raw_w = config.get("horizon_loss_weights") or [1.0, 0.8, 0.4]
    return {
        "label_smoothing": float(config.get("label_smoothing") or 0.0),
        "horizon_weights": [float(x) for x in raw_w],
        "lr_schedule": str(config.get("lr_schedule") or "cosine"),
        "amp": bool(config.get("amp", True)),
    }


OPTUNA_BEST_FILENAME = "optuna_best.json"
FUSION_WINDOW_MANIFEST = "manifest.json"
FUSION_LABELS_FILENAME = "labels.npy"
FUSION_TIMES_FILENAME = "decision_times.parquet"


def window_cache_manifest(
    *,
    window_lens: Mapping[str, int],
    stride: int,
    n_samples: Optional[int] = None,
    target_window_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Identity for cached TF windows + labels."""
    cols = list(fusion_feature_cols())
    lens = {res: int(window_lens[res]) for res in FUSION_INPUT_RESOLUTIONS}
    payload: Dict[str, Any] = {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "window_lens": lens,
        "window_len": int(lens["5m"]),
        "target_window_minutes": int(
            target_window_minutes
            if target_window_minutes is not None
            else FUSION_TARGET_WINDOW_MINUTES
        ),
        "stride": int(stride),
        "n_features": len(cols),
        "feature_fingerprint": fusion_feature_fingerprint(),
    }
    if n_samples is not None:
        payload["n_samples"] = int(n_samples)
    return payload


def try_load_fusion_dataset_cache(
    cache_dir: Path,
    *,
    stride: int,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    target_window_minutes: Optional[int] = None,
) -> Optional[Tuple[Dict[str, np.ndarray], np.ndarray, pd.Series]]:
    """Load memmapped windows + labels when manifest matches."""
    root = Path(cache_dir)
    man_path = root / FUSION_WINDOW_MANIFEST
    labels_path = root / FUSION_LABELS_FILENAME
    times_path = root / FUSION_TIMES_FILENAME
    if not man_path.is_file() or not labels_path.is_file() or not times_path.is_file():
        return None
    try:
        stored = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    lens = resolve_fusion_window_lens(window_lens, window_len)
    expected = window_cache_manifest(
        window_lens=lens,
        stride=stride,
        target_window_minutes=target_window_minutes,
    )
    for key, value in expected.items():
        if stored.get(key) != value:
            return None
    n_samples = int(stored.get("n_samples") or 0)
    if n_samples <= 0:
        return None
    windows: Dict[str, np.ndarray] = {}
    n_feat = int(expected["n_features"])
    for res in FUSION_INPUT_RESOLUTIONS:
        path = root / f"windows_{res}.npy"
        if not path.is_file():
            return None
        arr = np.load(str(path), mmap_mode="r")
        width = int(lens[res])
        if tuple(arr.shape) != (n_samples, width, n_feat):
            return None
        windows[str(res)] = arr
    labels = np.load(str(labels_path))
    if len(labels) != n_samples:
        return None
    times_df = pd.read_parquet(times_path)
    if "time" not in times_df.columns or len(times_df) != n_samples:
        return None
    decision_times = pd.to_datetime(times_df["time"], utc=True)
    return windows, labels, decision_times


def save_fusion_dataset_cache(
    cache_dir: Path,
    *,
    labels: np.ndarray,
    decision_times: pd.Series,
    stride: int,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    target_window_minutes: Optional[int] = None,
) -> None:
    """Write labels, decision times, and window manifest (memmaps already on disk)."""
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    np.save(root / FUSION_LABELS_FILENAME, np.asarray(labels))
    pd.DataFrame({"time": pd.to_datetime(decision_times, utc=True)}).to_parquet(
        root / FUSION_TIMES_FILENAME, index=False
    )
    lens = resolve_fusion_window_lens(window_lens, window_len)
    manifest = window_cache_manifest(
        window_lens=lens,
        stride=stride,
        n_samples=len(labels),
        target_window_minutes=target_window_minutes,
    )
    (root / FUSION_WINDOW_MANIFEST).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _optuna_cache_path(cache_dir: Optional[Path]) -> Optional[Path]:
    if cache_dir is None:
        return None
    return Path(cache_dir) / OPTUNA_BEST_FILENAME


def optuna_cache_identity() -> Dict[str, Any]:
    """Contract fingerprint so stale Optuna HPs are not reused after a v11 change."""
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "feature_fingerprint": fusion_feature_fingerprint(),
        "horizon_keys": list(FUSION_HORIZON_KEYS),
        "n_classes": int(FUSION_DIRECTION_CARDINALITY),
    }


def _optuna_cache_matches(payload: Mapping[str, Any]) -> bool:
    stored = payload.get("cache_identity")
    if not isinstance(stored, dict):
        return False
    expected = optuna_cache_identity()
    return all(stored.get(key) == value for key, value in expected.items())


def _apply_optuna_payload(cfg: Dict[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    params = dict(payload.get("params") or payload)
    cfg["lr"] = float(params["lr"])
    cfg["weight_decay"] = float(params["weight_decay"])
    cfg["dropout"] = float(params["dropout"])
    identity = dict(payload.get("cache_identity") or optuna_cache_identity())
    cfg["optuna_best"] = {
        "params": {
            "lr": cfg["lr"],
            "weight_decay": cfg["weight_decay"],
            "dropout": cfg["dropout"],
        },
        "best_val_loss": float(payload.get("best_val_loss") or payload.get("value") or 0.0),
        "n_trials": int(payload.get("n_trials") or 0),
        "cache_identity": identity,
    }
    return cfg


def optuna_search(
    config: Mapping[str, Any],
    *,
    n_features: int,
    train_loader: DataLoader,
    val_loader: DataLoader,
    device: torch.device,
    class_weights: Optional[torch.Tensor] = None,
    train_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    model_factory: Optional[Callable[..., MtfFusionTransformer]] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Search dropout / weight_decay / lr on val CE. Never reads test."""
    cfg = dict(config)
    if not cfg.get("run_optuna"):
        print(
            "Optuna skipped (CONFIG run_optuna=False). "
            "Search space: lr, weight_decay, dropout."
        )
        return cfg
    cache_root: Optional[Path] = Path(cache_dir) if cache_dir is not None else None
    if cache_root is None and cfg.get("cache_dir"):
        cache_root = Path(str(cfg["cache_dir"]))
    best_path = _optuna_cache_path(cache_root)
    if best_path is not None and best_path.is_file() and not cfg.get("optuna_refresh"):
        try:
            payload = json.loads(best_path.read_text(encoding="utf-8"))
            if not _optuna_cache_matches(payload):
                print(f"Optuna cache STALE {best_path}; running search.")
            else:
                cfg = _apply_optuna_payload(cfg, payload)
                print(f"Optuna cache HIT {best_path}")
                print("Optuna best", json.dumps(cfg["optuna_best"], indent=2, default=str))
                return cfg
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"Optuna cache unreadable ({exc}); running search.")
    try:
        import optuna
    except ImportError:
        print("Optuna not installed; leaving CONFIG unchanged.")
        return cfg

    trainer = train_fn or train_mtf_fusion
    factory = model_factory or fusion_model_from_config
    extra = _fusion_train_extra(cfg)
    n_trials = max(1, int(cfg.get("optuna_trials") or 3))
    trial_epochs = max(1, int(cfg.get("optuna_trial_epochs") or 4))
    patience = max(2, int(cfg.get("early_stop_patience") or 3))
    failed_value = 1.0e9

    def objective(trial: Any) -> float:
        model: Optional[MtfFusionTransformer] = None
        try:
            trial_cfg = dict(cfg)
            trial_cfg["lr"] = float(trial.suggest_float("lr", 3e-5, 3e-4, log=True))
            trial_cfg["weight_decay"] = float(
                trial.suggest_float("weight_decay", 1e-4, 3e-3, log=True)
            )
            trial_cfg["dropout"] = float(trial.suggest_float("dropout", 0.20, 0.40))
            model = factory(n_features, trial_cfg).to(device)
            hist = trainer(
                model,
                train_loader,
                val_loader,
                device=device,
                epochs=trial_epochs,
                lr=float(trial_cfg["lr"]),
                weight_decay=float(trial_cfg["weight_decay"]),
                patience=patience,
                class_weights=class_weights,
                **extra,
            )
            if not hist.get("ok"):
                print(f"Optuna trial {trial.number}: non-finite train, skip")
                return failed_value
            value = float(hist["best_val_loss"])
            if not math.isfinite(value):
                return failed_value
            return value
        except Exception as exc:
            print(
                f"Optuna trial {getattr(trial, 'number', '?')} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return failed_value
        finally:
            if model is not None:
                del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    amp_on = bool(extra.get("amp")) and device.type == "cuda"
    print(
        f"Optuna: {n_trials} trials on val CE (test unused, "
        f"AMP {'on' if amp_on else 'off'})."
    )
    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, catch=())
    finite = [
        t
        for t in study.trials
        if t.value is not None
        and math.isfinite(float(t.value))
        and float(t.value) < failed_value / 2.0
    ]
    if not finite:
        print(
            "Optuna: no finite trial; keeping CONFIG lr / dropout / weight_decay."
        )
        return cfg
    best_trial = min(finite, key=lambda t: float(t.value))
    best = dict(best_trial.params)
    cfg["lr"] = float(best["lr"])
    cfg["weight_decay"] = float(best["weight_decay"])
    cfg["dropout"] = float(best["dropout"])
    cfg["optuna_best"] = {
        "params": best,
        "best_val_loss": float(best_trial.value),
        "n_trials": n_trials,
        "cache_identity": optuna_cache_identity(),
    }
    if best_path is not None:
        best_path.parent.mkdir(parents=True, exist_ok=True)
        best_path.write_text(
            json.dumps(cfg["optuna_best"], indent=2, default=str), encoding="utf-8"
        )
        print(f"Wrote Optuna cache {best_path}")
    print("Optuna best", json.dumps(cfg["optuna_best"], indent=2, default=str))
    return cfg


def optuna_search_stub(
    config: Mapping[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Backward-compatible alias. Requires the same kwargs as optuna_search."""
    if not kwargs:
        print("optuna_search_stub needs loaders; leaving CONFIG unchanged.")
        return dict(config)
    return optuna_search(config, **kwargs)


def _decision_times(featured_5m: pd.DataFrame, window_len: int) -> pd.Series:
    times = pd.to_datetime(featured_5m["time"], utc=True)
    return times.iloc[int(window_len) :]


def build_dataset_from_ohlcv(
    frames: Dict[str, pd.DataFrame],
    *,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    stride: int = 4,
    memmap_dir: Optional[Path] = None,
) -> Tuple[Dict[str, np.ndarray], np.ndarray, pd.Series]:
    """Native TF windows + 2-class train labels aligned on the 5m decision clock."""
    lens = resolve_fusion_window_lens(window_lens, window_len)
    warmup = int(lens["5m"])
    cache_root = Path(memmap_dir) if memmap_dir is not None else None
    if cache_root is not None:
        cached = try_load_fusion_dataset_cache(
            cache_root, window_lens=lens, stride=stride
        )
        if cached is not None:
            print(f"cache HIT {cache_root}")
            return cached
        print(f"cache MISS {cache_root}")

    labeled = compute_fusion_horizon_labels(frames["5m"])
    labeled = trim_fusion_label_tail(labeled)
    featured: Optional[Dict[str, pd.DataFrame]] = None
    if cache_root is not None:
        featured = try_load_featured_frames(cache_root)
        if featured is not None:
            print(f"featured cache HIT {cache_root}")
    if featured is None:
        featured = precompute_featured_frames(frames)
        if cache_root is not None:
            save_featured_frames(cache_root, featured)
            print(f"wrote featured cache {cache_root}")
    feat5_time = featured["5m"][["time"]].copy()
    feat5_time["time"] = pd.to_datetime(feat5_time["time"], utc=True)
    labeled["time"] = pd.to_datetime(labeled["time"], utc=True)
    dir_cols = [c for c in FUSION_DIR_COLS if c in labeled.columns]
    merged = feat5_time.merge(labeled[["time", *dir_cols]], on="time", how="inner")
    merged = merged.iloc[int(warmup) :].reset_index(drop=True)
    if stride > 1:
        merged = merged.iloc[:: int(stride)].reset_index(drop=True)
    y = fusion_label_matrix(merged)
    mask = valid_label_mask(y)
    merged = merged.loc[mask].reset_index(drop=True)
    y = y[mask]
    decision_close = bar_close_time(merged["time"], 5)
    windows = collect_training_windows(
        featured,
        list(decision_close),
        window_lens=lens,
        zscore=True,
        memmap_dir=cache_root,
    )
    decision_times = merged["time"].copy()
    if cache_root is not None:
        save_fusion_dataset_cache(
            cache_root,
            labels=y,
            decision_times=decision_times,
            window_lens=lens,
            stride=stride,
        )
        print(f"wrote window cache {cache_root}")
    del featured, labeled, merged, feat5_time
    gc.collect()
    return windows, y, decision_times


def softmax_np(logits: np.ndarray) -> np.ndarray:
    z = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(z)
    return exp / np.clip(exp.sum(axis=-1, keepdims=True), 1e-12, None)


def balanced_accuracy(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    scores: List[float] = []
    for c in range(int(n_classes)):
        mask = y_true == c
        if not np.any(mask):
            continue
        scores.append(float(np.mean(y_pred[mask] == c)))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def macro_f1(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    f1s: List[float] = []
    for c in range(int(n_classes)):
        tp = float(np.sum((y_true == c) & (y_pred == c)))
        fp = float(np.sum((y_true != c) & (y_pred == c)))
        fn = float(np.sum((y_true == c) & (y_pred != c)))
        prec = tp / (tp + fp + 1e-9)
        rec = tp / (tp + fn + 1e-9)
        f1s.append(2 * prec * rec / (prec + rec + 1e-9))
    return float(np.mean(f1s)) if f1s else 0.0


def expected_calibration_error(
    probs: np.ndarray,
    y_true: np.ndarray,
    n_bins: int = 10,
) -> float:
    """ECE on max-class confidence vs correctness."""
    conf = probs.max(axis=-1)
    pred = probs.argmax(axis=-1)
    correct = (pred == y_true).astype(np.float64)
    edges = np.linspace(0.0, 1.0, int(n_bins) + 1)
    ece = 0.0
    n = max(len(y_true), 1)
    for i in range(int(n_bins)):
        lo, hi = edges[i], edges[i + 1]
        if i == n_bins - 1:
            sel = (conf >= lo) & (conf <= hi)
        else:
            sel = (conf >= lo) & (conf < hi)
        if not np.any(sel):
            continue
        acc = float(correct[sel].mean())
        avg_conf = float(conf[sel].mean())
        ece += (float(sel.sum()) / n) * abs(acc - avg_conf)
    return float(ece)


def brier_score(
    probs: np.ndarray,
    y_true: np.ndarray,
    n_classes: int = FUSION_DIRECTION_CARDINALITY,
) -> float:
    onehot = np.eye(int(n_classes), dtype=np.float64)[np.clip(y_true, 0, n_classes - 1)]
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=-1)))


def paper_pnl(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Secondary metric only. +1 correct 2-class direction, -1 wrong. Skip < 0."""
    valid = (y_true >= 0) & (y_pred >= 0)
    if not np.any(valid):
        return 0.0
    wins = y_pred[valid] == y_true[valid]
    return float(np.mean(np.where(wins, 1.0, -1.0)))


def fit_temperature(logits: np.ndarray, y_true: np.ndarray) -> float:
    """One-parameter temperature on validation logits (NLL). Never uses test."""
    valid = y_true >= 0
    if not np.any(valid):
        return 1.0
    z = torch.tensor(logits[valid], dtype=torch.float32)
    y = torch.tensor(y_true[valid], dtype=torch.long)
    log_t = torch.nn.Parameter(torch.zeros(()))
    opt = torch.optim.LBFGS([log_t], lr=0.25, max_iter=50)

    def _closure() -> torch.Tensor:
        opt.zero_grad()
        temp = torch.exp(log_t).clamp(0.05, 10.0)
        loss = torch.nn.functional.cross_entropy(z / temp, y)
        loss.backward()
        return loss

    opt.step(_closure)
    return float(torch.exp(log_t).clamp(0.05, 10.0).detach().item())


def apply_temperature(logits: np.ndarray, temperature: float) -> np.ndarray:
    t = max(float(temperature), 1e-6)
    return softmax_np(logits / t)


def grade_horizon(
    *,
    balanced_acc: float,
    ece: float,
    fold_std: float = 0.0,
    high_acc: float = FUSION_HIGH_BALANCED_ACC,
    high_ece: float = FUSION_HIGH_MAX_ECE,
    medium_acc: float = FUSION_MEDIUM_BALANCED_ACC,
) -> str:
    """Map OOS metrics to HIGH / MEDIUM / LOW. Unstable folds cannot be HIGH."""
    if float(fold_std) > 0.08:
        if float(balanced_acc) >= float(medium_acc):
            return FUSION_GRADE_MEDIUM
        return FUSION_GRADE_LOW
    if float(balanced_acc) >= float(high_acc) and float(ece) <= float(high_ece):
        return FUSION_GRADE_HIGH
    if float(balanced_acc) >= float(medium_acc):
        return FUSION_GRADE_MEDIUM
    return FUSION_GRADE_LOW


def horizon_metrics(
    logits: np.ndarray,
    y_true: np.ndarray,
    *,
    temperature: float = 1.0,
) -> Dict[str, float]:
    valid = y_true >= 0
    if not np.any(valid):
        return {
            "balanced_acc": 0.0,
            "macro_f1": 0.0,
            "ece": 1.0,
            "brier": 1.0,
            "paper_pnl": 0.0,
            "n": 0.0,
        }
    probs = apply_temperature(logits[valid], temperature)
    pred = probs.argmax(axis=-1)
    yt = y_true[valid]
    return {
        "balanced_acc": balanced_accuracy(yt, pred, FUSION_DIRECTION_CARDINALITY),
        "macro_f1": macro_f1(yt, pred, FUSION_DIRECTION_CARDINALITY),
        "ece": expected_calibration_error(probs, yt),
        "brier": brier_score(probs, yt, FUSION_DIRECTION_CARDINALITY),
        "paper_pnl": paper_pnl(yt, pred),
        "n": float(len(yt)),
    }


@torch.no_grad()
def predict_logits(
    model: MtfFusionTransformer,
    loader: DataLoader,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (n, n_horizons, 2) logits and (n, n_horizons) labels."""
    model.eval()
    logit_chunks: List[np.ndarray] = []
    label_chunks: List[np.ndarray] = []
    for batch in loader:
        batch_d = tuple(
            t.to(device, non_blocking=device.type == "cuda") for t in batch
        )
        outs = model(*batch_d[:-1])
        dir_logits = [o.cpu().numpy() for o in outs[:N_HORIZONS_SAFE]]
        stacked = np.stack(dir_logits, axis=1)
        logit_chunks.append(stacked)
        label_chunks.append(batch_d[-1].cpu().numpy())
    return np.concatenate(logit_chunks, axis=0), np.concatenate(label_chunks, axis=0)


N_HORIZONS_SAFE = len(FUSION_HORIZON_KEYS)


def slice_windows(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    sl: slice,
) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
    return {k: v[sl] for k, v in windows.items()}, labels[sl]


_MAX_RAM_WINDOW_BYTES = 2 * 1024 * 1024 * 1024


def _is_memmap_array(arr: Any) -> bool:
    return isinstance(arr, np.memmap)


def _windows_to_cpu_tensors(
    windows: Mapping[str, Any],
    *,
    pin: bool,
) -> Dict[str, torch.Tensor]:
    """Host float32 tensors. Pin only when the DataLoader has no workers."""
    out: Dict[str, torch.Tensor] = {}
    for key, arr in windows.items():
        if isinstance(arr, torch.Tensor):
            tensor = arr.detach().to(dtype=torch.float32).contiguous().cpu()
        else:
            copied = np.ascontiguousarray(np.asarray(arr), dtype=np.float32)
            tensor = torch.from_numpy(copied)
        if pin and torch.cuda.is_available():
            tensor = tensor.pin_memory()
        out[str(key)] = tensor
    return out


def materialize_windows_if_fits(
    windows: Mapping[str, np.ndarray],
    *,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Copy TF windows to C-contiguous writeable RAM. Keep memmaps on OOM.

    Colab's OOM killer often SIGKILLs before Python can raise MemoryError, so
    copies larger than 2 GiB are skipped.
    """
    if not enabled:
        return {k: v for k, v in windows.items()}
    nbytes = 0
    for arr in windows.values():
        nbytes += int(getattr(arr, "nbytes", 0) or 0)
    if nbytes > _MAX_RAM_WINDOW_BYTES:
        print(
            f"windows_in_ram: skip copy ({nbytes / 1e9:.1f} GB > "
            f"{_MAX_RAM_WINDOW_BYTES / 1e9:.0f} GB cap)"
        )
        return {k: v for k, v in windows.items()}
    out: Dict[str, Any] = {}
    try:
        for key, arr in windows.items():
            if isinstance(arr, torch.Tensor):
                out[str(key)] = arr.detach().to(dtype=torch.float32).contiguous()
                continue
            copied = np.asarray(arr).astype(np.float32, copy=True, order="C")
            out[str(key)] = copied
    except MemoryError:
        print("windows_in_ram: MemoryError, keeping original arrays")
        return {k: v for k, v in windows.items()}
    return out


def make_loader(
    windows: Mapping[str, Any],
    labels: np.ndarray,
    *,
    batch_size: int,
    shuffle: bool,
    pin_memory: bool = False,
    num_workers: int = 0,
    windows_in_ram: bool = False,
    prefetch_factor: int = 4,
) -> DataLoader:
    mats = materialize_windows_if_fits(windows, enabled=windows_in_ram)
    workers = max(0, int(num_workers))
    pin = bool(pin_memory)
    in_ram = mats and not any(_is_memmap_array(v) for v in mats.values())
    if in_ram:
        try:
            mats = _windows_to_cpu_tensors(mats, pin=pin and workers == 0)
        except (RuntimeError, MemoryError, ValueError) as exc:
            print(f"windows_to_tensor skipped ({type(exc).__name__}: {exc})")
    ds = MtfFusionDataset(mats, labels)
    kwargs: Dict[str, Any] = {
        "batch_size": int(batch_size),
        "shuffle": shuffle,
        "pin_memory": pin,
    }
    if workers > 0:
        kwargs["num_workers"] = workers
        kwargs["persistent_workers"] = True
        kwargs["prefetch_factor"] = max(2, int(prefetch_factor))
    return DataLoader(ds, **kwargs)


def loader_runtime_kwargs(
    config: Mapping[str, Any],
    device: torch.device,
) -> Dict[str, Any]:
    """CUDA: pin batches, 2 workers, prefetch. CPU: single-process loader."""
    cuda = device.type == "cuda"
    pin = bool(config.get("pin_memory", True)) and cuda
    if "dataloader_workers" in config:
        workers = int(config.get("dataloader_workers") or 0)
    else:
        workers = 2 if cuda else 0
    if not cuda:
        workers = 0
    return {
        "pin_memory": pin,
        "num_workers": max(0, workers),
        "windows_in_ram": bool(config.get("windows_in_ram", True)),
        "prefetch_factor": int(config.get("prefetch_factor") or 4),
    }


def _loader_runtime_kwargs(
    config: Mapping[str, Any],
    device: torch.device,
) -> Dict[str, Any]:
    """Alias kept for the generated Colab notebook."""
    return loader_runtime_kwargs(config, device)


def run_walk_forward(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    n_features: int,
    config: Mapping[str, Any],
    device: torch.device,
) -> Dict[str, Any]:
    """Expanding-window folds on the development set only."""
    n = len(labels)
    folds = int(
        config.get("walk_forward_folds") or config.get("walk_forward_folds") or 3
    )
    embargo = int(
        config.get("walk_forward_embargo") or config.get("walk_forward_embargo") or 24
    )
    fold_rows: List[Dict[str, Any]] = []
    per_h_acc: Dict[str, List[float]] = {k: [] for k in FUSION_HORIZON_KEYS}
    for train_sl, val_sl in walk_forward_slices(n, folds=folds, embargo=embargo):
        tw, ty = slice_windows(windows, labels, train_sl)
        vw, vy = slice_windows(windows, labels, val_sl)
        model = fusion_model_from_config(n_features, config).to(device)
        loader_kw = _loader_runtime_kwargs(config, device)
        train_loader = make_loader(
            tw,
            ty,
            batch_size=int(config.get("batch_size") or 64),
            shuffle=True,
            **loader_kw,
        )
        val_loader = make_loader(
            vw,
            vy,
            batch_size=int(config.get("batch_size") or 64),
            shuffle=False,
            **loader_kw,
        )
        extra = _fusion_train_extra(config)
        fold_cw = torch.tensor(
            inverse_frequency_class_weights(ty, FUSION_DIRECTION_CARDINALITY),
            dtype=torch.float32,
        )
        train_mtf_fusion(
            model,
            train_loader,
            val_loader,
            device=device,
            epochs=max(1, int(config.get("epochs") or 8) // 4),
            lr=float(config.get("lr") or 1e-4),
            weight_decay=float(config.get("weight_decay") or 1e-3),
            patience=max(2, int(config.get("early_stop_patience") or 3) // 2),
            class_weights=fold_cw,
            **extra,
        )
        logits, y = predict_logits(model, val_loader, device)
        row: Dict[str, Any] = {}
        for j, key in enumerate(FUSION_HORIZON_KEYS):
            m = horizon_metrics(logits[:, j, :], y[:, j])
            row[key] = m
            per_h_acc[key].append(float(m["balanced_acc"]))
        fold_rows.append(row)
    summary: Dict[str, Any] = {"folds": fold_rows, "mean": {}, "std": {}}
    for key in FUSION_HORIZON_KEYS:
        vals = per_h_acc[key]
        summary["mean"][key] = float(np.mean(vals)) if vals else 0.0
        summary["std"][key] = float(np.std(vals)) if vals else 0.0
    return summary


def freeze_horizon_gates(
    val_logits: np.ndarray,
    val_y: np.ndarray,
    walk_forward: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Calibrate and grade each horizon on validation. Do not touch test."""
    gates: Dict[str, Any] = {}
    temps: Dict[str, float] = {}
    for j, key in enumerate(FUSION_HORIZON_KEYS):
        temp = fit_temperature(val_logits[:, j, :], val_y[:, j])
        temps[key] = temp
        m = horizon_metrics(val_logits[:, j, :], val_y[:, j], temperature=temp)
        fold_std = float((walk_forward.get("std") or {}).get(key) or 0.0)
        grade = grade_horizon(
            balanced_acc=float(m["balanced_acc"]),
            ece=float(m["ece"]),
            fold_std=fold_std,
            high_acc=float(config.get("high_balanced_acc") or FUSION_HIGH_BALANCED_ACC),
            high_ece=float(config.get("high_max_ece") or FUSION_HIGH_MAX_ECE),
            medium_acc=float(config.get("medium_balanced_acc") or FUSION_MEDIUM_BALANCED_ACC),
        )
        gates[key] = {
            **m,
            "temperature": temp,
            "validation_confidence": grade,
            "min_probability": float(config.get("min_probability") or FUSION_MIN_PROBABILITY),
            "accepted_grades": [FUSION_GRADE_HIGH, FUSION_GRADE_MEDIUM],
        }
    return {"horizons": gates, "temperatures": temps}


def export_fusion_bundle(
    model: MtfFusionTransformer,
    export_dir: Path,
    *,
    n_features: int,
    window_len: Optional[int] = None,
    window_lens: Optional[Mapping[str, int]] = None,
    config: Mapping[str, Any],
    gates: Mapping[str, Any],
    fusion_weights: Sequence[float],
    test_metrics: Mapping[str, Any] | None = None,
) -> Tuple[Path, Path, Path]:
    """Write ONNX + feature_config + metadata for the single fused bundle."""
    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = export_dir / FUSION_ONNX_FILENAME
    cfg_path = export_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    meta_path = export_dir / TRANSFORMER_METADATA_FILENAME
    cfg_lens = config.get("window_lens") if config is not None else None
    target_minutes = int(
        (config or {}).get("target_window_minutes") or FUSION_TARGET_WINDOW_MINUTES
    )
    lens = resolve_fusion_window_lens(
        window_lens if window_lens is not None else cfg_lens,
        window_len,
        target_minutes=target_minutes,
    )
    dummy = [
        torch.randn(1, int(lens[res]), int(n_features))
        for res in FUSION_INPUT_RESOLUTIONS
    ]
    input_names = [f"features_{res}" for res in FUSION_INPUT_RESOLUTIONS]
    output_names = list(ONNX_OUTPUT_NAMES_V11)
    dynamic_axes = {name: {0: "batch"} for name in input_names + output_names}
    model.cpu().eval()
    export_kwargs: Dict[str, Any] = {
        "input_names": input_names,
        "output_names": output_names,
        "dynamic_axes": dynamic_axes,
        "opset_version": 17,
        "export_params": True,
    }
    last_error: Optional[BaseException] = None
    exported = False
    for opset in (17, 14):
        export_kwargs["opset_version"] = int(opset)
        try:
            try:
                torch.onnx.export(
                    model,
                    tuple(dummy),
                    str(onnx_path),
                    dynamo=False,
                    **export_kwargs,
                )
            except TypeError:
                torch.onnx.export(
                    model, tuple(dummy), str(onnx_path), **export_kwargs
                )
            exported = True
            break
        except (TypeError, RuntimeError, ValueError) as exc:
            last_error = exc
    if not exported:
        raise RuntimeError(
            f"ONNX export failed for opset 17 and 14: {last_error}"
        ) from last_error
    try:
        import onnx

        onnx.checker.check_model(onnx.load(str(onnx_path)))
    except ImportError:
        pass

    feature_config = {
        "feature_contract_version": FEATURE_CONTRACT_VERSION_V11,
        "feature_cols": list(fusion_feature_cols()),
        "window_len": int(max(lens.values())),
        "window_lens": {res: int(lens[res]) for res in FUSION_INPUT_RESOLUTIONS},
        "target_window_minutes": target_minutes,
        "resolutions": list(FUSION_INPUT_RESOLUTIONS),
        "horizon_keys": list(FUSION_HORIZON_KEYS),
        "direction_names": {str(k): v for k, v in FUSION_DIRECTION_NAMES.items()},
        "onnx_output_names": output_names,
        "input_names": input_names,
        "config": dict(config),
        "horizon_gates": dict(gates),
        "tf_fusion_weights": [float(x) for x in fusion_weights],
    }
    cfg_path.write_text(
        json.dumps(feature_config, indent=2, default=str), encoding="utf-8"
    )
    meta = {
        "version": "transformer_mtf_fusion_v11",
        "model_name": "jacksparrow_transformer_BTCUSD_mtf_fusion",
        "model_family": FUSION_MODEL_FAMILY,
        "symbol": str(config.get("symbol") or "BTCUSD"),
        "resolution": "mtf_fusion",
        "onnx_filename": FUSION_ONNX_FILENAME,
        "feature_config_filename": TRANSFORMER_FEATURE_CONFIG_FILENAME,
        "onnx_output_names": output_names,
        "tf_fusion_weights": [float(x) for x in fusion_weights],
        "horizon_gates": dict(gates),
        "test_metrics": dict(test_metrics or {}),
        "training_config": dict(config),
        "primary_signal_mode": "multi_horizon_position",
    }
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return onnx_path, cfg_path, meta_path


def purged_dev_test_split(
    windows: Mapping[str, np.ndarray],
    labels: np.ndarray,
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, Dict[str, np.ndarray]]:
    """Time-ordered train/val/test with embargo. Test is the final untouched tail."""
    packed = {**{f"x_{k}": v for k, v in windows.items()}, "y": labels}
    splits = split_purged_windows(
        packed, train_frac=train_frac, val_frac=val_frac, embargo_bars=embargo_bars
    )
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for name, part in splits.items():
        out[name] = {
            "windows": {res: part[f"x_{res}"] for res in FUSION_INPUT_RESOLUTIONS},
            "labels": part["y"],
        }
    return out


def fusion_ready_to_promote(
    walk_forward: Mapping[str, Any],
    test_metrics: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> Dict[str, Any]:
    """True if at least one head is MEDIUM+ on WF mean, frozen test, and val gate.

    The exported ``validation_confidence`` is what live will trade. Frozen test
    is graded from test metrics, not copied from validation. Walk-forward mean
    has no ECE, so WF HIGH is not used; MEDIUM is enough on that axis.
    """
    wf_mean = dict(walk_forward.get("mean") or {})
    wf_std = dict(walk_forward.get("std") or {})
    gate_map = dict(gates.get("horizons") or gates)
    ready_heads: List[str] = []
    detail: Dict[str, Any] = {}
    accepted = {FUSION_GRADE_HIGH, FUSION_GRADE_MEDIUM}
    for key in FUSION_HORIZON_KEYS:
        test_m = dict(test_metrics.get(key) or {})
        test_acc = float(test_m.get("balanced_acc") or 0.0)
        test_ece = float(test_m.get("ece") or 1.0)
        wf_acc = float(wf_mean.get(key) or 0.0)
        fold_std = float(wf_std.get(key) or 0.0)
        val_grade = str(
            (gate_map.get(key) or {}).get("validation_confidence") or ""
        )
        test_grade = grade_horizon(balanced_acc=test_acc, ece=test_ece)
        wf_grade = grade_horizon(
            balanced_acc=wf_acc,
            ece=1.0,
            fold_std=fold_std,
        )
        ok = (
            wf_grade in accepted
            and test_grade in accepted
            and val_grade in accepted
        )
        if ok:
            ready_heads.append(key)
        detail[key] = {
            "walk_forward_mean_acc": wf_acc,
            "walk_forward_grade": wf_grade,
            "test_acc": test_acc,
            "test_ece": test_ece,
            "test_grade": test_grade,
            "validation_grade": val_grade,
            "ok": ok,
        }
    ready = bool(ready_heads)
    return {
        "ready": ready,
        "heads": ready_heads,
        "detail": detail,
        "reason": (
            "at least one head MEDIUM+ on walk-forward mean, frozen test, and val gate"
            if ready
            else (
                "no head is MEDIUM on walk-forward mean, frozen test, and val gate; "
                "do not promote"
            )
        ),
    }


def default_config() -> Dict[str, Any]:
    cfg = default_fusion_training_config()
    cfg["window_len"] = FUSION_WINDOW_LEN
    cfg["window_lens"] = resolve_fusion_window_lens(cfg.get("window_lens"))
    cfg["target_window_minutes"] = int(
        cfg.get("target_window_minutes") or FUSION_TARGET_WINDOW_MINUTES
    )
    cfg["n_classes"] = FUSION_DIRECTION_CARDINALITY
    return cfg
