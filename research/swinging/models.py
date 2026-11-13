"""XGBoost and LightGBM fits tuned only on the development span.

The sealed tail from ``chronological_bounds`` is never passed to Optuna or to
``fit``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from research.swinging.contract import COLAB_DATA_ROOT, RESOLUTIONS, SYMBOL
from research.swinging.features import snapshot_columns
from research.swinging.regime import attach_regime_targets
from research.swinging.splits import chronological_bounds

_SEED = 7


class LabelledClassifier:
    """Fit a tree classifier on stable integer ids and expose the class names.

    XGBoost's multiclass objective expects integer labels. The names stay on
    ``classes_`` so scoring code can read them.
    """

    def __init__(self, model: Any, classes: list[str]) -> None:
        self.model = model
        self.classes_ = np.asarray(list(classes))

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "LabelledClassifier":
        """Fit on string or integer labels.

        Args:
            features: Training matrix.
            labels: Class names. Every name must be in ``classes_``.

        Returns:
            This wrapper.
        """
        mapping = {str(name): index for index, name in enumerate(self.classes_)}
        encoded = np.asarray([mapping[str(label)] for label in labels], dtype=np.int32)
        self.model.fit(features, encoded)
        return self

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Return class probabilities in ``classes_`` order.

        Args:
            features: Rows to score.

        Returns:
            Probability matrix.
        """
        return self.model.predict_proba(features)


def _class_names(labels: np.ndarray) -> list[str]:
    return sorted({str(label) for label in labels})


def _xy(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    target: str,
) -> tuple[np.ndarray, np.ndarray]:
    matrix = frame.loc[:, list(feature_columns)].apply(pd.to_numeric, errors="coerce")
    matrix = matrix.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    labels = frame[target].to_numpy()
    return matrix.to_numpy(dtype=np.float64), labels


