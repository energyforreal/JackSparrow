"""Deterministic setup candidates, including rejects and neutrals.

Chart-pattern rows reuse CPR proposals. A proposal's future breakout status
is not copied onto the feature snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.cpr_mtf.candidates import generate_candidates
from research.cpr_mtf.features import causal_atr
from research.cpr_mtf.swings import detect_swings
from research.swinging.contract import (
    ACCEPT_SCORE,
    BREAKOUT_LOOKBACK,
    COLAB_DATA_ROOT,
    NEUTRAL_STRIDE,
    REJECT_SCORE,
    RESOLUTIONS,
    SETUP_META_COLUMNS,
    SYMBOL,
    WARMUP_BARS,
)
from feature_store.pattern_features.chart_patterns import ChartPatternEngine
from research.swinging.features import aligned_snapshot, build_feature_frame, snapshot_columns
from research.swinging.quality import normalize_ohlcv


def _stamp(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _row(
    *,
    resolution: str,
    index: int,
    timestamp: object,
    setup_type: str,
    direction: str,
    score: float,
    reasoning: str,
    invalidation: str,
    status: str,
    features: dict[str, float],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "setup_id": f"{resolution}:{setup_type}:{index}:{direction}",
        "signal_timestamp": _stamp(timestamp),
        "bar_index": int(index),
        "direction": direction,
        "setup_type": setup_type,
        "timeframe": resolution,
        "algorithmic_score": float(score),
        "reasoning": reasoning,
        "invalidation": invalidation,
        "status": status,
    }
    record.update(features)
    return record


def screen_indices(
    frame: pd.DataFrame,
    *,
    warmup: int = WARMUP_BARS,
    neutral_stride: int = NEUTRAL_STRIDE,
    lookback: int = BREAKOUT_LOOKBACK,
) -> list[int]:
    """Choose bars worth a causal snapshot.

    Args:
        frame: OHLCV series.
        warmup: First usable bar.
        neutral_stride: Keep a neutral sample on this stride.
        lookback: Window for a close through the prior high or low.

    Returns:
        Increasing bar indexes.
    """
    work = normalize_ohlcv(frame)
    high = work["high"].to_numpy(dtype=float)
    low = work["low"].to_numpy(dtype=float)
    close = work["close"].to_numpy(dtype=float)
    opened = work["open"].to_numpy(dtype=float)
    chosen: set[int] = set()
    start = max(warmup, lookback)
    for index in range(start, len(work)):
        prior_high = float(np.max(high[index - lookback : index]))
        prior_low = float(np.min(low[index - lookback : index]))
        span = float(high[index] - low[index])
        body = abs(float(close[index] - opened[index]))
        if close[index] > prior_high or close[index] < prior_low:
            chosen.add(index)
        if span > 0.0 and body / span <= 0.35:
            chosen.add(index)
        if neutral_stride > 0 and (index - start) % neutral_stride == 0:
            chosen.add(index)
    return sorted(chosen)


def _status(score: float, direction: str) -> str:
    if direction == "neutral" or score <= 0.0:
        return "neutral"
    if score < REJECT_SCORE:
        return "rejected"
    if score < ACCEPT_SCORE:
        return "rejected"
    return "accepted"


def _level_setups(
    work: pd.DataFrame,
    index: int,
    resolution: str,
    features: dict[str, float],
) -> list[dict[str, Any]]:
    lookback = BREAKOUT_LOOKBACK
    window = work.iloc[index - lookback : index]
    close = float(work["close"].iloc[index])
    opened = float(work["open"].iloc[index])
    volume = float(work["volume"].iloc[index])
    average_volume = float(window["volume"].mean()) if len(window) else volume
    prior_high = float(window["high"].max())
    prior_low = float(window["low"].min())
    atr = float(features.get("atr_14") or 0.0)
    if atr <= 0.0:
        atr = max(abs(close) * 0.01, 1e-9)
    volume_boost = 0.15 if average_volume > 0.0 and volume >= average_volume else 0.0
    rows: list[dict[str, Any]] = []
    stamp = work["time"].iloc[index]
    if close > prior_high:
        distance = (close - prior_high) / atr
        score = float(np.clip(0.45 + 0.25 * distance + volume_boost, 0.0, 1.0))
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="long_breakout",
                direction="long",
                score=score,
                reasoning="close traded through the prior lookback high",
                invalidation="close back below the broken high",
                status=_status(score, "long"),
                features=features,
            )
        )
    if close < prior_low:
        distance = (prior_low - close) / atr
        score = float(np.clip(0.45 + 0.25 * distance + volume_boost, 0.0, 1.0))
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="short_breakdown",
                direction="short",
                score=score,
                reasoning="close traded through the prior lookback low",
                invalidation="close back above the broken low",
                status=_status(score, "short"),
                features=features,
            )
        )
    near_low = abs(close - prior_low) <= 0.35 * atr and close >= opened
    near_high = abs(close - prior_high) <= 0.35 * atr and close <= opened
    if near_low and close <= prior_high:
        score = 0.6 if close > prior_low else 0.3
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="support_bounce",
                direction="long",
                score=score,
                reasoning="close held the lookback low and finished above the open",
                invalidation="close through the lookback low",
                status=_status(score, "long"),
                features=features,
            )
        )
    if near_high and close >= prior_low:
        score = 0.6 if close < prior_high else 0.3
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="resistance_rejection",
                direction="short",
                score=score,
                reasoning="close stalled at the lookback high and finished below the open",
                invalidation="close through the lookback high",
                status=_status(score, "short"),
                features=features,
            )
        )
    return rows


def _pattern_setups(
    work: pd.DataFrame,
    index: int,
    resolution: str,
    features: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stamp = work["time"].iloc[index]
    bull = float(features.get("cdl_bull_score") or 0.0)
    bear = float(features.get("cdl_bear_score") or 0.0)
    if bull > 0.0 or bear > 0.0:
        direction = "long" if bull >= bear else "short"
        score = float(np.clip(max(bull, bear), 0.0, 1.0))
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="candlestick",
                direction=direction,
                score=score,
                reasoning="candlestick engine score on the closed bar",
                invalidation="pattern high or low broken on the next bar",
                status=_status(score, direction),
                features=features,
            )
        )
    net = float(features.get("cdl_net_score") or 0.0)
    if abs(net) >= 0.5:
        direction = "long" if net > 0.0 else "short"
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="reversal",
                direction=direction,
                score=float(np.clip(abs(net), 0.0, 1.0)),
                reasoning="net candlestick score points against the prior close",
                invalidation="signal bar extreme broken",
                status=_status(abs(net), direction),
                features=features,
            )
        )
    adx = float(features.get("adx_14") or 0.0)
    ema_distance = float(features.get("price_vs_ema21_atr") or 0.0)
    if adx >= 22.0 and abs(ema_distance) > 0.0:
        direction = "long" if ema_distance > 0.0 else "short"
        score = float(np.clip(0.4 + adx / 100.0, 0.0, 1.0))
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="trend_continuation",
                direction=direction,
                score=score,
                reasoning="ADX and EMA distance agree on the closed bar",
                invalidation="ADX falls below the trend threshold",
                status=_status(score, direction),
                features=features,
            )
        )
    chart_score = max(float(features.get(name) or 0.0) for name in (
        "chp_bull_flag",
        "chp_bear_flag",
        "chp_double_top",
        "chp_double_bottom",
        "chp_hs_detected",
        "chp_ihs_detected",
    ))
    if chart_score > 0.0:
        direction = "short" if float(features.get("chp_bear_flag") or 0.0) >= chart_score else "long"
        if float(features.get("chp_double_top") or 0.0) >= chart_score or float(
            features.get("chp_hs_detected") or 0.0
        ) >= chart_score:
            direction = "short"
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=stamp,
                setup_type="chart_pattern",
                direction=direction,
                score=float(np.clip(chart_score, 0.0, 1.0)),
                reasoning="chart-pattern engine flag on the closed prefix",
                invalidation="pattern boundary broken the wrong way",
                status=_status(chart_score, direction),
                features=features,
            )
        )
    return rows


def _retests(
    work: pd.DataFrame,
    index: int,
    resolution: str,
    features: dict[str, float],
) -> list[dict[str, Any]]:
    if index < BREAKOUT_LOOKBACK + 3:
        return []
    close = work["close"].to_numpy(dtype=float)
    high = work["high"].to_numpy(dtype=float)
    low = work["low"].to_numpy(dtype=float)
    atr = float(features.get("atr_14") or 0.0)
    if atr <= 0.0:
        atr = max(abs(float(close[index])) * 0.01, 1e-9)
    rows: list[dict[str, Any]] = []
    for previous in range(index - 5, index):
        if previous < BREAKOUT_LOOKBACK:
            continue
        prior_high = float(np.max(high[previous - BREAKOUT_LOOKBACK : previous]))
        prior_low = float(np.min(low[previous - BREAKOUT_LOOKBACK : previous]))
        if close[previous] > prior_high and abs(close[index] - prior_high) <= 0.35 * atr:
            score = 0.62
            rows.append(
                _row(
                    resolution=resolution,
                    index=index,
                    timestamp=work["time"].iloc[index],
                    setup_type="breakout_retest",
                    direction="long",
                    score=score,
                    reasoning="price returned to a high broken within five bars",
                    invalidation="close back below the retested high",
                    status=_status(score, "long"),
                    features=features,
                )
            )
            break
        if close[previous] < prior_low and abs(close[index] - prior_low) <= 0.35 * atr:
            score = 0.62
            rows.append(
                _row(
                    resolution=resolution,
                    index=index,
                    timestamp=work["time"].iloc[index],
                    setup_type="breakout_retest",
                    direction="short",
                    score=score,
                    reasoning="price returned to a low broken within five bars",
                    invalidation="close back above the retested low",
                    status=_status(score, "short"),
                    features=features,
                )
            )
            break
    return rows


def _cpr_setups(
    work: pd.DataFrame,
    index: int,
    resolution: str,
    features: dict[str, float],
) -> list[dict[str, Any]]:
    if resolution not in ("15m", "1h", "4h"):
        return []
    prefix = work.iloc[: index + 1].reset_index(drop=True)
    atr = causal_atr(
        prefix["high"].to_numpy(dtype=float),
        prefix["low"].to_numpy(dtype=float),
        prefix["close"].to_numpy(dtype=float),
        14,
    )
    prefix = prefix.copy()
    prefix["atr"] = atr
    swings = detect_swings(prefix, resolution, atr)
    proposals = generate_candidates(prefix, swings, resolution, len(prefix) - 1)
    rows: list[dict[str, Any]] = []
    for proposal in proposals:
        direction = {"bullish": "long", "bearish": "short"}.get(proposal.direction, "neutral")
        score = float(np.clip(proposal.rule_score, 0.0, 1.0))
        rows.append(
            _row(
                resolution=resolution,
                index=index,
                timestamp=work["time"].iloc[index],
                setup_type="chart_pattern",
                direction=direction,
                score=score,
                reasoning=f"cpr proposal {proposal.pattern}",
                invalidation="proposal boundary broken before confirmation",
                status=_status(score, direction),
                features=features,
            )
        )
    return rows


def generate_setups(
    frame: pd.DataFrame,
    resolution: str,
    *,
    warmup: int = WARMUP_BARS,
    neutral_stride: int = NEUTRAL_STRIDE,
    indexes: list[int] | None = None,
) -> pd.DataFrame:
    """Generate setup rows for one OHLCV frame.

    Args:
        frame: OHLCV candles.
        resolution: Bar size.
        warmup: First bar that may emit a setup.
        neutral_stride: Sampling stride for bars that are not price events.
        indexes: Optional explicit bar list. Skips the screen when provided.

    Returns:
        One row per candidate. Feature columns follow ``snapshot_columns``.
        Failed screens are stored as ``rejected`` or ``neutral``.
    """
    work = normalize_ohlcv(frame)
    chosen = indexes if indexes is not None else screen_indices(
        work,
        warmup=warmup,
        neutral_stride=neutral_stride,
    )
    records: list[dict[str, Any]] = []
    usable = [index for index in chosen if 0 <= index < len(work)]
    featured = build_feature_frame(work, resolution) if usable else None
    chart_engine = ChartPatternEngine()
    for index in usable:
        features = aligned_snapshot(work, featured, index, chart_engine)
        found = []
        found.extend(_level_setups(work, index, resolution, features))
        found.extend(_retests(work, index, resolution, features))
        found.extend(_pattern_setups(work, index, resolution, features))
        found.extend(_cpr_setups(work, index, resolution, features))
        if not found:
            records.append(
                _row(
                    resolution=resolution,
                    index=index,
                    timestamp=work["time"].iloc[index],
                    setup_type="candlestick",
                    direction="neutral",
                    score=0.0,
                    reasoning="no directional rule fired on this bar",
                    invalidation="not a trade candidate",
                    status="neutral",
                    features=features,
                )
            )
        else:
            records.extend(found)
    columns = list(SETUP_META_COLUMNS) + list(snapshot_columns())
    if not records:
        return pd.DataFrame(columns=columns)
    frame_out = pd.DataFrame.from_records(records)
    frame_out = frame_out.loc[:, columns]
    frame_out["setup_id"] = [
        f"{setup_id}:{position}"
        for position, setup_id in enumerate(frame_out["setup_id"].tolist())
    ]
    return frame_out


def materialize_setups(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = RESOLUTIONS,
    neutral_stride: int = NEUTRAL_STRIDE,
) -> dict[str, str]:
    """Write setup parquet files next to stored OHLCV.

    Args:
        root: Local dataset root.
        symbol: Instrument.
        resolutions: Resolutions to scan.
        neutral_stride: Neutral sampling stride.

    Returns:
        Map of resolution to the setup parquet path.
    """
    written: dict[str, str] = {}
    for resolution in resolutions:
        source = Path(root) / symbol / resolution / "ohlcv.parquet"
        if not source.is_file():
            continue
        setups = generate_setups(
            pd.read_parquet(source),
            resolution,
            neutral_stride=neutral_stride,
        )
        destination = source.with_name("setups.parquet")
        setups.to_parquet(destination, index=False)
        written[resolution] = str(destination)
    return written
