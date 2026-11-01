"""Phase-1 trainers: a causal TCN and an XGBoost presence baseline.

Head A is per-bar geometric multi-label. Head E is the window's market state
and structure tag. Direction, chart patterns, formation status, breakouts,
and zone geometry are not trained.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
import torch
from torch import nn
from xgboost import XGBClassifier

logger = structlog.get_logger(__name__)

from research.recognition_15m.contract import (
    GEOMETRIC_CLASSES,
    MARKET_STATES,
    POS_WEIGHT_CLIP,
    SEED,
    STRUCTURE_TAGS,
    TCN_BATCH,
    TCN_DILATIONS,
    TCN_EPOCHS,
    TCN_HIDDEN,
    TCN_KERNEL,
    TCN_LEARNING_RATE,
    XGB_ESTIMATORS,
    XGB_MAX_DEPTH,
)


class CausalConv1d(nn.Module):
    """Convolution that pads on the left, so each step sees only the past."""

    def __init__(self, in_channels: int, out_channels: int, kernel: int, dilation: int) -> None:
        super().__init__()
        self.pad = (kernel - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels,
            out_channels,
            kernel,
            dilation=dilation,
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        """Apply the convolution to ``(n, channels, time)``."""
        padded = nn.functional.pad(values, (self.pad, 0))
        return self.conv(padded)


class RecognitionTCN(nn.Module):
    """Shared causal encoder with geometric and market-state heads."""

    def __init__(
        self,
        in_channels: int,
        n_geometry: int,
        n_states: int,
        n_tags: int,
        hidden: int = TCN_HIDDEN,
        dilations: tuple[int, ...] = TCN_DILATIONS,
    ) -> None:
        super().__init__()
        blocks: list[nn.Module] = []
        channels = in_channels
        for dilation in dilations:
            blocks.append(CausalConv1d(channels, hidden, TCN_KERNEL, int(dilation)))
            blocks.append(nn.ReLU())
            channels = hidden
        self.encoder = nn.Sequential(*blocks)
        self.head_geometry = nn.Conv1d(hidden, n_geometry, kernel_size=1)
        self.head_state = nn.Linear(hidden, n_states)
        self.head_tag = nn.Linear(hidden, n_tags)

    def forward(self, values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Return geometry logits, state logits, and tag logits.

        Args:
            values: ``(n, time, channels)``.

        Returns:
            Geometry logits ``(n, time, classes)`` and two window logits
            taken from the last timestep.
        """
        hidden = self.encoder(values.transpose(1, 2))
        geometry = self.head_geometry(hidden).transpose(1, 2)
        pooled = hidden[:, :, -1]
        return geometry, self.head_state(pooled), self.head_tag(pooled)


def train_tcn(
    train: dict[str, np.ndarray],
    val: dict[str, np.ndarray],
    test: dict[str, np.ndarray] | None = None,
    *,
    epochs: int = TCN_EPOCHS,
    batch_size: int = TCN_BATCH,
    seed: int = SEED,
    hidden: int = TCN_HIDDEN,
    dilations: tuple[int, ...] = TCN_DILATIONS,
    learning_rate: float = TCN_LEARNING_RATE,
    pos_weight_clip: float = POS_WEIGHT_CLIP,
    patience: int | None = None,
    include_test_calibration: bool = False,
) -> dict[str, Any]:
    """Fit Head A and Head E. The epoch is chosen on validation loss.

    Args:
        train: Scaled windows and labels.
        val: Validation windows used only to choose the epoch.
        test: Held-out windows. Scored once after the epoch is chosen.
            Omitted during the development search.
        epochs: Maximum passes over the training windows.
        batch_size: Mini-batch size.
        seed: Torch seed.
        hidden: Encoder width.
        dilations: Causal dilation schedule.
        learning_rate: Step size for AdamW or the clipped SGD fallback.
        pos_weight_clip: Upper bound on the Head A positive-class weight.
        patience: Stop after this many epochs without a lower validation
            loss. ``None`` runs every epoch and still keeps the best one.
        include_test_calibration: When scoring ``test``, add Head A
            reliability bins. This is recognition calibration.

    Returns:
        Metrics for validation and, when provided, test, plus the CPU
        ``state_dict`` of the chosen epoch. ``best_epoch`` is the
        zero-based index of the lowest validation loss.
    """
    torch.manual_seed(seed)
    model = RecognitionTCN(
        in_channels=int(train["features"].shape[-1]),
        n_geometry=len(GEOMETRIC_CLASSES),
        n_states=len(MARKET_STATES),
        n_tags=len(STRUCTURE_TAGS),
        hidden=hidden,
        dilations=dilations,
    )
    optimizer = _adamw(model, learning_rate)
    pos_weight = _as_tensor(_positive_weights(train["geometry"], pos_weight_clip))
    state_weight = _as_tensor(_class_weights(train["state"], len(MARKET_STATES)))
    tag_weight = _as_tensor(_class_weights(train["tag"], len(STRUCTURE_TAGS)))
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    train_history: list[float] = []
    history: list[float] = []
    stale = 0
    for epoch in range(epochs):
        train_loss = _run_epoch(
            model,
            train,
            pos_weight,
            state_weight,
            tag_weight,
            batch_size,
            seed + epoch,
            learning_rate,
            optimizer,
        )
        val_loss = _loss(
            model,
            val,
            pos_weight,
            state_weight,
            tag_weight,
            batch_size,
        )
        train_history.append(train_loss)
        history.append(val_loss)
        logger.info(
            "recognition_epoch",
            epoch=epoch,
            train_loss=train_loss,
            val_loss=val_loss,
        )
        if val_loss < best_loss:
            best_loss = val_loss
            best_epoch = epoch
            stale = 0
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
        else:
            stale += 1
            if patience is not None and stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("TCN training produced no epoch")
    model.load_state_dict(best_state)
    scored_test = None
    if test is not None:
        scored_test = _score(
            model,
            test,
            batch_size,
            include_calibration=include_test_calibration,
        )
    return {
        "val_loss": best_loss,
        "best_epoch": best_epoch,
        "train_loss_by_epoch": train_history,
        "val_loss_by_epoch": history,
        "val": _score(model, val, batch_size),
        "test": scored_test,
        "state_dict": best_state,
        "optimizer": "adamw" if optimizer is not None else "sgd",
    }


