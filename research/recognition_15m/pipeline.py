"""Train the phase-1 recognition heads and write research metrics.

Running this module does not register a live model and does not send orders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog
import torch

from research.recognition_15m.bars import dedupe_timestamps, resample_completed_15m
from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    EVAL_STRIDE,
    HEADS_NOT_TRAINED,
    OUTPUT_RELATIVE,
    RAW_CHANNELS,
    SEED,
    SOURCE_RELATIVE,
    SPEC_VERSION,
    TRAIN_STRIDE,
)
from research.recognition_15m.dataset import (
    ChannelScaler,
    prepare_series,
    rule_card_is_separate,
    stack_windows,
)
from research.recognition_15m.models import train_presence_baseline, train_tcn
from research.recognition_15m.splits import nonoverlapping_ends, strided_ends

logger = structlog.get_logger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def run(
    source: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Resample, guard the tensor, train both feature modes, and score test.

    Args:
        source: 5-minute parquet. Defaults to the frozen research export.
        output: Metrics JSON path. Checkpoints are written beside it.

    Returns:
        JSON-safe metrics. Test scores use non-overlapping windows.
    """
    source_path = source or (_REPO_ROOT / SOURCE_RELATIVE)
    output_path = output or (_REPO_ROOT / OUTPUT_RELATIVE)
    raw = pd.read_parquet(source_path)
    bars = resample_completed_15m(dedupe_timestamps(raw))
    logger.info("recognition_bars", rows_5m=int(len(raw)), rows_15m=int(len(bars)))
    prepared = prepare_series(bars)
    if not rule_card_is_separate(prepared):
        raise ValueError("rule card was not separated from the feature tensor")
    card = prepared.pop("rule_card")
    splits = prepared["splits"]
    if not isinstance(splits, dict):
        raise TypeError("prepared series is missing splits")
    metrics: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "rows_5m": int(len(raw)),
        "rows_15m": int(len(bars)),
        "rule_card_rows": int(len(card)),
        "heads_not_trained": list(HEADS_NOT_TRAINED),
        "channels": {"raw": list(RAW_CHANNELS), "engineered": list(ENGINEERED_CHANNELS)},
        "windows": {
            name: int(len(indices))
            for name, indices in splits.items()
        },
        "purge_gap_bars": {
            "train_val": int(splits["val"][0] - splits["train"][-1]),
            "val_test": int(splits["test"][0] - splits["val"][-1]),
        },
        "train_stride_bars": TRAIN_STRIDE,
        "eval_stride_bars": EVAL_STRIDE,
    }
    train_ends = strided_ends(splits["train"], TRAIN_STRIDE)
    val_ends = strided_ends(splits["val"], TRAIN_STRIDE)
    test_ends = nonoverlapping_ends(splits["test"], EVAL_STRIDE)
    engineered_train = _scale_split(prepared, train_ends, val_ends, test_ends, "engineered")
    raw_train = _scale_split(prepared, train_ends, val_ends, test_ends, "raw")
    metrics["tcn_engineered"] = _fit_tcn(
        engineered_train,
        output_path.with_name("tcn_engineered.pt"),
    )
    metrics["tcn_raw"] = _fit_tcn(raw_train, output_path.with_name("tcn_raw.pt"))
    metrics["xgboost_presence"] = train_presence_baseline(
        engineered_train["train"]["features"],
        engineered_train["train"]["geometry"],
        engineered_train["test"]["features"],
        engineered_train["test"]["geometry"],
        seed=SEED,
    )
    metrics["ablation"] = {
        "raw_geometry_macro_f1": metrics["tcn_raw"]["test"]["geometry_macro_f1"],
        "engineered_geometry_macro_f1": metrics["tcn_engineered"]["test"]["geometry_macro_f1"],
        "xgboost_presence_macro_f1": metrics["xgboost_presence"]["macro_f1"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_json_ready(metrics), indent=2), encoding="utf-8")
    logger.info(
        "recognition_15m_trained",
        rows_15m=metrics["rows_15m"],
        raw_f1=metrics["ablation"]["raw_geometry_macro_f1"],
        engineered_f1=metrics["ablation"]["engineered_geometry_macro_f1"],
        output=str(output_path),
    )
    return metrics


def _scale_split(
    prepared: dict[str, object],
    train_ends: np.ndarray,
    val_ends: np.ndarray,
    test_ends: np.ndarray,
    mode: str,
) -> dict[str, dict[str, np.ndarray]]:
    """Stack windows and standardize them with the training-split scaler."""
    train = stack_windows(prepared, train_ends, mode)
    val = stack_windows(prepared, val_ends, mode)
    test = stack_windows(prepared, test_ends, mode)
    scaler = ChannelScaler().fit(train["features"])
    for batch in (train, val, test):
        batch["features"] = scaler.transform(batch["features"])
        batch["scaler_mean"] = scaler.mean
        batch["scaler_std"] = scaler.std
    return {"train": train, "val": val, "test": test}


def _fit_tcn(batches: dict[str, dict[str, np.ndarray]], checkpoint: Path) -> dict[str, Any]:
    """Train one feature mode and store the chosen epoch beside the metrics."""
    trained = train_tcn(batches["train"], batches["val"], batches["test"], seed=SEED)
    state = trained.pop("state_dict")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "spec_version": SPEC_VERSION,
            "state_dict": state,
            "channels": batches["train"]["channels"].tolist(),
            "scaler_mean": batches["train"]["scaler_mean"],
            "scaler_std": batches["train"]["scaler_std"],
        },
        checkpoint,
    )
    return trained


def _json_ready(value: Any) -> Any:
    """Convert numpy values so the metrics file is plain JSON."""
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_ready(value.tolist())
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def main() -> int:
    """Train from the default 5-minute export."""
    run()
    return 0
