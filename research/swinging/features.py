"""Causal feature snapshots shared by training and inference.

``snapshot_features`` builds the frame on bars at or before the as-of index.
Later bars are not passed to the engines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from feature_store.feature_registry import (
    CANDLESTICK_FEATURES,
    CHART_PATTERN_FEATURES,
    FEATURE_LIST,
    MTF_CONTEXT_FEATURES,
)
from feature_store.pattern_features.candlestick_patterns import CandlestickPatternEngine
from feature_store.pattern_features.chart_patterns import ChartPatternEngine
from feature_store.transformer_btcusd.contract import NATIVE_STRUCTURE_COLS
from feature_store.transformer_btcusd.structure import add_market_structure_features
from feature_store.unified_feature_engine import UnifiedFeatureEngine
from research.cpr_mtf.features import causal_atr
from research.cpr_mtf.swings import detect_swings
from research.swinging.contract import (
    BAR_MINUTES,
    COLAB_DATA_ROOT,
    FORBIDDEN_FEATURE_COLUMNS,
    RESOLUTIONS,
    SWING_COLUMNS,
    SYMBOL,
)
from research.swinging.quality import normalize_ohlcv

_ATR_PERIOD = 14


def snapshot_columns() -> tuple[str, ...]:
    """Return the feature names a snapshot always contains.

    Returns:
        Stable column order. Outcome columns are not included.
    """
    ordered: list[str] = []
    for name in (
        *FEATURE_LIST,
        *CANDLESTICK_FEATURES,
        *CHART_PATTERN_FEATURES,
        *MTF_CONTEXT_FEATURES,
        *NATIVE_STRUCTURE_COLS,
        *SWING_COLUMNS,
    ):
        if name in FORBIDDEN_FEATURE_COLUMNS or name in ordered:
            continue
        ordered.append(name)
    return tuple(ordered)


def _finite(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return number


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    work = normalize_ohlcv(frame)
    if work.empty:
        raise ValueError("feature frame is empty")
    work["timestamp"] = pd.to_datetime(work["time"], utc=True)
    return work


def _swing_frame(work: pd.DataFrame, resolution: str) -> pd.DataFrame:
    high = work["high"].to_numpy(dtype=np.float64)
    low = work["low"].to_numpy(dtype=np.float64)
    close = work["close"].to_numpy(dtype=np.float64)
    atr = causal_atr(high, low, close, _ATR_PERIOD)
    swings = detect_swings(work, resolution, atr)
    count = len(work)
    high_dist = np.zeros(count, dtype=np.float64)
    low_dist = np.zeros(count, dtype=np.float64)
    bars_high = np.full(count, -1.0, dtype=np.float64)
    bars_low = np.full(count, -1.0, dtype=np.float64)
    pending: dict[int, list[Any]] = {}
    for swing in swings:
        pending.setdefault(int(swing.confirmation_index), []).append(swing)
    last_high = None
    last_low = None
    for index in range(count):
        for swing in pending.get(index, []):
            if swing.swing_type == "high":
                last_high = swing
            else:
                last_low = swing
        scale = atr[index]
        if not np.isfinite(scale) or scale <= 0.0:
            scale = max(abs(float(close[index])) * 0.01, 1e-9)
        if last_high is not None:
            high_dist[index] = (float(close[index]) - float(last_high.pivot_price)) / scale
            bars_high[index] = float(index - int(last_high.confirmation_index))
        if last_low is not None:
            low_dist[index] = (float(close[index]) - float(last_low.pivot_price)) / scale
            bars_low[index] = float(index - int(last_low.confirmation_index))
    return pd.DataFrame(
        {
            "swing_high_dist_atr": high_dist,
            "swing_low_dist_atr": low_dist,
            "bars_since_swing_high": bars_high,
            "bars_since_swing_low": bars_low,
        }
    )


def build_feature_frame(frame: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Compute swinging features for every row of ``frame``.

    The engines see only this frame. Callers that need a causal row pass the
    prefix that ends at the prediction bar.

    Args:
        frame: OHLCV candles.
        resolution: Bar size. Selects the unified-engine minute scale.

    Returns:
        Feature rows in ``snapshot_columns`` order, plus ``time`` and ``close``.

    Raises:
        ValueError: If the resolution is unknown or the frame is empty.
        RuntimeError: If a forbidden future column is present.
    """
    if resolution not in BAR_MINUTES:
        raise ValueError(f"unknown resolution: {resolution}")
    work = _prepare_ohlcv(frame)
    minutes = BAR_MINUTES[resolution]
    base = UnifiedFeatureEngine().compute_batch(
        work,
        resolution_minutes=minutes,
        include_pattern_features=False,
        include_mtf_context=True,
        fill_invalid=True,
    )
    candles = CandlestickPatternEngine().compute_all(work)
    charts = ChartPatternEngine().compute_all(work)
    structured = add_market_structure_features(work.drop(columns=["timestamp"], errors="ignore"))
    structure_cols = [name for name in NATIVE_STRUCTURE_COLS if name in structured.columns]
    pieces = [
        base.reset_index(drop=True),
        candles.reset_index(drop=True),
        charts.reset_index(drop=True),
        structured.loc[:, structure_cols].reset_index(drop=True),
        _swing_frame(work, resolution),
    ]
    featured = pd.concat(pieces, axis=1)
    featured = featured.loc[:, ~featured.columns.duplicated()]
    columns = snapshot_columns()
    for name in columns:
        if name not in featured.columns:
            featured[name] = 0.0
    featured = featured.loc[:, list(columns)]
    leaked = set(featured.columns) & FORBIDDEN_FEATURE_COLUMNS
    if leaked:
        raise RuntimeError(f"feature frame contains future columns: {sorted(leaked)}")
    featured.insert(0, "time", work["time"].to_numpy())
    featured.insert(1, "close", work["close"].to_numpy())
    return featured.replace([np.inf, -np.inf], 0.0).fillna(0.0)


def snapshot_features(frame: pd.DataFrame, asof_index: int, resolution: str) -> dict[str, float]:
    """Return the feature row known at ``asof_index``.

    Args:
        frame: Full OHLCV series. Rows after ``asof_index`` are discarded
            before any engine runs.
        asof_index: Signal bar. Must be inside ``frame``.
        resolution: Bar size.

    Returns:
        Finite feature values in ``snapshot_columns`` order.

    Raises:
        ValueError: If the index is outside the frame.
    """
    if asof_index < 0 or asof_index >= len(frame):
        raise ValueError(f"as-of index {asof_index} is outside the series")
    featured = build_feature_frame(frame.iloc[: asof_index + 1], resolution)
    row = featured.iloc[-1]
    return {name: _finite(row[name]) for name in snapshot_columns()}


def materialize_features(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = RESOLUTIONS,
) -> dict[str, str]:
    """Write a feature parquet next to each stored OHLCV file.

    Args:
        root: Local dataset root.
        symbol: Instrument directory name.
        resolutions: Resolutions that already have ``ohlcv.parquet``.

    Returns:
        Map of resolution to the feature parquet path.
    """
    written: dict[str, str] = {}
    for resolution in resolutions:
        source = Path(root) / symbol / resolution / "ohlcv.parquet"
        if not source.is_file():
            continue
        featured = build_feature_frame(pd.read_parquet(source), resolution)
        destination = source.with_name("features.parquet")
        featured.to_parquet(destination, index=False)
        written[resolution] = str(destination)
    return written