def train_presence_baseline(
    train_features: np.ndarray,
    train_geometry: np.ndarray,
    test_features: np.ndarray,
    test_geometry: np.ndarray,
    *,
    seed: int = SEED,
) -> dict[str, Any]:
    """Fit one tree per geometric family on window-level presence.

    Args:
        train_features: ``(n, time, channels)`` training windows.
        train_geometry: Per-bar multi-label targets.
        test_features: Held-out windows.
        test_geometry: Held-out per-bar targets.
        seed: Tree seed.

    Returns:
        Per-class presence metrics. Classes without both outcomes in train
        are recorded as skipped. Spans are not predicted.
    """
    x_train = train_features.reshape(len(train_features), -1)
    x_test = test_features.reshape(len(test_features), -1)
    y_train = (train_geometry.max(axis=1) >= 0.5).astype(np.int64)
    y_test = (test_geometry.max(axis=1) >= 0.5).astype(np.int64)
    per_class: dict[str, Any] = {}
    f1_scores: list[float] = []
    for class_index, name in enumerate(GEOMETRIC_CLASSES):
        labels = y_train[:, class_index]
        positives = int(labels.sum())
        negatives = int(len(labels) - positives)
        if positives == 0 or negatives == 0:
            per_class[name] = {"skipped": True, "support": int(y_test[:, class_index].sum())}
            continue
        model = XGBClassifier(
            n_estimators=XGB_ESTIMATORS,
            max_depth=XGB_MAX_DEPTH,
            learning_rate=0.1,
            objective="binary:logistic",
            eval_metric="logloss",
            scale_pos_weight=float(negatives) / float(positives),
            tree_method="hist",
            n_jobs=1,
            random_state=seed,
        )
        model.fit(x_train, labels)
        scores = model.predict_proba(x_test)[:, 1]
        metrics = binary_scores(y_test[:, class_index], scores)
        metrics["skipped"] = False
        per_class[name] = metrics
        if metrics["support"] > 0:
            f1_scores.append(metrics["f1"])
    macro = float(np.mean(f1_scores)) if f1_scores else 0.0
    return {"per_class": per_class, "macro_f1": macro}


def binary_scores(
    y_true: np.ndarray,
    y_score: np.ndarray,
    threshold: float = 0.5,
) -> dict[str, float]:
    """Precision, recall, and F1 for one binary label."""
    pred = y_score >= threshold
    true = y_true.astype(bool)
    true_positive = int(np.logical_and(pred, true).sum())
    false_positive = int(np.logical_and(pred, ~true).sum())
    false_negative = int(np.logical_and(~pred, true).sum())
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "support": float(true.sum()),
    }


def multiclass_scores(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    names: tuple[str, ...],
) -> dict[str, Any]:
    """Macro-F1 over classes that appear in ``y_true``, plus per-class recall."""
    per_class: dict[str, dict[str, float]] = {}
    f1_scores: list[float] = []
    for class_index, name in enumerate(names):
        true = y_true == class_index
        pred = y_pred == class_index
        true_positive = int(np.logical_and(pred, true).sum())
        false_positive = int(np.logical_and(pred, ~true).sum())
        false_negative = int(np.logical_and(~pred, true).sum())
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        score = _f1(precision, recall)
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": score,
            "support": float(true.sum()),
        }
        if int(true.sum()) > 0:
            f1_scores.append(score)
    macro = float(np.mean(f1_scores)) if f1_scores else 0.0
    return {"macro_f1": macro, "per_class": per_class}


