"""Colab entry point for the intense recognition run.

The sealed test is scored once. The report is not an order and it is not
copied into the live model directory.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from research.recognition_15m.bars import dedupe_timestamps, resample_completed_15m
from research.recognition_15m.contract import (
    COLAB_OUTPUT_RELATIVE,
    ENGINEERED_CHANNELS,
    EVAL_STRIDE,
    FINAL_EPOCHS,
    FINAL_PATIENCE,
    HEADS_NOT_TRAINED,
    SEARCH_TRIALS,
    SEED,
    SHAP_SAMPLE,
    SPEC_VERSION,
    TRAIN_STRIDE,
    WINDOW_BARS,
)
from research.recognition_15m.dataset import (
    ChannelScaler,
    prepare_series,
    rule_card_is_separate,
    stack_windows,
)
from research.recognition_15m.explain import presence_shap, spearman_report
from research.recognition_15m.features import first_finite_bar
from research.recognition_15m.integrity import assert_causal_at
from research.recognition_15m.models import train_tcn
from research.recognition_15m.plots import write_recognition_figures
from research.recognition_15m.search import (
    assert_folds_exclude_test,
    run_optuna_search,
)
from research.recognition_15m.splits import (
    development_folds,
    nonoverlapping_ends,
    strided_ends,
)

_FORBIDDEN_REPORT_TEXT = (
    "expectancy",
    "sharpe",
    "model_storage",
    "forecastmodelnode",
    "orders_enabled",
    "buy_signal",
    "sell_signal",
)


def run_colab(
    source: Path,
    output_dir: Path | None = None,
    *,
    n_trials: int = SEARCH_TRIALS,
    seed: int = SEED,
    shap_sample: int = SHAP_SAMPLE,
) -> dict[str, Any]:
    """Search, explain, refit, and score the sealed recognition test.

    Args:
        source: 5-minute BTCUSD parquet.
        output_dir: Directory for the report, checkpoint, and zip.
        n_trials: Optuna trials on the development span.
        seed: Split and sampler seed.
        shap_sample: Development windows explained by TreeSHAP.

    Returns:
        The recognition report. It has no order fields.
    """
    destination = output_dir or (_repo_root() / COLAB_OUTPUT_RELATIVE).parent
    destination.mkdir(parents=True, exist_ok=True)
    raw = pd.read_parquet(source)
    bars = resample_completed_15m(dedupe_timestamps(raw))
    prepared = prepare_series(bars)
    if not rule_card_is_separate(prepared):
        raise ValueError("rule card was not separated from the feature tensor")
    prepared.pop("rule_card")
    splits = prepared["splits"]
    if not isinstance(splits, dict):
        raise TypeError("prepared series is missing splits")
    folds = development_folds(splits["train"], splits["val"])
    assert_folds_exclude_test(folds, splits["test"])
    indices = perturbation_indices(len(bars), first_finite_bar(prepared["features"]))
    for index in indices:
        assert_causal_at(bars, index)
    study = run_optuna_search(
        prepared,
        splits["train"],
        splits["val"],
        n_trials=n_trials,
        seed=seed,
    )
    train_view = strided_ends(splits["train"], TRAIN_STRIDE)
    audit = stack_windows(prepared, train_view, "engineered")
    correlation = spearman_report(
        audit["features"],
        audit["geometry"],
        audit["state"],
        tuple(audit["channels"]),
    )
    explained = presence_shap(
        audit["features"],
        audit["geometry"],
        tuple(audit["channels"]),
        sample_size=shap_sample,
        seed=seed,
    )
    stride = final_train_stride(int(len(splits["train"])), len(ENGINEERED_CHANNELS))
    trained = _refit(
        prepared,
        splits,
        study["best_params"],
        stride,
        destination / "tcn_colab.pt",
        seed,
    )
    report = {
        "spec_version": SPEC_VERSION,
        "rows_5m": int(len(raw)),
        "rows_15m": int(len(bars)),
        "heads_not_trained": list(HEADS_NOT_TRAINED),
        "perturbation_indices": indices,
        "purge_gap_bars": {
            "train_val": int(splits["val"][0] - splits["train"][-1]),
            "val_test": int(splits["test"][0] - splits["val"][-1]),
        },
        "optuna": study,
        "correlation": {
            "threshold": correlation["threshold"],
            "pairs": correlation["pairs"],
            "flagged": correlation["flagged"],
            "pair_count": len(correlation["pairs"]),
        },
        "shap": explained,
        "final_stride_bars": stride,
        "eval_stride_bars": EVAL_STRIDE,
        "optimizer": trained["optimizer"],
        "fit": {
            "best_epoch": int(trained["best_epoch"]),
            "train_loss_by_epoch": [float(item) for item in trained["train_loss_by_epoch"]],
            "val_loss_by_epoch": [float(item) for item in trained["val_loss_by_epoch"]],
        },
        "val": trained["val"],
        "test": trained["test"],
        "sealed_test_scored_once": True,
    }
    figure_paths = write_recognition_figures(report, destination)
    report["figures"] = [path.name for path in figure_paths]
    assert_recognition_report(report)
    report_path = destination / "report.json"
    report_path.write_text(json.dumps(_json_ready(report), indent=2), encoding="utf-8")
    archive = destination / "recognition_15m_colab.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.write(report_path, arcname="report.json")
        handle.write(destination / "tcn_colab.pt", arcname="tcn_colab.pt")
        for figure_path in figure_paths:
            handle.write(figure_path, arcname=figure_path.name)
    report["report_path"] = str(report_path)
    report["zip_path"] = str(archive)
    return report


def perturbation_indices(n_bars: int, first_finite: int) -> list[int]:
    """Three bar indices with later bars available for a causality check.

    Args:
        n_bars: Length of the 15-minute series.
        first_finite: First bar whose engineered features are finite.

    Returns:
        Start, middle, and late indices. Each has at least one bar after it.

    Raises:
        ValueError: If the series cannot support the check.
    """
    start = first_finite + WINDOW_BARS
    late = n_bars - 2
    if start >= late:
        raise ValueError("series is too short for a future-bar check")
    mid = (start + late) // 2
    return [int(start), int(mid), int(late)]


def final_train_stride(n_train_ends: int, n_channels: int) -> int:
    """Use every training window on a GPU when the tensor fits.

    Args:
        n_train_ends: Windows in the outer training split.
        n_channels: Engineered channel count.

    Returns:
        1 or 2 on a GPU with room, otherwise the search stride of 4.
    """
    if not torch.cuda.is_available():
        return TRAIN_STRIDE
    estimate = int(n_train_ends) * WINDOW_BARS * int(n_channels) * 4
    if estimate <= 1_500_000_000:
        return 1
    if estimate <= 3_000_000_000:
        return 2
    return TRAIN_STRIDE


def _repo_root() -> Path:
    """Repository root when this file is on disk, otherwise the working directory.

    A Colab cell has no ``__file__``. The notebook passes an output directory,
    and this fallback keeps a local call working from the repo root.
    """
    located = globals().get("__file__")
    if isinstance(located, str) and located:
        return Path(located).resolve().parents[2]
    return Path.cwd()


def _json_ready(value: Any) -> Any:
    """Convert numpy values so the report file is plain JSON."""
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


def assert_recognition_report(report: dict[str, Any]) -> None:
    """Reject a report that carries an order or promotion field.

    Args:
        report: JSON-ready recognition report.

    Raises:
        ValueError: If forbidden trading text appears in the serialized report.
    """
    blob = json.dumps(_json_ready(report)).lower()
    found = [token for token in _FORBIDDEN_REPORT_TEXT if token in blob]
    if found:
        raise ValueError(f"recognition report contains trading fields: {found}")


def _refit(
    prepared: dict[str, object],
    splits: dict[str, np.ndarray],
    params: dict[str, Any],
    stride: int,
    checkpoint: Path,
    seed: int,
) -> dict[str, Any]:
    """Refit the chosen TCN and score the sealed test once."""
    train_ends = strided_ends(splits["train"], stride)
    val_ends = nonoverlapping_ends(splits["val"], EVAL_STRIDE)
    test_ends = nonoverlapping_ends(splits["test"], EVAL_STRIDE)
    train = stack_windows(prepared, train_ends, "engineered")
    val = stack_windows(prepared, val_ends, "engineered")
    test = stack_windows(prepared, test_ends, "engineered")
    scaler = ChannelScaler().fit(train["features"])
    for batch in (train, val, test):
        batch["features"] = scaler.transform(batch["features"])
    trained = train_tcn(
        train,
        val,
        test,
        epochs=FINAL_EPOCHS,
        batch_size=int(params["batch_size"]),
        seed=seed,
        hidden=int(params["hidden"]),
        dilations=tuple(int(item) for item in params["dilations"]),
        learning_rate=float(params["learning_rate"]),
        pos_weight_clip=float(params["pos_weight_clip"]),
        patience=FINAL_PATIENCE,
        include_test_calibration=True,
    )
    state = trained.pop("state_dict")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "spec_version": SPEC_VERSION,
            "state_dict": state,
            "best_params": params,
            "scaler_mean": scaler.mean,
            "scaler_std": scaler.std,
            "channels": list(ENGINEERED_CHANNELS),
        },
        checkpoint,
    )
    return trained


def main() -> int:
    """Run from a local parquet when Colab is not the host."""
    from research.recognition_15m.contract import SOURCE_RELATIVE

    run_colab(_repo_root() / SOURCE_RELATIVE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
