"""Figures for the recognition report.

The drawings read the report dict. They do not refit a model and they do
not add a feature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

Figure = Any


def write_recognition_figures(report: Mapping[str, Any], directory: Path) -> list[Path]:
    """Save one PNG per available section of ``report``.

    Args:
        report: Recognition report produced by ``run_colab``.
        directory: Folder that already holds the checkpoint.

    Returns:
        Paths of the figures that had enough data to draw.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, figure in recognition_figures(report):
        path = directory / f"{name}.png"
        figure.savefig(path, dpi=120, bbox_inches="tight")
        _close(figure)
        written.append(path)
    return written


def show_recognition_plots(report: Mapping[str, Any]) -> None:
    """Draw the report figures in the current notebook output."""
    import matplotlib.pyplot as plt

    figures = [figure for _name, figure in recognition_figures(report)]
    if not figures:
        print("report has no rows to plot")
        return
    plt.show()
    for figure in figures:
        _close(figure)


def recognition_figures(report: Mapping[str, Any]) -> list[tuple[str, Figure]]:
    """Build the figures that ``report`` can support.

    Args:
        report: In-memory recognition report.

    Returns:
        ``(file stem, figure)`` pairs. The caller closes each figure.
    """
    import matplotlib.pyplot as plt

    plt.ioff()
    figures: list[tuple[str, Figure]] = []
    learning = _learning_curve(report)
    if learning is not None:
        figures.append(("learning_curve", learning))
    scores = _split_scores(report)
    if scores is not None:
        figures.append(("validation_and_test", scores))
    search = _optuna_trials(report)
    if search is not None:
        figures.append(("optuna_trials", search))
    correlation = _correlation_heatmaps(report)
    if correlation is not None:
        figures.append(("label_correlation", correlation))
    explained = _shap_heatmap(report)
    if explained is not None:
        figures.append(("shap_channels", explained))
    reliability = _calibration(report)
    if reliability is not None:
        figures.append(("calibration", reliability))
    return figures


def _learning_curve(report: Mapping[str, Any]) -> Figure | None:
    """Train and validation loss for the refit that is saved."""
    import matplotlib.pyplot as plt

    fit = report.get("fit")
    if not isinstance(fit, Mapping):
        return None
    train = [float(item) for item in fit.get("train_loss_by_epoch", [])]
    val = [float(item) for item in fit.get("val_loss_by_epoch", [])]
    if not val:
        return None
    epochs = np.arange(1, len(val) + 1)
    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    if len(train) == len(val):
        axis.plot(epochs, train, marker="o", label="train")
    axis.plot(epochs, val, marker="o", label="validation")
    best = int(fit.get("best_epoch", int(np.argmin(val)))) + 1
    axis.axvline(best, color="0.4", linestyle="--", label=f"kept epoch {best}")
    axis.set_xlabel("epoch")
    axis.set_ylabel("loss")
    axis.set_title("Final TCN: train loss and validation loss")
    axis.legend()
    return figure


def _split_scores(report: Mapping[str, Any]) -> Figure | None:
    """Macro-F1 and per-class geometry F1 on validation and the sealed test."""
    import matplotlib.pyplot as plt

    val = report.get("val")
    test = report.get("test")
    if not isinstance(val, Mapping) or not isinstance(test, Mapping):
        return None
    labels, val_macro, test_macro = _macro_trio(val, test)
    if not labels:
        return None
    figure, axes = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)
    positions = np.arange(len(labels))
    width = 0.36
    axes[0].bar(positions - width / 2, val_macro, width, label="validation")
    axes[0].bar(positions + width / 2, test_macro, width, label="sealed test")
    axes[0].set_xticks(positions, labels, rotation=15, ha="right")
    axes[0].set_ylim(0.0, 1.0)
    axes[0].set_ylabel("macro-F1")
    axes[0].set_title("Chosen epoch")
    axes[0].legend()
    _grouped_class_bars(
        axes[1],
        _class_f1(val.get("geometry_per_class")),
        _class_f1(test.get("geometry_per_class")),
    )
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_ylabel("F1")
    axes[1].set_title("Geometry families")
    axes[1].legend()
    figure.suptitle("Validation against the sealed test, scored once")
    return figure