def development_slice(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Return rows before the sealed test and the sealed start index.

    Args:
        frame: Chronological frame.

    Returns:
        Development rows and the first sealed index.
    """
    _, _, sealed = chronological_bounds(len(frame))
    return frame.iloc[:sealed].reset_index(drop=True), sealed


def _estimator(algorithm: str, task: str, params: dict[str, Any]) -> Any:
    depth = int(params.get("max_depth", 3))
    trees = int(params.get("n_estimators", 40))
    rate = float(params.get("learning_rate", 0.1))
    if algorithm == "xgboost":
        if task == "classifier":
            from xgboost import XGBClassifier

            return XGBClassifier(
                max_depth=depth,
                n_estimators=trees,
                learning_rate=rate,
                objective="multi:softprob",
                eval_metric="mlogloss",
                verbosity=0,
                random_state=_SEED,
            )
        from xgboost import XGBRegressor

        return XGBRegressor(
            max_depth=depth,
            n_estimators=trees,
            learning_rate=rate,
            objective="reg:squarederror",
            verbosity=0,
            random_state=_SEED,
        )
    if algorithm != "lightgbm":
        raise ValueError(f"unknown algorithm: {algorithm}")
    return _NativeLightGBM(task, depth, trees, rate)


class _NativeLightGBM:
    """LightGBM booster trained without the sklearn wrapper.

    The installed LightGBM sklearn classes pass ``force_all_finite`` into
    scikit-learn, which this environment no longer accepts. ``lightgbm.train``
    is the same path the forecast package uses.
    """

    def __init__(self, task: str, depth: int, trees: int, rate: float) -> None:
        self.task = task
        self.depth = depth
        self.trees = trees
        self.rate = rate
        self.booster: Any = None
        self.num_class = 1

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "_NativeLightGBM":
        """Train one booster.

        Args:
            features: Training matrix.
            labels: Integer class ids or numeric targets.

        Returns:
            This booster.
        """
        import lightgbm as lgb

        settings: dict[str, Any] = {
            "learning_rate": self.rate,
            "max_depth": self.depth,
            "verbosity": -1,
            "seed": _SEED,
            "num_threads": 1,
        }
        if self.task == "classifier":
            encoded = np.asarray(labels, dtype=np.int32)
            self.num_class = int(encoded.max()) + 1
            settings["objective"] = "multiclass"
            settings["num_class"] = self.num_class
            settings["metric"] = "multi_logloss"
            dataset = lgb.Dataset(np.asarray(features, dtype=np.float64), label=encoded)
        else:
            settings["objective"] = "regression"
            dataset = lgb.Dataset(
                np.asarray(features, dtype=np.float64),
                label=np.asarray(labels, dtype=np.float64),
            )
        self.booster = lgb.train(settings, dataset, num_boost_round=self.trees)
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Return numeric predictions.

        Args:
            features: Rows to score.

        Returns:
            One prediction per row.
        """
        return np.asarray(self.booster.predict(features), dtype=np.float64).reshape(-1)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Return class probabilities in class-id order.

        Args:
            features: Rows to score.

        Returns:
            Probability matrix with one column per class.
        """
        predicted = np.asarray(self.booster.predict(features), dtype=np.float64)
        if predicted.ndim == 1:
            predicted = predicted.reshape(-1, self.num_class)
        return predicted


def _validation_loss(model: Any, features: np.ndarray, target: np.ndarray, task: str) -> float:
    if len(features) == 0:
        return 1.0
    if task == "classifier":
        from sklearn.metrics import log_loss

        probabilities = model.predict_proba(features)
        labels = [str(label) for label in model.classes_]
        return float(log_loss(target, probabilities, labels=labels))
    predictions = model.predict(features)
    return float(np.mean((predictions - target.astype(float)) ** 2))


def tune_hyperparameters(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    target: str,
    *,
    algorithm: str,
    task: str,
    n_trials: int = 10,
    storage: str | None = None,
    study_name: str = "swinging",
) -> dict[str, Any]:
    """Search hyperparameters on the development train and validation blocks.

    Args:
        frame: Chronological rows. The sealed tail is removed before search.
        feature_columns: Model inputs.
        target: Column to predict.
        algorithm: ``xgboost`` or ``lightgbm``.
        task: ``classifier`` or ``regressor``.
        n_trials: Optuna trials.
        storage: Optional Optuna storage URL. ``None`` keeps the study in memory.
        study_name: Study name when ``storage`` is set.

    Returns:
        Best parameter dictionary and the sealed start index that was excluded.

    Raises:
        ValueError: If the development span cannot be split.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    development, sealed = development_slice(frame)
    train_end, validation_end, _ = chronological_bounds(len(development))
    features, labels = _xy(development, feature_columns, target)
    if task == "regressor":
        labels = labels.astype(np.float64)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 2, 4),
            "learning_rate": trial.suggest_float("learning_rate", 0.05, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 8, 30),
        }
        if task == "classifier":
            model = LabelledClassifier(_estimator(algorithm, task, params), _class_names(labels))
        else:
            model = _estimator(algorithm, task, params)
        model.fit(features[:train_end], labels[:train_end])
        return _validation_loss(
            model,
            features[train_end:validation_end],
            labels[train_end:validation_end],
            task,
        )

    study = optuna.create_study(
        direction="minimize",
        study_name=study_name,
        storage=storage,
        load_if_exists=storage is not None,
    )
    study.optimize(objective, n_trials=int(n_trials))
    best = dict(study.best_params)
    best["sealed_start"] = int(sealed)
    best["development_rows"] = int(len(development))
    return best


