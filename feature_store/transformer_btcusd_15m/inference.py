"""Window building and label un-standardization for transformer inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np

from feature_store.transformer_btcusd_15m.contract import (
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    FEATURE_CONTRACT_VERSION,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
)


def load_feature_config(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def resolve_feature_config(bundle_dir: Path) -> Dict[str, Any]:
    cfg_path = bundle_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"Missing {TRANSFORMER_FEATURE_CONFIG_FILENAME} in {bundle_dir}"
        )
    return load_feature_config(cfg_path)


def zscore_window(window: np.ndarray) -> np.ndarray:
    """Per-window z-score (matches Colab ``WindowDataset``)."""
    mu = window.mean(axis=0, keepdims=True)
    sd = window.std(axis=0, keepdims=True) + 1e-6
    return ((window - mu) / sd).astype(np.float32)


def build_inference_window(
    feat_values: np.ndarray,
    *,
    window_len: int,
    feature_cols: Sequence[str] = FEATURE_COLS,
) -> np.ndarray:
    """Build a single (1, window_len, n_features) tensor from feature matrix values."""
    if feat_values.shape[0] < window_len:
        raise ValueError(
            f"Need at least {window_len} feature rows, got {feat_values.shape[0]}"
        )
    window = feat_values[-window_len:, :].astype(np.float32)
    if not np.isfinite(window).all():
        raise ValueError("Feature window contains non-finite values")
    normed = zscore_window(window)
    return normed[np.newaxis, :, :]


def unstandardize_continuous(
    pred_z: np.ndarray,
    label_mean: Sequence[float],
    label_std: Sequence[float],
    *,
    label_cols: Sequence[str] = CONTINUOUS_LABEL_COLS,
) -> Dict[str, float]:
    """Map standardized ONNX output back to real units."""
    mean = np.asarray(label_mean, dtype=np.float64)
    std = np.asarray(label_std, dtype=np.float64)
    flat = np.asarray(pred_z, dtype=np.float64).reshape(-1)
    if flat.shape[0] != len(label_cols):
        raise ValueError(
            f"Expected {len(label_cols)} continuous outputs, got {flat.shape[0]}"
        )
    real = flat * std + mean
    return {str(col): float(val) for col, val in zip(label_cols, real)}


def softmax(logits: np.ndarray) -> np.ndarray:
    x = np.asarray(logits, dtype=np.float64).reshape(-1)
    x = x - x.max()
    exp = np.exp(x)
    return exp / (exp.sum() + 1e-12)


def parse_regime_prediction(
    regime_logits: np.ndarray,
    regime_names: Mapping[str, str],
) -> Tuple[int, str, Dict[str, float]]:
    probs = softmax(regime_logits)
    idx = int(np.argmax(probs))
    name = regime_names.get(str(idx), regime_names.get(idx, f"CLASS_{idx}"))
    prob_map = {
        regime_names.get(str(i), f"CLASS_{i}"): float(probs[i])
        for i in range(len(probs))
    }
    return idx, str(name), prob_map


def feature_config_from_training_export(
    *,
    feature_cols: Sequence[str],
    window_len: int,
    label_mean: Sequence[float],
    label_std: Sequence[float],
    q_edges: Sequence[float],
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build ``feature_config.json`` payload written by Colab export cell."""
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "feature_cols": list(feature_cols),
        "window_len": int(window_len),
        "continuous_label_cols": list(CONTINUOUS_LABEL_COLS),
        "label_mean": [float(x) for x in label_mean],
        "label_std": [float(x) for x in label_std],
        "regime_names": {"0": "LOW", "1": "NORMAL", "2": "HIGH", "3": "EXTREME"},
        "vol_regime_quantile_edges": [float(x) for x in q_edges],
        "config": dict(config),
    }