def _optuna_trials(report: Mapping[str, Any]) -> Figure | None:
    """Trial scores from the purged search. Pruned trials stay visible."""
    import matplotlib.pyplot as plt

    study = report.get("optuna")
    if not isinstance(study, Mapping):
        return None
    trials = [row for row in study.get("trials", []) if isinstance(row, Mapping)]
    if not trials:
        return None
    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    best_so_far: list[float] = []
    running: float | None = None
    missing: list[int] = []
    for row in trials:
        number = int(row["number"])
        value = row.get("value")
        completed = str(row.get("state")) == "COMPLETE" and value is not None
        if value is None:
            missing.append(number)
        else:
            color = "C0" if completed else "C1"
            axis.scatter(number, float(value), color=color, zorder=3)
        if completed:
            score = float(value)
            running = score if running is None else max(running, score)
        best_so_far.append(np.nan if running is None else running)
    axis.plot(
        [int(row["number"]) for row in trials],
        best_so_far,
        color="0.2",
        label="best completed",
    )
    if missing:
        floor = axis.get_ylim()[0]
        axis.scatter(missing, [floor] * len(missing), marker="x", color="0.5", zorder=3)
    axis.scatter([], [], color="C0", label="completed")
    axis.scatter([], [], color="C1", label="pruned with a score")
    axis.scatter([], [], marker="x", color="0.5", label="pruned before a score")
    axis.set_xlabel("trial")
    axis.set_ylabel("mean macro-F1")
    axis.set_title("Development search (validation folds only)")
    axis.legend()
    return figure


def _correlation_heatmaps(report: Mapping[str, Any]) -> Figure | None:
    """Spearman of each channel with each recognition label."""
    import matplotlib.pyplot as plt

    block = report.get("correlation")
    if not isinstance(block, Mapping):
        return None
    pairs = [row for row in block.get("pairs", []) if isinstance(row, Mapping)]
    if not pairs:
        return None
    threshold = float(block.get("threshold", 0.5))
    figure, axes = plt.subplots(1, 2, figsize=(16, 6), constrained_layout=True)
    image = None
    for axis, reduction in zip(axes, ("last_bar", "window_mean")):
        channels, labels, grid = _pivot_correlation(pairs, reduction)
        if grid.size == 0:
            axis.set_axis_off()
            continue
        image = axis.imshow(grid, cmap="RdBu_r", vmin=-1.0, vmax=1.0, aspect="auto")
        axis.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
        axis.set_yticks(range(len(channels)), channels)
        axis.set_title(reduction.replace("_", " "))
        _annotate_grid(axis, grid, threshold)
    if image is None:
        _close(figure)
        return None
    figure.colorbar(image, ax=axes, fraction=0.03, label="Spearman")
    figure.suptitle(
        f"Train windows only. A black box marks |Spearman| >= {threshold:.1f}"
    )
    return figure


def _shap_heatmap(report: Mapping[str, Any]) -> Figure | None:
    """Channel importance from TreeSHAP, one column per geometric family."""
    import matplotlib.pyplot as plt

    block = report.get("shap")
    if not isinstance(block, Mapping):
        return None
    per_class = block.get("per_class")
    if not isinstance(per_class, Mapping):
        return None
    classes: list[str] = []
    channels: list[str] = []
    rows: list[list[float]] = []
    for name, item in per_class.items():
        if not isinstance(item, Mapping) or item.get("skipped"):
            continue
        scores = item.get("channels")
        if not isinstance(scores, Mapping):
            continue
        if not channels:
            channels = [str(channel) for channel in scores]
        classes.append(str(name))
        rows.append([float(scores.get(channel, 0.0)) for channel in channels])
    if not rows:
        return None
    grid = np.asarray(rows, dtype=np.float64).T
    order = np.argsort(grid.mean(axis=1))[::-1]
    grid = grid[order]
    channels = [channels[int(index)] for index in order]
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(14, 6),
        constrained_layout=True,
        gridspec_kw={"width_ratios": [2.2, 1.0]},
    )
    image = axes[0].imshow(grid, cmap="YlOrRd", aspect="auto")
    axes[0].set_xticks(range(len(classes)), classes, rotation=45, ha="right")
    axes[0].set_yticks(range(len(channels)), channels)
    axes[0].set_title("By family")
    figure.colorbar(image, ax=axes[0], fraction=0.05, label="mean |SHAP|")
    means = grid.mean(axis=1)
    positions = np.arange(len(channels))
    axes[1].barh(positions, means)
    axes[1].set_yticks(positions, channels)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("mean |SHAP|")
    axes[1].set_title("Across families")
    sample = block.get("sample_size")
    figure.suptitle(f"TreeSHAP on the presence baseline (n={sample})")
    return figure


