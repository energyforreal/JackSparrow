"""Candlestick previews of confirmed swings and proposal boundaries."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from research.cpr_mtf.candidates import Candidate
from research.cpr_mtf.contract import WINDOW_BARS
from research.cpr_mtf.swings import Swing, swings_on_chart


def save_preview(
    frame: pd.DataFrame,
    swings: list[Swing],
    candidates: list[Candidate],
    asof_index: int,
    timeframe: str,
    path: Path,
) -> list[Swing]:
    """Draw the 192-bar window ending at ``asof_index`` and save a PNG.

    Args:
        frame: OHLCV for ``timeframe``.
        swings: Full swing list. Only confirmed pivots inside the window
            are marked.
        candidates: Proposals for this timeframe at ``asof_index``.
        asof_index: Last bar on the chart.
        timeframe: Title label.
        path: PNG destination.

    Returns:
        The swings that were drawn.

    Raises:
        ValueError: If the window would start before the series.
    """
    if asof_index < WINDOW_BARS - 1:
        raise ValueError("preview requires a full 192-bar window")
    start = asof_index - WINDOW_BARS + 1
    drawn = swings_on_chart(swings, asof_index, start)
    window = frame.iloc[start : asof_index + 1]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(10, 4))
    for offset, row in enumerate(window.itertuples(index=False)):
        color = "#2a9d8f" if float(row.close) >= float(row.open) else "#c44536"
        axis.plot([offset, offset], [row.low, row.high], color=color, linewidth=0.8)
        body_low = min(float(row.open), float(row.close))
        body_high = max(float(row.open), float(row.close))
        axis.plot([offset, offset], [body_low, body_high], color=color, linewidth=2.4)
    for swing in drawn:
        offset = swing.pivot_index - start
        marker = "v" if swing.swing_type == "high" else "^"
        axis.scatter(offset, swing.pivot_price, marker=marker, color="#1d3557", s=18, zorder=3)
    for candidate in candidates:
        if candidate.timeframe != timeframe:
            continue
        _draw_boundary(axis, candidate, start, asof_index)
    axis.set_title(f"{timeframe} as of bar {asof_index}")
    axis.set_xlabel("Bars in the 192-bar window")
    axis.set_ylabel("Price")
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return drawn


def _draw_boundary(
    axis: plt.Axes,
    candidate: Candidate,
    start: int,
    asof_index: int,
) -> None:
    """Draw one proposal's upper and lower lines across the visible span."""
    left = max(candidate.first_pivot_index, start)
    xs = [left - start, asof_index - start]
    for price_at_asof, slope, color in (
        (candidate.upper_price_at_asof, candidate.upper_slope, "#1d3557"),
        (candidate.lower_price_at_asof, candidate.lower_slope, "#457b9d"),
    ):
        y_left = price_at_asof + slope * (left - asof_index)
        y_right = price_at_asof
        axis.plot(xs, [y_left, y_right], color=color, linewidth=1.0)
