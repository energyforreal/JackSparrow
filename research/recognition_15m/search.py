"""Purged Bayesian search for the recognition TCN.

The study never receives the sealed test ends. Its score is recognition
macro-F1, not a trading result.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import optuna

from research.recognition_15m.contract import (
    BATCH_CHOICES,
    CLIP_CHOICES,
    DEVELOPMENT_FOLDS,
    EVAL_STRIDE,
    HIDDEN_CHOICES,
    PURGE_BARS,
    SEARCH_EPOCHS,
    SEARCH_PATIENCE,
    SEARCH_TRIALS,
    SEED,
    TRAIN_STRIDE,
)
from research.recognition_15m.dataset import ChannelScaler, stack_windows
from research.recognition_15m.models import train_tcn
from research.recognition_15m.splits import (
    development_folds,
    nonoverlapping_ends,
    strided_ends,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)


def run_optuna_search(
    prepared: Mapping[str, object],
    train_ends: np.ndarray,
    val_ends: np.ndarray,
    *,
    n_trials: int = SEARCH_TRIALS,
    max_epochs: int = SEARCH_EPOCHS,
    patience: int = SEARCH_PATIENCE,
    seed: int = SEED,
    hidden_choices: Sequence[int] = HIDDEN_CHOICES,
    batch_choices: Sequence[int] = BATCH_CHOICES,
    clip_choices: Sequence[float] = CLIP_CHOICES,
    search_stride: int = TRAIN_STRIDE,
    folds: int = DEVELOPMENT_FOLDS,
) -> dict[str, Any]:
    """Search TCN settings on development folds.

    Args:
        prepared: Feature frame and labels from ``prepare_series``.
        train_ends: Outer training ends. Test ends must not be included.
        val_ends: Outer validation ends. Test ends must not be included.
        n_trials: Optuna trials.
        max_epochs: Epoch cap inside each trial.
        patience: Early-stopping patience on fold validation loss.
        seed: Sampler seed.
        hidden_choices: Encoder widths.
        batch_choices: Mini-batch sizes.
        clip_choices: Positive-class weight caps.
        search_stride: Training-window stride used inside the study.
        folds: Chronological development folds.

    Returns:
        The best trial parameters and the mean recognition score.

    Raises:
        ValueError: If a fold overlaps a caller-supplied sealed test.
    """
    fold_rows = development_folds(train_ends, val_ends, folds=folds, purge=PURGE_BARS)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=0),
    )

    def objective(trial: optuna.Trial) -> float:
        depth = trial.suggest_int("dilation_depth", 2, 4)
        params = {
            "hidden": int(trial.suggest_categorical("hidden", list(hidden_choices))),
            "dilations": tuple(2**index for index in range(depth)),
            "learning_rate": float(
                trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True)
            ),
            "batch_size": int(trial.suggest_categorical("batch_size", list(batch_choices))),
            "pos_weight_clip": float(
                trial.suggest_categorical("pos_weight_clip", list(clip_choices))
            ),
        }
        scores: list[float] = []
        for step, fold in enumerate(fold_rows):
            scores.append(
                _fold_score(
                    prepared,
                    fold,
                    params,
                    max_epochs=max_epochs,
                    patience=patience,
                    seed=seed + trial.number,
                    search_stride=search_stride,
                )
            )
            trial.report(float(np.mean(scores)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(scores)) if scores else 0.0

    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_trial
    depth = int(best.params["dilation_depth"])
    return {
        "best_value": float(best.value) if best.value is not None else 0.0,
        "trials": _trial_rows(study),
        "best_params": {
            "hidden": int(best.params["hidden"]),
            "dilation_depth": depth,
            "dilations": [int(2**index) for index in range(depth)],
            "learning_rate": float(best.params["learning_rate"]),
            "batch_size": int(best.params["batch_size"]),
            "pos_weight_clip": float(best.params["pos_weight_clip"]),
        },
        "n_trials": int(len(study.trials)),
        "folds": [
            {
                "train_windows": int(len(fold["train"])),
                "val_windows": int(len(fold["val"])),
                "purge_gap_bars": int(fold["val"][0] - fold["train"][-1]),
            }
            for fold in fold_rows
        ],
    }


def _trial_rows(study: optuna.Study) -> list[dict[str, Any]]:
    """One row per Optuna trial, including trials the pruner stopped."""
    rows: list[dict[str, Any]] = []
    for trial in study.trials:
        raw = trial.value
        value = None
        if raw is not None and np.isfinite(float(raw)):
            value = float(raw)
        rows.append(
            {
                "number": int(trial.number),
                "value": value,
                "state": str(trial.state.name),
            }
        )
    return rows


def assert_folds_exclude_test(
    folds: Sequence[Mapping[str, np.ndarray]],
    test_ends: np.ndarray,
) -> None:
    """Raise when a development fold contains a sealed test end."""
    sealed = {int(end) for end in np.asarray(test_ends, dtype=np.int64)}
    for fold in folds:
        seen = {int(end) for end in fold["train"]} | {int(end) for end in fold["val"]}
        leaked = sorted(sealed & seen)
        if leaked:
            raise ValueError(f"development fold contains sealed test ends: {leaked[:5]}")


def _fold_score(
    prepared: Mapping[str, object],
    fold: Mapping[str, np.ndarray],
    params: Mapping[str, Any],
    *,
    max_epochs: int,
    patience: int,
    seed: int,
    search_stride: int,
) -> float:
    """Recognition score for one purged fold. The test split is not read."""
    train_ends = strided_ends(fold["train"], search_stride)
    val_ends = nonoverlapping_ends(fold["val"], EVAL_STRIDE)
    if train_ends.size < 2 or val_ends.size < 1:
        return 0.0
    train, val = _scaled_pair(prepared, train_ends, val_ends)
    trained = train_tcn(
        train,
        val,
        None,
        epochs=max_epochs,
        batch_size=int(params["batch_size"]),
        seed=seed,
        hidden=int(params["hidden"]),
        dilations=tuple(int(item) for item in params["dilations"]),
        learning_rate=float(params["learning_rate"]),
        pos_weight_clip=float(params["pos_weight_clip"]),
        patience=patience,
    )
    geometry = float(trained["val"]["geometry_macro_f1"])
    state = float(trained["val"]["market_state"]["macro_f1"])
    return 0.5 * (geometry + state)


def _scaled_pair(
    prepared: Mapping[str, object],
    train_ends: np.ndarray,
    val_ends: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Standardize fold windows with a scaler fit on that fold's train rows."""
    train = stack_windows(prepared, train_ends, "engineered")
    val = stack_windows(prepared, val_ends, "engineered")
    scaler = ChannelScaler().fit(train["features"])
    train["features"] = scaler.transform(train["features"])
    val["features"] = scaler.transform(val["features"])
    return train, val
