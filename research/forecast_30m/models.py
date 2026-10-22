"""Baselines, XGBoost, LightGBM, and a capped development-only search.

Training helpers refuse rows at or after the holdout timestamp.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from research.forecast_30m.contract import (
    ABLATION_MIN_DELTA,
    CALENDAR_COLUMNS,
    FEATURE_COLUMNS,
    GATE4_LOGLOSS_LIFT,
    GATE4_MAE_LIFT,
    HORIZON_BARS,
    OPTUNA_TRIALS,
    SEED,
    TREE_DEFAULTS,
    TUNE_ENABLED,
)
from research.forecast_30m.contract_v3 import (
    ALGORITHM as V3_ALGORITHM,
    POLICY_THRESHOLD,
    RANKING_BINS,
    ROUND_TRIP_COST,
)
from research.forecast_30m.evaluation import (
    always_in_expectancy,
    barrier_expectancy,
    brier_score,
    development_policy_gate,
    direction_log_loss,
    gate4_passed,
    mean_absolute_error,
    one_position_policy,
    path_net_return,
    phase_average,
    probability_quintiles,
    ranking_statistical_gate,
)
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
    development_blocks,
)

TASKS = ("direction", "return", "long_tp", "short_tp")
TARGET_COLUMN = {
    "direction": "y_direction",
    "return": "forward_return_24",
    "long_tp": "long_tp_first_24",
    "short_tp": "short_tp_first_24",
}
HIGHER_IS_BETTER = {
    "direction": False,
    "return": False,
    "long_tp": True,
    "short_tp": True,
}
BARRIER_TASKS = ("long_tp", "short_tp")


def train_development(
    frame: pd.DataFrame,
    *,
    holdout_start: pd.Timestamp,
    tasks: Sequence[str],
    feature_columns: Sequence[str] = FEATURE_COLUMNS,
) -> dict[str, Any]:
    """Fit baselines and both tree models. Tuning stays off until Gate 4 is economic.

    Args:
        frame: Development rows only.
        holdout_start: Guard timestamp. Any row at or after it aborts training.
        tasks: Targets that passed the label rule.
        feature_columns: Causal columns available before ablation.

    Returns:
        Per-target walk-forward results, the frozen fit, and Gate 4.
    """
    assert_development_only(frame, holdout_start)
    results = {}
    for task in tasks:
        results[task] = _train_task(frame, task, list(feature_columns))
    return {"tasks": results, "orders_enabled": False}


def train_xgboost_event_policy(
    frame: pd.DataFrame,
    *,
    holdout_start: pd.Timestamp,
    embargo_end: pd.Timestamp,
    feature_columns: Sequence[str] = FEATURE_COLUMNS,
) -> dict[str, Any]:
    """Fit the v3 one-position policy. LightGBM and Optuna are not used.

    Args:
        frame: Development event rows only.
        holdout_start: First embargo timestamp. Any row at or after it aborts.
        embargo_end: Last embargo timestamp, used as a second leak check.
        feature_columns: Causal columns at the signal bar.

    Returns:
        Walk-forward policy stats, the economic gate, and frozen bundles when
        that gate passes.
    """
    assert_development_only(frame, holdout_start)
    assert_outside_embargo(frame, holdout_start, embargo_end)
    columns = list(feature_columns)
    blocks = development_blocks(frame["bar_index"].to_numpy(dtype=np.int64))
    fold_stats = []
    oof_rows = []
    oof_long = []
    oof_short = []
    for fold in blocks["walk_forward"]:
        train = frame.iloc[fold["train"]]
        validation = frame.iloc[fold["validation"]]
        try:
            long_est = _fit_estimator(
                V3_ALGORITHM, "long_tp", _task_rows(train, "long_tp"), columns, TREE_DEFAULTS
            )
            short_est = _fit_estimator(
                V3_ALGORITHM, "short_tp", _task_rows(train, "short_tp"), columns, TREE_DEFAULTS
            )
        except (ValueError, RuntimeError) as exc:
            fold_stats.append({"error": str(exc), "trades": 0})
            continue
        features = validation.loc[:, columns].to_numpy(dtype=np.float64)
        long_p = _predict_raw(long_est, "long_tp", features)
        short_p = _predict_raw(short_est, "short_tp", features)
        stats = one_position_policy(
            validation,
            long_p,
            short_p,
            threshold=POLICY_THRESHOLD,
            cost=ROUND_TRIP_COST,
        )
        fold_stats.append(
            {
                "trades": int(stats["trades"]),
                "expectancy": stats["expectancy"],
                "profit_factor": stats["profit_factor"],
            }
        )
        oof_rows.append(validation.reset_index(drop=True))
        oof_long.append(np.asarray(long_p, dtype=np.float64))
        oof_short.append(np.asarray(short_p, dtype=np.float64))
    if not oof_rows:
        gate = {
            "passed": False,
            "reasons": ["walk_forward_failed"],
            "trades": 0,
            "expectancy": None,
            "profit_factor": None,
        }
        oof_stats = {"trades": 0.0, "expectancy": 0.0, "profit_factor": 0.0}
    else:
        oof_frame = pd.concat(oof_rows, ignore_index=True)
        oof_stats = one_position_policy(
            oof_frame,
            np.concatenate(oof_long),
            np.concatenate(oof_short),
            threshold=POLICY_THRESHOLD,
            cost=ROUND_TRIP_COST,
        )
        gate = development_policy_gate(oof_stats)
    bundles = None
    if gate["passed"]:
        bundles = {
            "long_tp": _fit_event_bundle(frame, "long_tp", columns),
            "short_tp": _fit_event_bundle(frame, "short_tp", columns),
        }
    return {
        "algorithm": V3_ALGORITHM,
        "params": dict(TREE_DEFAULTS),
        "fold_stats": fold_stats,
        "oof": {
            "trades": oof_stats["trades"],
            "expectancy": oof_stats["expectancy"],
            "profit_factor": oof_stats.get("profit_factor"),
            "max_drawdown": oof_stats.get("max_drawdown"),
        },
        "gate": gate,
        "features": columns,
        "bundles": bundles,
        "orders_enabled": False,
    }


def rank_development_events(
    frame: pd.DataFrame,
    *,
    holdout_start: pd.Timestamp,
    embargo_end: pd.Timestamp,
    feature_columns: Sequence[str] = FEATURE_COLUMNS,
) -> dict[str, Any]:
    """Walk-forward ranking of development events. Confirmation is not scored.

    Args:
        frame: Development event rows only.
        holdout_start: First embargo timestamp.
        embargo_end: Last embargo timestamp.
        feature_columns: Causal columns at the signal bar.

    Returns:
        Baseline and XGBoost Brier folds, quintiles, always-in expectancy, and
        the out-of-fold one-position policy. Bundles are stored only as an
        inspection artifact; they are not a promotion.
    """
    assert_development_only(frame, holdout_start)
    assert_outside_embargo(frame, holdout_start, embargo_end)
    columns = list(feature_columns)
    blocks = development_blocks(frame["bar_index"].to_numpy(dtype=np.int64))
    fold_rows: list[dict[str, Any]] = []
    oof_parts: list[pd.DataFrame] = []
    oof_long: list[np.ndarray] = []
    oof_short: list[np.ndarray] = []
    oof_long_base: list[np.ndarray] = []
    oof_short_base: list[np.ndarray] = []
    long_model_brier: list[float] = []
    long_base_brier: list[float] = []
    short_model_brier: list[float] = []
    short_base_brier: list[float] = []
    for fold in blocks["walk_forward"]:
        train = frame.iloc[fold["train"]]
        validation = frame.iloc[fold["validation"]]
        row: dict[str, Any] = {}
        try:
            long_model = _fit_estimator(
                V3_ALGORITHM, "long_tp", _task_rows(train, "long_tp"), columns, TREE_DEFAULTS
            )
            short_model = _fit_estimator(
                V3_ALGORITHM, "short_tp", _task_rows(train, "short_tp"), columns, TREE_DEFAULTS
            )
            long_base = _fit_baseline("long_tp", _target(_task_rows(train, "long_tp"), "long_tp"))
            short_base = _fit_baseline(
                "short_tp", _target(_task_rows(train, "short_tp"), "short_tp")
            )
        except (ValueError, RuntimeError) as exc:
            row["error"] = str(exc)
            fold_rows.append(row)
            continue
        features = validation.loc[:, columns].to_numpy(dtype=np.float64)
        long_p = _predict_raw(long_model, "long_tp", features)
        short_p = _predict_raw(short_model, "short_tp", features)
        long_b = _predict_raw(long_base, "long_tp", features)
        short_b = _predict_raw(short_base, "short_tp", features)
        long_brier = _side_brier(validation, "long_tp", long_p)
        short_brier = _side_brier(validation, "short_tp", short_p)
        long_brier_base = _side_brier(validation, "long_tp", long_b)
        short_brier_base = _side_brier(validation, "short_tp", short_b)
        long_model_brier.append(long_brier)
        long_base_brier.append(long_brier_base)
        short_model_brier.append(short_brier)
        short_base_brier.append(short_brier_base)
        row = {
            "long_brier": long_brier,
            "long_brier_baseline": long_brier_base,
            "short_brier": short_brier,
            "short_brier_baseline": short_brier_base,
            "baseline_long_rate": float(long_base["rate"]),
            "baseline_short_rate": float(short_base["rate"]),
            "validation_rows": int(len(validation)),
        }
        fold_rows.append(row)
        oof_parts.append(validation.reset_index(drop=True))
        oof_long.append(np.asarray(long_p, dtype=np.float64))
        oof_short.append(np.asarray(short_p, dtype=np.float64))
        oof_long_base.append(np.asarray(long_b, dtype=np.float64))
        oof_short_base.append(np.asarray(short_b, dtype=np.float64))
    statistical = {
        "long": ranking_statistical_gate(long_model_brier, long_base_brier),
        "short": ranking_statistical_gate(short_model_brier, short_base_brier),
    }
    if not oof_parts:
        return {
            "folds": fold_rows,
            "statistical": statistical,
            "economic": {"passed": False, "reasons": ["walk_forward_failed"]},
            "always_in": None,
            "quintiles": {},
            "bundles": None,
            "orders_enabled": False,
            "confirmation_scored": False,
        }
    oof = pd.concat(oof_parts, ignore_index=True)
    long_p = np.concatenate(oof_long)
    short_p = np.concatenate(oof_short)
    long_b = np.concatenate(oof_long_base)
    short_b = np.concatenate(oof_short_base)
    model_policy = one_position_policy(
        oof, long_p, short_p, threshold=POLICY_THRESHOLD, cost=ROUND_TRIP_COST
    )
    base_policy = one_position_policy(
        oof, long_b, short_b, threshold=POLICY_THRESHOLD, cost=ROUND_TRIP_COST
    )
    always = always_in_expectancy(oof, cost=ROUND_TRIP_COST)
    economic = development_policy_gate(model_policy)
    economic["always_in_average"] = always["average"]
    economic["baseline_policy"] = {
        "trades": base_policy["trades"],
        "expectancy": base_policy["expectancy"],
        "profit_factor": base_policy.get("profit_factor"),
    }
    economic["model_policy"] = {
        "trades": model_policy["trades"],
        "expectancy": model_policy["expectancy"],
        "profit_factor": model_policy.get("profit_factor"),
        "max_drawdown": model_policy.get("max_drawdown"),
    }
    quintiles = {
        "long": probability_quintiles(
            long_p, path_net_return(oof, side="long"), bins=RANKING_BINS
        ),
        "short": probability_quintiles(
            short_p, path_net_return(oof, side="short"), bins=RANKING_BINS
        ),
    }
    return {
        "algorithm": V3_ALGORITHM,
        "params": dict(TREE_DEFAULTS),
        "features": columns,
        "oof_rows": int(len(oof)),
        "folds": fold_rows,
        "statistical": statistical,
        "economic": economic,
        "always_in": always,
        "quintiles": quintiles,
        "bundles": {
            "long_tp": _fit_event_bundle(frame, "long_tp", columns),
            "short_tp": _fit_event_bundle(frame, "short_tp", columns),
        },
        "orders_enabled": False,
        "confirmation_scored": False,
        "promoted_to_agent": False,
    }


def _side_brier(frame: pd.DataFrame, task: str, probability: np.ndarray) -> float:
    target = frame[TARGET_COLUMN[task]].to_numpy(dtype=np.float64)
    mask = np.isfinite(target)
    if not mask.any():
        return float("nan")
    return brier_score(target[mask], np.asarray(probability, dtype=np.float64)[mask])


def _fit_event_bundle(
    frame: pd.DataFrame,
    task: str,
    feature_columns: Sequence[str],
) -> dict[str, Any]:
    rows = _task_rows(frame, task)
    estimator = _fit_estimator(V3_ALGORITHM, task, rows, feature_columns, TREE_DEFAULTS)
    return {
        "task": task,
        "algorithm": V3_ALGORITHM,
        "features": list(feature_columns),
        "params": dict(TREE_DEFAULTS),
        "estimator": estimator,
        "calibrator": None,
    }


def score_frozen(bundle: Mapping[str, Any], frame: pd.DataFrame) -> dict[str, float]:
    """Score one frozen bundle. This does not fit anything.

    Args:
        bundle: Output stored under a passed Gate 4 target.
        frame: Rows to score, already restricted to one time split.

    Returns:
        Phase-averaged primary score and the overlapping diagnostic.
    """
    task = str(bundle["task"])
    columns = list(bundle["features"])
    prediction = predict_bundle(bundle, frame.loc[:, columns].to_numpy(dtype=np.float64))
    if task == "direction":
        mask = frame["y_direction"].to_numpy(dtype=np.int64) >= 0
    elif task == "return":
        mask = np.isfinite(frame["forward_return_24"].to_numpy(dtype=np.float64))
    else:
        mask = np.isfinite(frame[TARGET_COLUMN[task]].to_numpy(dtype=np.float64))
    eligible = frame.iloc[np.flatnonzero(mask)].reset_index(drop=True)
    prediction = prediction[mask]
    return {
        "primary": _primary_score(task, eligible, prediction),
        "overlapping": _overlapping_score(task, eligible, prediction),
    }


def predict_bundle(bundle: Mapping[str, Any], features: np.ndarray) -> np.ndarray:
    """Apply a frozen estimator and its calibration map.

    Args:
        bundle: Final model dict produced by :func:`train_development`.
        features: Array of shape ``(n, n_features)``.

    Returns:
        Class probabilities with shape ``(n, k)``, or a return vector ``(n,)``.
    """
    task = str(bundle["task"])
    raw = _predict_raw(bundle["estimator"], task, features)
    calibrator = bundle.get("calibrator")
    if calibrator is None or task == "return":
        return raw
    return _apply_calibrator(calibrator, raw, task)


def train_direction_xgb(
    frame: pd.DataFrame,
    *,
    holdout_start: pd.Timestamp,
    embargo_end: pd.Timestamp,
    feature_columns: Sequence[str],
) -> dict[str, Any]:
    """Fit the v4 direction head. Only XGBoost is compared with the class prior.

    Args:
        frame: Development rows with ``y_direction``.
        holdout_start: First embargo timestamp.
        embargo_end: Last embargo timestamp.
        feature_columns: Causal columns, including the v4 pattern block.

    Returns:
        Walk-forward scores, Gate 4, and a frozen bundle when the gate passes.
    """
    assert_development_only(frame, holdout_start)
    assert_outside_embargo(frame, holdout_start, embargo_end)
    task = _train_task(
        frame,
        "direction",
        list(feature_columns),
        algorithms=("baseline", "xgb"),
    )
    return {"tasks": {"direction": task}, "orders_enabled": False}


def _train_task(
    frame: pd.DataFrame,
    task: str,
    feature_columns: list[str],
    algorithms: Sequence[str] | None = None,
) -> dict[str, Any]:
    import structlog

    structlog.get_logger().info("forecast_30m_task_start", task=task, rows=int(len(frame)))
    rows = _task_rows(frame, task)
    blocks = development_blocks(rows["bar_index"].to_numpy(dtype=np.int64))
    names = list(algorithms) if algorithms is not None else ["baseline", "xgb", "lgbm"]
    phase3 = {
        algorithm: _walk_forward(rows, task, algorithm, feature_columns, TREE_DEFAULTS, blocks)
        for algorithm in names
    }
    if "lgbm" in phase3 and "xgb" in phase3:
        winner = _better_tree(task, phase3["xgb"], phase3["lgbm"])
    else:
        winner = "xgb" if "xgb" in phase3 else names[-1]
    if TUNE_ENABLED:
        tuned = _tune(rows, task, winner, feature_columns, blocks)
        if not _score_is_better(task, tuned["mean_primary"], phase3[winner]["mean_primary"]):
            tuned = dict(phase3[winner])
    else:
        tuned = dict(phase3[winner])
        tuned["optuna_trials"] = 0
        tuned["tune_skipped"] = "awaiting_economic_gate"
    gate = _gate_for(task, tuned["primary_scores"], phase3["baseline"]["primary_scores"])
    kept = list(feature_columns)
    ablation: dict[str, Any] = {"ran": False, "dropped": []}
    if gate["passed"]:
        kept, ablation = _ablate(rows, task, winner, tuned["params"], kept, blocks, phase3)
        if _clock_only(kept):
            gate = {**gate, "passed": False, "reason": "clock_only_features"}
            ablation["rejected_clock_only"] = True
        else:
            tuned = _walk_forward(rows, task, winner, kept, tuned["params"], blocks)
            gate = _gate_for(task, tuned["primary_scores"], phase3["baseline"]["primary_scores"])
            if not gate["passed"]:
                kept = list(feature_columns)
                tuned = _walk_forward(rows, task, winner, kept, tuned["params"], blocks)
                gate = _gate_for(
                    task, tuned["primary_scores"], phase3["baseline"]["primary_scores"]
                )
                ablation["reverted_to_full_set"] = True
    final = None
    if gate["passed"]:
        final = _fit_final(rows, task, winner, kept, tuned["params"], blocks)
    return {
        "task": task,
        "winner": winner,
        "phase3": _public_phase(phase3),
        "tuned": _public_walk(tuned),
        "gate4": gate,
        "features": kept,
        "ablation": ablation,
        "bundle": final,
    }


def _task_rows(frame: pd.DataFrame, task: str) -> pd.DataFrame:
    column = TARGET_COLUMN[task]
    values = frame[column]
    if task == "direction":
        mask = values.to_numpy(dtype=np.int64) >= 0
    else:
        mask = np.isfinite(values.to_numpy(dtype=np.float64))
    return frame.loc[mask].reset_index(drop=True)


def _walk_forward(
    rows: pd.DataFrame,
    task: str,
    algorithm: str,
    feature_columns: Sequence[str],
    params: Mapping[str, Any],
    blocks: Mapping[str, Any],
) -> dict[str, Any]:
    scores = []
    overlapping = []
    for fold in blocks["walk_forward"]:
        train = rows.iloc[fold["train"]]
        validation = rows.iloc[fold["validation"]]
        try:
            estimator = _fit_estimator(algorithm, task, train, feature_columns, params)
            prediction = _predict_raw(
                estimator,
                task,
                validation.loc[:, list(feature_columns)].to_numpy(dtype=np.float64),
            )
            primary = _primary_score(task, validation, prediction)
        except (ValueError, RuntimeError):
            scores.append(float("nan"))
            overlapping.append(float("nan"))
            continue
        scores.append(primary)
        overlapping.append(_overlapping_score(task, validation, prediction))
    finite = [score for score in scores if np.isfinite(score)]
    return {
        "algorithm": algorithm,
        "params": dict(params),
        "primary_scores": scores,
        "overlapping_scores": overlapping,
        "mean_primary": float(np.mean(finite)) if finite else float("nan"),
    }


def _tune(
    rows: pd.DataFrame,
    task: str,
    algorithm: str,
    feature_columns: Sequence[str],
    blocks: Mapping[str, Any],
) -> dict[str, Any]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    direction = "maximize" if HIGHER_IS_BETTER[task] else "minimize"

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 80, 180),
            "max_depth": trial.suggest_int("max_depth", 2, 5),
            "learning_rate": trial.suggest_float("learning_rate", 0.03, 0.12, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 10, 40),
            "subsample": trial.suggest_float("subsample", 0.7, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 5.0),
        }
        scored = _walk_forward(rows, task, algorithm, feature_columns, params, blocks)
        if not np.isfinite(scored["mean_primary"]):
            return -1.0 if direction == "maximize" else 1.0
        return float(scored["mean_primary"])

    study = optuna.create_study(
        direction=direction,
        sampler=optuna.samplers.TPESampler(seed=SEED),
    )
    study.optimize(objective, n_trials=OPTUNA_TRIALS, show_progress_bar=False)
    best = dict(TREE_DEFAULTS)
    best.update(study.best_params)
    scored = _walk_forward(rows, task, algorithm, feature_columns, best, blocks)
    scored["optuna_best_value"] = float(study.best_value)
    scored["optuna_trials"] = OPTUNA_TRIALS
    return scored


def _ablate(
    rows: pd.DataFrame,
    task: str,
    algorithm: str,
    params: Mapping[str, Any],
    feature_columns: list[str],
    blocks: Mapping[str, Any],
    phase3: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    full = _walk_forward(rows, task, algorithm, feature_columns, params, blocks)
    higher = HIGHER_IS_BETTER[task]
    dropped = []
    details = []
    for feature in feature_columns:
        reduced_columns = [column for column in feature_columns if column != feature]
        reduced = _walk_forward(rows, task, algorithm, reduced_columns, params, blocks)
        hurts = _worse_on_two_folds(
            full["primary_scores"],
            reduced["primary_scores"],
            higher,
            min_delta=ABLATION_MIN_DELTA[task],
        )
        details.append(
            {
                "feature": feature,
                "hurts": hurts,
                "mean_primary": reduced["mean_primary"],
            }
        )
        if not hurts:
            dropped.append(feature)
    kept = [column for column in feature_columns if column not in dropped]
    if not kept:
        kept = list(feature_columns)
        dropped = []
    return kept, {
        "ran": True,
        "dropped": dropped,
        "details": details,
        "baseline_mean": phase3["baseline"]["mean_primary"],
    }


def _fit_final(
    rows: pd.DataFrame,
    task: str,
    algorithm: str,
    feature_columns: Sequence[str],
    params: Mapping[str, Any],
    blocks: Mapping[str, Any],
) -> dict[str, Any]:
    fit_rows = rows.iloc[blocks["fit"]]
    calibration_rows = rows.iloc[blocks["calibration"]]
    estimator = _fit_estimator(algorithm, task, fit_rows, feature_columns, params)
    raw = _predict_raw(
        estimator,
        task,
        calibration_rows.loc[:, list(feature_columns)].to_numpy(dtype=np.float64),
    )
    target = _target(calibration_rows, task)
    calibrator = None if task == "return" else _fit_calibrator(task, target, raw)
    return {
        "task": task,
        "algorithm": algorithm,
        "features": list(feature_columns),
        "params": dict(params),
        "estimator": estimator,
        "calibrator": calibrator,
    }


def _fit_estimator(
    algorithm: str,
    task: str,
    train: pd.DataFrame,
    feature_columns: Sequence[str],
    params: Mapping[str, Any],
) -> Any:
    features = train.loc[:, list(feature_columns)].to_numpy(dtype=np.float64)
    target = _target(train, task)
    if algorithm == "baseline":
        return _fit_baseline(task, target)
    if task != "return" and np.unique(target).size < 2:
        raise ValueError("training fold has a single class")
    estimator = _make_tree(algorithm, task, params)
    estimator.fit(features, target)
    return estimator


def _fit_baseline(task: str, target: np.ndarray) -> dict[str, Any]:
    if task == "return":
        return {"kind": "baseline", "task": task}
    if task == "direction":
        counts = np.bincount(target.astype(int), minlength=3).astype(np.float64)
        return {"kind": "baseline", "task": task, "proba": counts / counts.sum()}
    rate = float(np.mean(target))
    return {"kind": "baseline", "task": task, "rate": rate}


def _make_tree(algorithm: str, task: str, params: Mapping[str, Any]) -> Any:
    merged = dict(TREE_DEFAULTS)
    merged.update(params)
    if algorithm == "xgb":
        from xgboost import XGBClassifier, XGBRegressor

        common = _tree_kwargs(merged, min_key="min_child_weight")
        common["tree_method"] = "hist"
        common["verbosity"] = 0
        if task == "return":
            return XGBRegressor(objective="reg:squarederror", **common)
        if task == "direction":
            return XGBClassifier(objective="multi:softprob", **common)
        return XGBClassifier(objective="binary:logistic", **common)
    if algorithm == "lgbm":
        return _LightGBMModel(task, merged)
    raise ValueError(f"unknown algorithm {algorithm}")


class _LightGBMModel:
    """Native LightGBM booster.

    The installed LightGBM sklearn wrapper is incompatible with this
    scikit-learn build, so training goes through ``lightgbm.train``.
    """

    def __init__(self, task: str, params: Mapping[str, Any]) -> None:
        self.task = task
        self.params = dict(params)
        self.booster: Any = None

    def fit(self, features: np.ndarray, target: np.ndarray) -> "_LightGBMModel":
        import lightgbm as lgb

        objective = {"direction": "multiclass", "return": "regression"}.get(self.task, "binary")
        settings = {
            "objective": objective,
            "learning_rate": float(self.params["learning_rate"]),
            "max_depth": int(self.params["max_depth"]),
            "min_child_samples": int(self.params["min_child_weight"]),
            "feature_fraction": float(self.params["colsample_bytree"]),
            "bagging_fraction": float(self.params["subsample"]),
            "bagging_freq": 1,
            "lambda_l2": float(self.params["reg_lambda"]),
            "verbosity": -1,
            "seed": SEED,
            "num_threads": 4,
        }
        if self.task == "direction":
            settings["num_class"] = 3
        dataset = lgb.Dataset(features, label=target)
        self.booster = lgb.train(
            settings,
            dataset,
            num_boost_round=int(self.params["n_estimators"]),
        )
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        return np.asarray(self.booster.predict(features), dtype=np.float64).reshape(-1)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        predicted = np.asarray(self.booster.predict(features), dtype=np.float64)
        if self.task == "direction":
            return predicted
        probability = predicted.reshape(-1)
        return np.column_stack([1.0 - probability, probability])


def _tree_kwargs(params: Mapping[str, Any], *, min_key: str) -> dict[str, Any]:
    return {
        "n_estimators": int(params["n_estimators"]),
        "max_depth": int(params["max_depth"]),
        "learning_rate": float(params["learning_rate"]),
        min_key: int(params["min_child_weight"]),
        "subsample": float(params["subsample"]),
        "colsample_bytree": float(params["colsample_bytree"]),
        "reg_lambda": float(params["reg_lambda"]),
        "random_state": SEED,
        "n_jobs": 4,
    }


def _predict_raw(estimator: Any, task: str, features: np.ndarray) -> np.ndarray:
    if isinstance(estimator, dict) and estimator.get("kind") == "baseline":
        n_rows = len(features)
        if task == "return":
            return np.zeros(n_rows, dtype=np.float64)
        if task == "direction":
            return np.tile(estimator["proba"], (n_rows, 1))
        return np.full(n_rows, float(estimator["rate"]), dtype=np.float64)
    if task == "return":
        return np.asarray(estimator.predict(features), dtype=np.float64)
    proba = np.asarray(estimator.predict_proba(features), dtype=np.float64)
    if task == "direction":
        return proba
    return proba[:, 1]


def _primary_score(task: str, validation: pd.DataFrame, prediction: np.ndarray) -> float:
    if task in BARRIER_TASKS:
        breakeven = (
            float(validation["breakeven_precision"].iloc[0])
            if "breakeven_precision" in validation.columns
            else float("nan")
        )
        side = "long" if task == "long_tp" else "short"
        return barrier_expectancy(validation, prediction, side=side, breakeven=breakeven)
    target = _target(validation, task)
    bars = validation["bar_index"].to_numpy(dtype=np.int64)

    def metric(mask: np.ndarray) -> float:
        return _point_score(task, target[mask], prediction[mask])

    return phase_average(bars, metric, horizon_bars=HORIZON_BARS)


def _overlapping_score(task: str, validation: pd.DataFrame, prediction: np.ndarray) -> float:
    return _point_score(task, _target(validation, task), prediction)


def _point_score(task: str, target: np.ndarray, prediction: np.ndarray) -> float:
    if task == "direction":
        return direction_log_loss(target, prediction)
    if task == "return":
        return mean_absolute_error(target, prediction)
    return brier_score(target, prediction)


def _gate_for(
    task: str,
    model_scores: Sequence[float],
    baseline_scores: Sequence[float],
) -> dict[str, Any]:
    """Apply the v2 fold rule. Barrier folds must clear zero expectancy."""
    if task in BARRIER_TASKS:
        zeros = [0.0] * len(model_scores)
        return gate4_passed(model_scores, zeros, higher_is_better=True)
    if task == "return":
        return gate4_passed(
            model_scores,
            baseline_scores,
            higher_is_better=False,
            min_delta=GATE4_MAE_LIFT,
            relative=True,
        )
    return gate4_passed(
        model_scores,
        baseline_scores,
        higher_is_better=False,
        min_delta=GATE4_LOGLOSS_LIFT,
    )


def _clock_only(columns: Sequence[str]) -> bool:
    """True when every remaining column is an hour or weekday term."""
    return bool(columns) and set(columns).issubset(CALENDAR_COLUMNS)


def _target(frame: pd.DataFrame, task: str) -> np.ndarray:
    values = frame[TARGET_COLUMN[task]].to_numpy()
    if task == "direction":
        return values.astype(np.int64)
    return values.astype(np.float64)


def _score_is_better(task: str, candidate: float, reference: float) -> bool:
    if not np.isfinite(candidate):
        return False
    if not np.isfinite(reference):
        return True
    if HIGHER_IS_BETTER[task]:
        return float(candidate) > float(reference)
    return float(candidate) < float(reference)


def _better_tree(task: str, xgb: Mapping[str, Any], lgbm: Mapping[str, Any]) -> str:
    higher = HIGHER_IS_BETTER[task]
    xgb_score = float(xgb["mean_primary"])
    lgbm_score = float(lgbm["mean_primary"])
    if not np.isfinite(lgbm_score):
        return "xgb"
    if not np.isfinite(xgb_score):
        return "lgbm"
    if higher:
        return "lgbm" if lgbm_score > xgb_score else "xgb"
    return "lgbm" if lgbm_score < xgb_score else "xgb"


def _worse_on_two_folds(
    full_scores: Sequence[float],
    reduced_scores: Sequence[float],
    higher_is_better: bool,
    min_delta: float,
) -> bool:
    hurts = 0
    for full, reduced in zip(full_scores, reduced_scores, strict=True):
        if not np.isfinite(full) or not np.isfinite(reduced):
            continue
        if higher_is_better and reduced < full - min_delta:
            hurts += 1
        elif not higher_is_better and reduced > full + min_delta:
            hurts += 1
    return hurts >= 2


def _fit_calibrator(task: str, target: np.ndarray, raw: np.ndarray) -> Any:
    if task == "direction":
        models = []
        for class_id in range(3):
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(raw[:, class_id], (target == class_id).astype(np.float64))
            models.append(iso)
        return models
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw, target.astype(np.float64))
    return iso


def _apply_calibrator(calibrator: Any, raw: np.ndarray, task: str) -> np.ndarray:
    if task == "direction":
        columns = [model.predict(raw[:, index]) for index, model in enumerate(calibrator)]
        adjusted = np.clip(np.column_stack(columns), 1e-6, None)
        return adjusted / adjusted.sum(axis=1, keepdims=True)
    return np.clip(calibrator.predict(raw), 0.0, 1.0)


def _public_phase(phase3: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {name: _public_walk(result) for name, result in phase3.items()}


def _public_walk(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key != "estimator"
    }