def _positive_weights(geometry: np.ndarray, clip: float = POS_WEIGHT_CLIP) -> np.ndarray:
    """Positive-class weights for binary cross-entropy, clipped."""
    rates = geometry.reshape(-1, geometry.shape[-1]).mean(axis=0)
    rates = np.clip(rates, 1e-4, 1.0 - 1e-4)
    weights = (1.0 - rates) / rates
    return np.clip(weights, 1.0, clip).astype(np.float32)


def _class_weights(labels: np.ndarray, n_classes: int) -> np.ndarray:
    """Inverse-frequency weights. Missing classes receive weight zero."""
    counts = np.bincount(labels.astype(np.int64), minlength=n_classes).astype(np.float64)
    weights = np.zeros(n_classes, dtype=np.float32)
    present = counts > 0.0
    if present.any():
        weights[present] = counts.sum() / (float(present.sum()) * counts[present])
    return weights


def _run_epoch(
    model: RecognitionTCN,
    batch: dict[str, np.ndarray],
    pos_weight: torch.Tensor,
    state_weight: torch.Tensor,
    tag_weight: torch.Tensor,
    batch_size: int,
    seed: int,
    learning_rate: float,
    optimizer: torch.optim.Optimizer | None,
) -> float:
    """One shuffled pass over the training split.

    Returns:
        Mean training loss for the pass, weighted by batch size.
    """
    model.train()
    order = np.arange(len(batch["features"]))
    rng = np.random.default_rng(seed)
    rng.shuffle(order)
    total = 0.0
    count = 0
    for start in range(0, len(order), batch_size):
        chosen = order[start : start + batch_size]
        if optimizer is not None:
            optimizer.zero_grad(set_to_none=True)
        else:
            model.zero_grad(set_to_none=True)
        loss = _batch_loss(
            model,
            batch,
            chosen,
            pos_weight,
            state_weight,
            tag_weight,
        )
        loss.backward()
        if optimizer is None:
            _sgd_step(model, learning_rate)
        else:
            optimizer.step()
        total += float(loss.detach().cpu()) * len(chosen)
        count += len(chosen)
    if count == 0:
        return float("inf")
    return total / count


def _loss(
    model: RecognitionTCN,
    batch: dict[str, np.ndarray],
    pos_weight: torch.Tensor,
    state_weight: torch.Tensor,
    tag_weight: torch.Tensor,
    batch_size: int,
) -> float:
    """Mean loss over ``batch`` without updating weights."""
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(batch["features"]), batch_size):
            chosen = np.arange(start, min(start + batch_size, len(batch["features"])))
            loss = _batch_loss(
                model,
                batch,
                chosen,
                pos_weight,
                state_weight,
                tag_weight,
            )
            total += float(loss.detach().cpu()) * len(chosen)
            count += len(chosen)
    if count == 0:
        return float("inf")
    return total / count


def _batch_loss(
    model: RecognitionTCN,
    batch: dict[str, np.ndarray],
    chosen: np.ndarray,
    pos_weight: torch.Tensor,
    state_weight: torch.Tensor,
    tag_weight: torch.Tensor,
) -> torch.Tensor:
    """Sum of Head A and Head E losses. Task weights stay at one."""
    features = _as_tensor(batch["features"][chosen].astype(np.float32))
    geometry = _as_tensor(batch["geometry"][chosen].astype(np.float32))
    state = _as_tensor(batch["state"][chosen].astype(np.int64))
    tag = _as_tensor(batch["tag"][chosen].astype(np.int64))
    geometry_logits, state_logits, tag_logits = model(features)
    geometry_loss = nn.functional.binary_cross_entropy_with_logits(
        geometry_logits,
        geometry,
        pos_weight=pos_weight,
    )
    state_loss = nn.functional.cross_entropy(state_logits, state, weight=state_weight)
    tag_loss = nn.functional.cross_entropy(tag_logits, tag, weight=tag_weight)
    return geometry_loss + state_loss + tag_loss