def fit_estimator(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    target: str,
    *,
    algorithm: str,
    task: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """Fit on the development span and ignore the sealed tail.

    Args:
        frame: Chronological rows.
        feature_columns: Model inputs.
        target: Column to predict.
        algorithm: ``xgboost`` or ``lightgbm``.
        task: ``classifier`` or ``regressor``.
        params: Optional fixed parameters. Optuna keys besides the three
            tree parameters are ignored.

    Returns:
        A fitted estimator.
    """
    development, _ = development_slice(frame)
    features, labels = _xy(development, feature_columns, target)
    if task == "regressor":
        labels = labels.astype(np.float64)
    if task == "classifier":
        model = LabelledClassifier(_estimator(algorithm, task, params or {}), _class_names(labels))
    else:
        model = _estimator(algorithm, task, params or {})
    model.fit(features, labels)
    return model


def _calibrate_win(
    classifier: Any,
    features: np.ndarray,
    labels: np.ndarray,
    train_end: int,
    validation_end: int,
) -> Any | None:
    from sklearn.isotonic import IsotonicRegression

    if "win" not in [str(label) for label in classifier.classes_]:
        return None
    validation_features = features[train_end:validation_end]
    validation_labels = labels[train_end:validation_end]
    if len(validation_features) < 2:
        return None
    probabilities = classifier.predict_proba(validation_features)
    classes = [str(label) for label in classifier.classes_]
    win_probability = probabilities[:, classes.index("win")]
    observed = (validation_labels.astype(str) == "win").astype(float)
    if len(np.unique(observed)) < 2:
        return None
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(win_probability, observed)
    return calibrator


def fit_bundle(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    target: str,
    positive_class: str | None,
    n_trials: int = 0,
    storage: str | None = None,
    study_name: str = "swinging",
) -> dict[str, Any]:
    """Fit the classifier and, when the target is numeric, skip it.

    The exported classifier and regressor are the algorithms with the lower
    validation loss. Search runs only when ``n_trials`` is positive.

    Args:
        frame: Chronological supervised rows.
        feature_columns: Model inputs.
        target: Classification target column.
        positive_class: Class name treated as the event, or ``None``.
        n_trials: Optuna trials per algorithm. Zero uses fixed small trees.
        storage: Optional Optuna storage URL.
        study_name: Study prefix.

    Returns:
        Artifact dictionary with ``classifier``, optional ``regressor``, and
        ``calibrator``.
    """
    params: dict[str, dict[str, Any]] = {}
    for algorithm in ("xgboost", "lightgbm"):
        if n_trials > 0:
            params[algorithm] = tune_hyperparameters(
                frame,
                feature_columns,
                target,
                algorithm=algorithm,
                task="classifier",
                n_trials=n_trials,
                storage=storage,
                study_name=f"{study_name}-{algorithm}-clf",
            )
        else:
            params[algorithm] = {"max_depth": 3, "n_estimators": 20, "learning_rate": 0.1}
    development, sealed = development_slice(frame)
    features, labels = _xy(development, feature_columns, target)
    train_end, validation_end, _ = chronological_bounds(len(development))
    fitted = {
        name: LabelledClassifier(_estimator(name, "classifier", params[name]), _class_names(labels))
        for name in ("xgboost", "lightgbm")
    }
    losses = {}
    for name, model in fitted.items():
        model.fit(features[:train_end], labels[:train_end])
        losses[name] = _validation_loss(
            model,
            features[train_end:validation_end],
            labels[train_end:validation_end],
            "classifier",
        )
    best_name = min(losses, key=losses.get)
    calibrator = _calibrate_win(fitted[best_name], features, labels, train_end, validation_end)
    classifier = LabelledClassifier(
        _estimator(best_name, "classifier", params[best_name]),
        _class_names(labels),
    )
    classifier.fit(features, labels)
    artifact: dict[str, Any] = {
        "classifier": classifier,
        "classifier_algorithm": best_name,
        "classifier_validation_loss": losses[best_name],
        "feature_columns": list(feature_columns),
        "target": target,
        "positive_class": positive_class,
        "sealed_start": int(sealed),
        "development_rows": int(len(development)),
        "calibrator": calibrator,
        "regressor": None,
        "regressor_algorithm": None,
    }
    return artifact


def fit_regressor_bundle(
    artifact: dict[str, Any],
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    target: str,
    *,
    n_trials: int = 0,
    storage: str | None = None,
    study_name: str = "swinging-reg",
) -> dict[str, Any]:
    """Attach the better of an XGBoost and a LightGBM regressor.

    Args:
        artifact: Classifier artifact to update.
        frame: Chronological rows containing ``target``.
        feature_columns: Model inputs.
        target: Numeric column.
        n_trials: Optuna trials per algorithm.
        storage: Optional Optuna storage URL.
        study_name: Study prefix.

    Returns:
        The same artifact with ``regressor`` set.
    """
    params: dict[str, dict[str, Any]] = {}
    for algorithm in ("xgboost", "lightgbm"):
        if n_trials > 0:
            params[algorithm] = tune_hyperparameters(
                frame,
                feature_columns,
                target,
                algorithm=algorithm,
                task="regressor",
                n_trials=n_trials,
                storage=storage,
                study_name=f"{study_name}-{algorithm}",
            )
        else:
            params[algorithm] = {"max_depth": 3, "n_estimators": 20, "learning_rate": 0.1}
    development, _ = development_slice(frame)
    features, labels = _xy(development, feature_columns, target)
    labels = labels.astype(np.float64)
    train_end, validation_end, _ = chronological_bounds(len(development))
    losses = {}
    for name in ("xgboost", "lightgbm"):
        model = _estimator(name, "regressor", params[name])
        model.fit(features[:train_end], labels[:train_end])
        losses[name] = _validation_loss(
            model,
            features[train_end:validation_end],
            labels[train_end:validation_end],
            "regressor",
        )
    best_name = min(losses, key=losses.get)
    regressor = _estimator(best_name, "regressor", params[best_name])
    regressor.fit(features, labels)
    artifact["regressor"] = regressor
    artifact["regressor_algorithm"] = best_name
    artifact["regressor_validation_loss"] = losses[best_name]
    artifact["regressor_target"] = target
    return artifact


def score_features(artifact: dict[str, Any], values: np.ndarray) -> dict[str, Any]:
    """Score one or more feature rows with a fitted artifact.

    Args:
        artifact: Dictionary produced by ``fit_bundle``.
        values: Array shaped ``(rows, features)``.

    Returns:
        Win or positive-class probability, class probabilities, and expected
        net return when a regressor is present.
    """
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    classifier = artifact["classifier"]
    probabilities = classifier.predict_proba(matrix)
    classes = [str(label) for label in classifier.classes_]
    positive = artifact.get("positive_class")
    if positive in classes:
        event = probabilities[:, classes.index(positive)]
    else:
        event = probabilities.max(axis=1)
    calibrator = artifact.get("calibrator")
    if calibrator is not None and positive == "win":
        event = np.asarray(calibrator.predict(event), dtype=float)
    expected = np.zeros(len(matrix), dtype=float)
    if artifact.get("regressor") is not None:
        expected = np.asarray(artifact["regressor"].predict(matrix), dtype=float)
    return {
        "event_probability": event,
        "class_probabilities": [
            {name: float(probability) for name, probability in zip(classes, row)}
            for row in probabilities
        ],
        "expected_net_return": expected,
    }


def class_from_outcome(label: object) -> str:
    """Map a trade outcome onto win, loss, or other.

    Args:
        label: Simulator label.

    Returns:
        Classifier class name.
    """
    text = str(label)
    if text == "win":
        return "win"
    if text == "loss":
        return "loss"
    return "other"


def sr_class(setup_type: object, outcome: object) -> str | None:
    """Map a support or breakout setup onto an effectiveness class.

    Args:
        setup_type: Engine A setup type.
        outcome: Simulator label.

    Returns:
        An S/R class, or ``None`` when the row is not an S/R example.
    """
    kind = str(setup_type)
    result = str(outcome)
    if kind == "support_bounce" and result == "win":
        return "bounce"
    if kind == "resistance_rejection" and result == "win":
        return "rejection"
    if kind in ("long_breakout", "short_breakdown", "breakout_retest") and result == "win":
        return "breakout"
    if kind in (
        "support_bounce",
        "resistance_rejection",
        "long_breakout",
        "short_breakdown",
        "breakout_retest",
    ) and result == "loss":
        return "failed_breakout"
    return None


def _load_outcomes(root: Path, symbol: str, resolutions: Sequence[str]) -> pd.DataFrame:
    frames = []
    for resolution in resolutions:
        path = root / symbol / resolution / "outcomes.parquet"
        if path.is_file():
            frame = pd.read_parquet(path)
            frame["timeframe"] = resolution
            frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no outcomes parquet under {root}")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("signal_timestamp").reset_index(drop=True)
    return combined


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    return [name for name in snapshot_columns() if name in frame.columns]


def _supervised(frame: pd.DataFrame) -> pd.DataFrame:
    if "simulated" in frame.columns:
        frame = frame.loc[frame["simulated"].fillna(False).astype(bool)]
    frame = frame.loc[frame["outcome_label"].notna()].copy()
    frame["outcome_class"] = frame["outcome_label"].map(class_from_outcome)
    return frame.reset_index(drop=True)


def train_setup_effectiveness(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = RESOLUTIONS,
    n_trials: int = 8,
    storage: str | None = None,
) -> dict[str, Any]:
    """Train setup win/loss/other and net-return models.

    Args:
        root: Local dataset root.
        symbol: Instrument.
        resolutions: Outcome files to stack, in time order per file.
        n_trials: Optuna trials. Zero skips search.
        storage: Optional Optuna storage URL under the Colab disk.

    Returns:
        Fitted artifact. Also written to ``experiments/setup_effectiveness``.
    """
    frame = _supervised(_load_outcomes(Path(root), symbol, resolutions))
    columns = _feature_columns(frame)
    artifact = fit_bundle(
        frame,
        columns,
        target="outcome_class",
        positive_class="win",
        n_trials=n_trials,
        storage=storage,
        study_name="setup-effectiveness",
    )
    artifact["task"] = "setup_effectiveness"
    for extra in ("net_return", "mfe", "mae"):
        if extra in frame.columns and extra == "net_return":
            fit_regressor_bundle(
                artifact,
                frame,
                columns,
                extra,
                n_trials=n_trials,
                storage=storage,
                study_name="setup-return",
            )
    _write_experiment(Path(root), "setup_effectiveness", artifact)
    return artifact


def train_sr_effectiveness(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = RESOLUTIONS,
    n_trials: int = 8,
    storage: str | None = None,
) -> dict[str, Any]:
    """Train support, resistance, and breakout effectiveness models.

    Args:
        root: Local dataset root.
        symbol: Instrument.
        resolutions: Outcome files to stack.
        n_trials: Optuna trials.
        storage: Optional Optuna storage URL.

    Returns:
        Fitted artifact.
    """
    frame = _supervised(_load_outcomes(Path(root), symbol, resolutions))
    frame["sr_class"] = [
        sr_class(kind, outcome)
        for kind, outcome in zip(frame["setup_type"], frame["outcome_label"])
    ]
    frame = frame.loc[frame["sr_class"].notna()].reset_index(drop=True)
    if frame.empty:
        raise ValueError("no support or breakout rows to train")
    columns = _feature_columns(frame)
    artifact = fit_bundle(
        frame,
        columns,
        target="sr_class",
        positive_class=None,
        n_trials=n_trials,
        storage=storage,
        study_name="sr-effectiveness",
    )
    artifact["task"] = "sr_effectiveness"
    if "net_return" in frame.columns:
        fit_regressor_bundle(
            artifact,
            frame,
            columns,
            "net_return",
            n_trials=n_trials,
            storage=storage,
            study_name="sr-return",
        )
    _write_experiment(Path(root), "sr_effectiveness", artifact)
    return artifact


def train_regime_model(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = ("1h",),
    n_trials: int = 8,
    storage: str | None = None,
) -> dict[str, Any]:
    """Train a regime classifier. The label is not one of the inputs.

    Args:
        root: Local dataset root.
        symbol: Instrument.
        resolutions: Feature parquets to stack. Defaults to 1-hour bars.
        n_trials: Optuna trials.
        storage: Optional Optuna storage URL.

    Returns:
        Fitted artifact.
    """
    frames = []
    for resolution in resolutions:
        path = Path(root) / symbol / resolution / "features.parquet"
        if path.is_file():
            frames.append(pd.read_parquet(path))
    if not frames:
        raise FileNotFoundError(f"no features parquet under {root}")
    featured = attach_regime_targets(pd.concat(frames, ignore_index=True))
    columns = [name for name in _feature_columns(featured) if name != "regime_target"]
    artifact = fit_bundle(
        featured,
        columns,
        target="regime_target",
        positive_class=None,
        n_trials=n_trials,
        storage=storage,
        study_name="regime",
    )
    artifact["task"] = "regime"
    _write_experiment(Path(root), "regime", artifact)
    return artifact


def _write_experiment(root: Path, name: str, artifact: dict[str, Any]) -> Path:
    import joblib

    destination = root / "experiments" / name
    destination.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, destination / "models.joblib")
    return destination