def _calibration(report: Mapping[str, Any]) -> Figure | None:
    """Reliability of Head A probabilities on the sealed test."""
    import matplotlib.pyplot as plt

    test = report.get("test")
    if not isinstance(test, Mapping):
        return None
    table = test.get("geometry_calibration")
    if not isinstance(table, Mapping):
        return None
    bins = [row for row in table.get("bins", []) if isinstance(row, Mapping)]
    if not bins:
        return None
    confidence = [float(row["confidence"]) for row in bins]
    frequency = [float(row["frequency"]) for row in bins]
    counts = np.asarray([float(row["count"]) for row in bins], dtype=np.float64)
    scale = 40.0 + 400.0 * counts / max(float(counts.max()), 1.0)
    figure, axis = plt.subplots(figsize=(6, 5), constrained_layout=True)
    axis.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color="0.5", label="matches")
    axis.scatter(confidence, frequency, s=scale, label="bin")
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)
    axis.set_xlabel("predicted probability")
    axis.set_ylabel("observed frequency")
    error = float(table.get("expected_calibration_error", 0.0))
    axis.set_title(f"Head A reliability on the sealed test (ECE {error:.3f})")
    axis.legend()
    return figure


def _macro_trio(
    val: Mapping[str, Any],
    test: Mapping[str, Any],
) -> tuple[list[str], list[float], list[float]]:
    """Macro-F1 labels shared by both splits."""
    labels: list[str] = []
    left: list[float] = []
    right: list[float] = []
    pairs = (
        ("geometry", "geometry_macro_f1", None),
        ("market state", "market_state", "macro_f1"),
        ("structure tag", "structure_tag", "macro_f1"),
    )
    for label, key, nested in pairs:
        val_score = _nested_float(val, key, nested)
        test_score = _nested_float(test, key, nested)
        if val_score is None or test_score is None:
            continue
        labels.append(label)
        left.append(val_score)
        right.append(test_score)
    return labels, left, right


def _nested_float(
    block: Mapping[str, Any],
    key: str,
    nested: str | None,
) -> float | None:
    """Read a float, or a float inside one nested mapping."""
    value = block.get(key)
    if nested is None:
        if isinstance(value, (int, float)):
            return float(value)
        return None
    if isinstance(value, Mapping) and isinstance(value.get(nested), (int, float)):
        return float(value[nested])
    return None


def _class_f1(per_class: object) -> list[tuple[str, float]]:
    """F1 for each class that published a score."""
    if not isinstance(per_class, Mapping):
        return []
    rows: list[tuple[str, float]] = []
    for name, scores in per_class.items():
        if isinstance(scores, Mapping) and isinstance(scores.get("f1"), (int, float)):
            rows.append((str(name), float(scores["f1"])))
    return rows


def _grouped_class_bars(
    axis: Any,
    val_rows: Sequence[tuple[str, float]],
    test_rows: Sequence[tuple[str, float]],
) -> None:
    """Side-by-side F1 bars. Classes missing from one split are skipped."""
    test_map = dict(test_rows)
    names = [name for name, _score in val_rows if name in test_map]
    if not names:
        axis.set_axis_off()
        return
    val_map = dict(val_rows)
    positions = np.arange(len(names))
    width = 0.36
    axis.bar(
        positions - width / 2,
        [val_map[name] for name in names],
        width,
        label="validation",
    )
    axis.bar(
        positions + width / 2,
        [test_map[name] for name in names],
        width,
        label="sealed test",
    )
    axis.set_xticks(positions, names, rotation=45, ha="right")


def _pivot_correlation(
    pairs: Sequence[Mapping[str, Any]],
    reduction: str,
) -> tuple[list[str], list[str], np.ndarray]:
    """Channel by label Spearman grid for one reduction."""
    chosen = [row for row in pairs if row.get("reduction") == reduction]
    channels = list(dict.fromkeys(str(row["channel"]) for row in chosen))
    labels = list(dict.fromkeys(str(row["label"]) for row in chosen))
    grid = np.full((len(channels), len(labels)), np.nan, dtype=np.float64)
    channel_index = {name: index for index, name in enumerate(channels)}
    label_index = {name: index for index, name in enumerate(labels)}
    for row in chosen:
        grid[channel_index[str(row["channel"])], label_index[str(row["label"])]] = float(
            row["spearman"]
        )
    return channels, labels, grid


def _annotate_grid(axis: Any, grid: np.ndarray, threshold: float) -> None:
    """Print each correlation and box the pairs past the flag."""
    from matplotlib.patches import Rectangle

    for row in range(grid.shape[0]):
        for col in range(grid.shape[1]):
            value = float(grid[row, col])
            if not np.isfinite(value):
                continue
            axis.text(
                col,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if abs(value) >= 0.65 else "black",
            )
            if abs(value) >= threshold:
                axis.add_patch(
                    Rectangle(
                        (col - 0.5, row - 0.5),
                        1,
                        1,
                        fill=False,
                        edgecolor="black",
                        linewidth=1.2,
                    )
                )


def _close(figure: Figure) -> None:
    """Release a figure without drawing it again."""
    import matplotlib.pyplot as plt

    plt.close(figure)