def _score(
    model: RecognitionTCN,
    batch: dict[str, np.ndarray],
    batch_size: int = TCN_BATCH,
    *,
    include_calibration: bool = False,
) -> dict[str, Any]:
    """Recognition metrics on one split."""
    model.eval()
    geometry_scores = []
    state_pred = []
    tag_pred = []
    with torch.no_grad():
        for start in range(0, len(batch["features"]), batch_size):
            chosen = np.arange(start, min(start + batch_size, len(batch["features"])))
            features = _as_tensor(batch["features"][chosen].astype(np.float32))
            geometry_logits, state_logits, tag_logits = model(features)
            geometry_scores.append(_to_numpy(torch.sigmoid(geometry_logits)))
            state_pred.append(_to_numpy(torch.argmax(state_logits, dim=1)).astype(np.int64))
            tag_pred.append(_to_numpy(torch.argmax(tag_logits, dim=1)).astype(np.int64))
    geometry = np.concatenate(geometry_scores, axis=0)
    true_geometry = batch["geometry"].reshape(-1, geometry.shape[-1])
    pred_geometry = geometry.reshape(-1, geometry.shape[-1])
    per_class = {
        name: binary_scores(true_geometry[:, index], pred_geometry[:, index])
        for index, name in enumerate(GEOMETRIC_CLASSES)
    }
    present = [scores["f1"] for scores in per_class.values() if scores["support"] > 0.0]
    macro = float(np.mean(present)) if present else 0.0
    scored: dict[str, Any] = {
        "geometry_macro_f1": macro,
        "geometry_per_class": per_class,
        "market_state": multiclass_scores(
            batch["state"],
            np.concatenate(state_pred),
            MARKET_STATES,
        ),
        "structure_tag": multiclass_scores(
            batch["tag"],
            np.concatenate(tag_pred),
            STRUCTURE_TAGS,
        ),
    }
    if include_calibration:
        scored["geometry_calibration"] = calibration_table(true_geometry, pred_geometry)
    return scored


def calibration_table(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Expected calibration error for recognition probabilities.

    Args:
        y_true: Binary labels, any shape.
        y_prob: Probabilities aligned with ``y_true``.
        n_bins: Equal-width bins on ``[0, 1]``.

    Returns:
        The error and a reliability table. This is not a trading metric.
    """
    true = np.asarray(y_true, dtype=np.float64).reshape(-1)
    prob = np.asarray(y_prob, dtype=np.float64).reshape(-1)
    if true.shape != prob.shape:
        raise ValueError("calibration labels and probabilities differ in shape")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows: list[dict[str, float]] = []
    error = 0.0
    total = max(len(true), 1)
    for index in range(n_bins):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        if index == n_bins - 1:
            mask = (prob >= lower) & (prob <= upper)
        else:
            mask = (prob >= lower) & (prob < upper)
        count = int(mask.sum())
        if count == 0:
            continue
        confidence = float(prob[mask].mean())
        frequency = float(true[mask].mean())
        error += (count / total) * abs(frequency - confidence)
        rows.append(
            {
                "lower": lower,
                "upper": upper,
                "count": float(count),
                "confidence": confidence,
                "frequency": frequency,
            }
        )
    return {"expected_calibration_error": float(error), "bins": rows}


def _adamw(model: nn.Module, learning_rate: float) -> torch.optim.Optimizer | None:
    """Build AdamW, or return None when this torch install cannot."""
    try:
        return torch.optim.AdamW(model.parameters(), lr=learning_rate)
    except Exception:
        logger.info("recognition_optimizer_fallback", optimizer="sgd")
        return None


def _as_tensor(values: np.ndarray) -> torch.Tensor:
    """Copy a NumPy array into a tensor without the NumPy bridge.

    The installed torch build was compiled against NumPy 1.x and cannot infer
    dtypes from NumPy 2 arrays. The byte copy keeps training on this machine.
    """
    array = np.ascontiguousarray(values)
    if array.dtype == np.float64:
        array = np.ascontiguousarray(array.astype(np.float32))
    if array.dtype == np.float32:
        dtype = torch.float32
    elif array.dtype == np.int64:
        dtype = torch.int64
    else:
        raise TypeError(f"unsupported array dtype: {array.dtype}")
    raw = bytearray(array.tobytes())
    return torch.frombuffer(raw, dtype=dtype).reshape(array.shape).clone()


def _to_numpy(values: torch.Tensor) -> np.ndarray:
    """Copy a CPU tensor to NumPy via a Python list."""
    detached = values.detach().cpu()
    return np.asarray(detached.reshape(-1).tolist(), dtype=np.float64).reshape(detached.shape)


def _sgd_step(model: nn.Module, learning_rate: float) -> None:
    """Gradient step with norm clipping. Avoids ``torch.optim`` on this install."""
    squared = None
    for parameter in model.parameters():
        if parameter.grad is None:
            continue
        term = parameter.grad.detach().pow(2).sum()
        squared = term if squared is None else squared + term
    if squared is None:
        return
    scale = max(1.0, float(squared.sqrt()))
    with torch.no_grad():
        for parameter in model.parameters():
            if parameter.grad is None:
                continue
            parameter -= learning_rate * (parameter.grad / scale)
            parameter.grad = None


def _ratio(numerator: int, denominator: int) -> float:
    """Zero when the denominator is zero."""
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean. Zero when both inputs are zero."""
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)
