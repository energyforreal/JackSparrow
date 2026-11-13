"""Chart-candidate proposals from confirmed swings.

Proposal type and the geometric rule score stay on the proposal record.
They are not columns of the sequence tensor or the geometry vector.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import numpy as np
import pandas as pd

from research.cpr_mtf.contract import (
    CONVERGENCE_SLOPE_ATR,
    CUP_DEPTH_ATR,
    FLAG_RETRACE_MAX,
    HANDLE_RETRACE_MAX,
    HANDLE_RETRACE_MIN,
    HEAD_PROMINENCE_ATR,
    IMPULSE_ATR_MIN,
    MAX_CANDIDATES,
    MAX_CANDIDATES_PER_TIMEFRAME,
    MAX_PER_FAMILY,
    MIN_CUP_SIDE_BARS,
    MIN_PATTERN_DEPTH_ATR,
    MIN_SEPARATION_BARS,
    MODEL_CANDIDATE_FEATURES,
    PAIR_LIMIT,
    PARALLEL_SLOPE_ATR,
    SIMILAR_PRICE_ATR,
    SLOPE_FLAT_ATR,
    TIMEFRAMES,
    TIMEFRAME_ID,
    TOUCH_TOL_ATR,
    WINDOW_BARS,
)
from research.cpr_mtf.swings import Swing

_EPS = 1e-9
_BOUNDARY_DIRECTION = {
    "ascending_triangle": "bullish",
    "descending_triangle": "bearish",
    "symmetrical_triangle": "neutral",
    "rising_wedge": "bullish",
    "falling_wedge": "bearish",
    "ascending_channel": "bullish",
    "descending_channel": "bearish",
    "rectangle": "neutral",
    "broadening": "neutral",
}


@dataclass
class Candidate:
    """One geometric proposal at a single as-of bar.

    Attributes:
        candidate_id: Stable id from timeframe, class, and confirmation times.
        timeframe: Native timeframe.
        pattern: Proposed shape class.
        direction: Structural proposal direction, not an annotation.
        rule_score: Preliminary geometric score in ``[0, 1]``.
        geometry_kind: ``swing`` or ``rounded_proxy``.
        swing_confirmation_indices: Constituent confirmation bars.
        first_confirmation_index: Earliest constituent confirmation.
        last_confirmation_index: Latest constituent confirmation.
        first_pivot_index: Earliest constituent pivot.
        last_pivot_index: Latest constituent pivot.
        upper_price_at_asof: Upper boundary price at the as-of bar.
        lower_price_at_asof: Lower boundary price at the as-of bar.
        upper_slope: Upper boundary in price per bar.
        lower_slope: Lower boundary in price per bar.
        atr: ATR at the as-of bar.
        origin_close: Close at the as-of bar, the price origin.
        start_time: Timestamp of the earliest constituent pivot.
        asof_time: Timestamp of the as-of bar.
        features: Geometry vector in ``MODEL_CANDIDATE_FEATURES`` order.
    """

    candidate_id: str
    timeframe: str
    pattern: str
    direction: str
    rule_score: float
    geometry_kind: str
    swing_confirmation_indices: tuple[int, ...]
    first_confirmation_index: int
    last_confirmation_index: int
    first_pivot_index: int
    last_pivot_index: int
    upper_price_at_asof: float
    lower_price_at_asof: float
    upper_slope: float
    lower_slope: float
    atr: float
    origin_close: float
    start_time: pd.Timestamp
    asof_time: pd.Timestamp
    features: np.ndarray


def generate_candidates(
    frame: pd.DataFrame,
    swings: Sequence[Swing],
    timeframe: str,
    asof_index: int,
) -> list[Candidate]:
    """Propose chart formations visible at ``asof_index``.

    Args:
        frame: Feature frame for ``timeframe``, position-aligned to ``swings``.
        swings: Swings detected on ``frame``.
        timeframe: Timeframe of the series.
        asof_index: Last bar the generator may use.

    Returns:
        Deduplicated proposals after the per-family and per-timeframe caps.

    Raises:
        ValueError: If ``asof_index`` is outside ``frame``.
    """
    if asof_index < 0 or asof_index >= len(frame):
        raise ValueError(f"as-of index {asof_index} is outside the series")
    atr = _asof_atr(frame, asof_index)
    visible = _visible_in_window(swings, asof_index)
    found: list[Candidate] = []
    found.extend(_doubles(visible, frame, timeframe, asof_index, atr))
    found.extend(_triples(visible, frame, timeframe, asof_index, atr))
    found.extend(_head_and_shoulders(visible, frame, timeframe, asof_index, atr))
    found.extend(_impulse_patterns(visible, frame, timeframe, asof_index, atr))
    found.extend(_boundary_pattern(visible, frame, timeframe, asof_index, atr))
    found.extend(_cups(visible, frame, timeframe, asof_index, atr))
    return apply_quota(deduplicate_candidates(found))


def deduplicate_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Keep the higher rule score for each candidate id.

    Args:
        candidates: Proposals that may repeat the same confirmation span.

    Returns:
        One proposal per candidate id.
    """
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.candidate_id)
        if current is None or candidate.rule_score > current.rule_score:
            best[candidate.candidate_id] = candidate
    return list(best.values())


def apply_quota(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Keep at most two proposals per family and twelve per call.

    Args:
        candidates: Proposals for a single timeframe.

    Returns:
        Proposals ordered by descending rule score.
    """
    ordered = sorted(candidates, key=lambda item: (-item.rule_score, item.candidate_id))
    kept: list[Candidate] = []
    counts: dict[str, int] = {}
    for candidate in ordered:
        if counts.get(candidate.pattern, 0) >= MAX_PER_FAMILY:
            continue
        if len(kept) >= MAX_CANDIDATES_PER_TIMEFRAME:
            break
        counts[candidate.pattern] = counts.get(candidate.pattern, 0) + 1
        kept.append(candidate)
    return kept


def stack_candidates(
    by_timeframe: dict[str, Sequence[Candidate]],
) -> tuple[np.ndarray, np.ndarray, list[Candidate]]:
    """Pad proposals to 36 rows in timeframe order.

    Args:
        by_timeframe: Proposals keyed by ``15m``, ``1h``, and ``4h``.

    Returns:
        Geometry array ``(36, 22)``, validity mask ``(36,)``, and the
        unpadded proposals in the same order as the mask's positive rows.
    """
    ordered: list[Candidate] = []
    for timeframe in TIMEFRAMES:
        ordered.extend(by_timeframe.get(timeframe, []))
    ordered = ordered[:MAX_CANDIDATES]
    width = len(MODEL_CANDIDATE_FEATURES)
    array = np.zeros((MAX_CANDIDATES, width), dtype=np.float64)
    mask = np.zeros(MAX_CANDIDATES, dtype=np.float64)
    for index, candidate in enumerate(ordered):
        array[index] = candidate.features
        mask[index] = 1.0
    return array, mask, ordered


def proposal_record(candidate: Candidate) -> dict[str, object]:
    """Return proposal metadata that is excluded from the geometry vector.

    Args:
        candidate: One proposal.

    Returns:
        JSON-ready metadata, including the rule score and proposed type.
    """
    atr = max(candidate.atr, _EPS)
    return {
        "candidate_id": candidate.candidate_id,
        "timeframe": candidate.timeframe,
        "candidate_type_proposal": candidate.pattern,
        "proposed_direction": candidate.direction,
        "candidate_quality_rule_score": candidate.rule_score,
        "geometry_kind": candidate.geometry_kind,
        "swing_confirmation_indices": list(candidate.swing_confirmation_indices),
        "upper_price": candidate.upper_price_at_asof,
        "lower_price": candidate.lower_price_at_asof,
        "upper_slope_price_per_bar": candidate.upper_slope,
        "lower_slope_price_per_bar": candidate.lower_slope,
        "origin_close": candidate.origin_close,
        "upper_boundary_atr": (candidate.upper_price_at_asof - candidate.origin_close) / atr,
        "lower_boundary_atr": (candidate.lower_price_at_asof - candidate.origin_close) / atr,
    }


def propose_pairs(candidates: Sequence[Candidate]) -> list[dict[str, object]]:
    """List cross-timeframe pairs, overlaps first, capped at 32.

    Args:
        candidates: Proposals from one or more timeframes.

    Returns:
        Pair rows with an empty ``relationship`` field. Same-timeframe
        pairs are omitted.
    """
    overlaps: list[dict[str, object]] = []
    negatives: list[dict[str, object]] = []
    for left, right in combinations(candidates, 2):
        if left.timeframe == right.timeframe:
            continue
        lower, higher = _timeframe_order(left, right)
        price_overlap = _ranges_overlap(_price_span(lower), _price_span(higher))
        time_overlap = _ranges_overlap(
            (lower.start_time, lower.asof_time),
            (higher.start_time, higher.asof_time),
        )
        row = {
            "lower_timeframe": lower.timeframe,
            "higher_timeframe": higher.timeframe,
            "left_id": lower.candidate_id,
            "right_id": higher.candidate_id,
            "price_overlap": price_overlap,
            "time_overlap": time_overlap,
            "relationship": "",
        }
        if price_overlap and time_overlap:
            overlaps.append(row)
        else:
            negatives.append(row)
    return (overlaps + negatives)[:PAIR_LIMIT]


def _doubles(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    highs = [swing for swing in visible if swing.swing_type == "high"]
    lows = [swing for swing in visible if swing.swing_type == "low"]
    found = _paired_extremes(highs, lows, "bearish", frame, timeframe, asof_index, atr, 2)
    found.extend(
        _paired_extremes(lows, highs, "bullish", frame, timeframe, asof_index, atr, 2)
    )
    return found


def _triples(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    highs = [swing for swing in visible if swing.swing_type == "high"]
    lows = [swing for swing in visible if swing.swing_type == "low"]
    found = _paired_extremes(highs, lows, "bearish", frame, timeframe, asof_index, atr, 3)
    found.extend(
        _paired_extremes(lows, highs, "bullish", frame, timeframe, asof_index, atr, 3)
    )
    return found


def _paired_extremes(
    extremes: Sequence[Swing],
    opposites: Sequence[Swing],
    direction: str,
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
    count: int,
) -> list[Candidate]:
    """Build double or triple proposals from consecutive same-side swings."""
    found: list[Candidate] = []
    if len(extremes) < count:
        return found
    pattern = "double" if count == 2 else "triple"
    for start in range(len(extremes) - count + 1):
        group = list(extremes[start : start + count])
        prices = [swing.pivot_price for swing in group]
        gap = max(prices) - min(prices)
        if gap > SIMILAR_PRICE_ATR * atr:
            continue
        if group[-1].pivot_index - group[0].pivot_index < MIN_SEPARATION_BARS:
            continue
        between: list[Swing] = []
        valid = True
        for left, right in zip(group, group[1:]):
            mids = [
                swing
                for swing in opposites
                if left.pivot_index < swing.pivot_index < right.pivot_index
            ]
            if not mids:
                valid = False
                break
            if direction == "bearish":
                between.append(min(mids, key=lambda swing: swing.pivot_price))
            else:
                between.append(max(mids, key=lambda swing: swing.pivot_price))
        if not valid:
            continue
        if direction == "bearish":
            depth = min(prices) - max(swing.pivot_price for swing in between)
        else:
            depth = min(swing.pivot_price for swing in between) - max(prices)
        if depth < MIN_PATTERN_DEPTH_ATR * atr:
            continue
        upper_slope, upper_at, lower_slope, lower_at = _extreme_lines(
            group, between, direction, asof_index
        )
        used = tuple(group + between)
        impulse = abs(upper_at - lower_at) / max(atr, _EPS)
        found.append(
            _assemble(
                frame,
                timeframe,
                pattern,
                direction,
                used,
                asof_index,
                atr,
                upper_slope,
                lower_slope,
                upper_at,
                lower_at,
                impulse,
                depth / max(abs(upper_at - lower_at), _EPS),
                "swing",
                gap,
            )
        )
    return found


def _extreme_lines(
    extremes: Sequence[Swing],
    between: Sequence[Swing],
    direction: str,
    asof_index: int,
) -> tuple[float, float, float, float]:
    """Return upper slope, upper price, lower slope, and lower price."""
    extreme_slope, extreme_intercept = _fit_line(
        [(swing.pivot_index, swing.pivot_price) for swing in extremes]
    )
    other_slope, other_intercept = _fit_line(
        [(swing.pivot_index, swing.pivot_price) for swing in between]
    )
    extreme_at = extreme_intercept + extreme_slope * asof_index
    other_at = other_intercept + other_slope * asof_index
    if direction == "bearish":
        return extreme_slope, extreme_at, other_slope, other_at
    return other_slope, other_at, extreme_slope, extreme_at


def _head_and_shoulders(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    found: list[Candidate] = []
    for index in range(len(visible) - 4):
        group = list(visible[index : index + 5])
        kinds = [swing.swing_type for swing in group]
        if kinds == ["high", "low", "high", "low", "high"]:
            candidate = _shoulder_candidate(
                group, "bearish", frame, timeframe, asof_index, atr
            )
        elif kinds == ["low", "high", "low", "high", "low"]:
            candidate = _shoulder_candidate(
                group, "bullish", frame, timeframe, asof_index, atr
            )
        else:
            candidate = None
        if candidate is not None:
            found.append(candidate)
    return found


def _shoulder_candidate(
    group: list[Swing],
    direction: str,
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> Candidate | None:
    left, first_mid, head, second_mid, right = group
    if direction == "bearish":
        prominence = head.pivot_price - max(left.pivot_price, right.pivot_price)
        above = min(left.pivot_price, right.pivot_price) - max(
            first_mid.pivot_price, second_mid.pivot_price
        )
    else:
        prominence = min(left.pivot_price, right.pivot_price) - head.pivot_price
        above = min(first_mid.pivot_price, second_mid.pivot_price) - max(
            left.pivot_price, right.pivot_price
        )
    gap = abs(left.pivot_price - right.pivot_price)
    if prominence < HEAD_PROMINENCE_ATR * atr or above <= 0.0 or gap > SIMILAR_PRICE_ATR * atr:
        return None
    if direction == "bearish":
        upper_points = [
            (left.pivot_index, left.pivot_price),
            (right.pivot_index, right.pivot_price),
        ]
        lower_points = [
            (first_mid.pivot_index, first_mid.pivot_price),
            (second_mid.pivot_index, second_mid.pivot_price),
        ]
    else:
        lower_points = [
            (left.pivot_index, left.pivot_price),
            (right.pivot_index, right.pivot_price),
        ]
        upper_points = [
            (first_mid.pivot_index, first_mid.pivot_price),
            (second_mid.pivot_index, second_mid.pivot_price),
        ]
    upper_slope, upper_intercept = _fit_line(upper_points)
    lower_slope, lower_intercept = _fit_line(lower_points)
    return _assemble(
        frame,
        timeframe,
        "head_and_shoulders",
        direction,
        tuple(group),
        asof_index,
        atr,
        upper_slope,
        lower_slope,
        upper_intercept + upper_slope * asof_index,
        lower_intercept + lower_slope * asof_index,
        prominence / max(atr, _EPS),
        0.0,
        "swing",
        gap,
    )


def _impulse_patterns(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    found: list[Candidate] = []
    for index in range(len(visible) - 1):
        start = visible[index]
        end = visible[index + 1]
        if start.swing_type == end.swing_type:
            continue
        impulse = abs(end.pivot_price - start.pivot_price)
        if impulse < IMPULSE_ATR_MIN * atr:
            continue
        direction = "bullish" if end.pivot_price > start.pivot_price else "bearish"
        packed = _consolidation_points(end, visible[index + 2 : index + 8])
        if packed is None:
            continue
        upper_points, lower_points, rest = packed
        prices = [price for _, price in upper_points + lower_points]
        span = max(prices) - min(prices)
        if span > FLAG_RETRACE_MAX * impulse:
            continue
        drift = rest[-1].pivot_price - end.pivot_price
        if direction == "bullish" and drift >= 0.0:
            continue
        if direction == "bearish" and drift <= 0.0:
            continue
        upper_slope, upper_intercept = _fit_line(upper_points)
        lower_slope, lower_intercept = _fit_line(lower_points)
        upper_at = upper_intercept + upper_slope * asof_index
        lower_at = lower_intercept + lower_slope * asof_index
        used = (start, end, *rest)
        retrace = span / max(impulse, _EPS)
        impulse_atr = impulse / max(atr, _EPS)
        found.append(
            _assemble(
                frame,
                timeframe,
                "flag",
                direction,
                used,
                asof_index,
                atr,
                upper_slope,
                lower_slope,
                upper_at,
                lower_at,
                impulse_atr,
                retrace,
                "swing",
                None,
            )
        )
        slope_gap = (lower_slope - upper_slope) / max(atr, _EPS)
        if slope_gap > CONVERGENCE_SLOPE_ATR:
            found.append(
                _assemble(
                    frame,
                    timeframe,
                    "pennant",
                    direction,
                    used,
                    asof_index,
                    atr,
                    upper_slope,
                    lower_slope,
                    upper_at,
                    lower_at,
                    impulse_atr,
                    retrace,
                    "swing",
                    None,
                )
            )
    return found


def _consolidation_points(
    impulse_end: Swing,
    rest: Sequence[Swing],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], list[Swing]] | None:
    """Collect two boundary points on each side, including the impulse end."""
    upper: list[tuple[int, float]] = []
    lower: list[tuple[int, float]] = []
    if impulse_end.swing_type == "high":
        upper.append((impulse_end.pivot_index, impulse_end.pivot_price))
    else:
        lower.append((impulse_end.pivot_index, impulse_end.pivot_price))
    used: list[Swing] = []
    for swing in rest:
        used.append(swing)
        point = (swing.pivot_index, swing.pivot_price)
        if swing.swing_type == "high":
            upper.append(point)
        else:
            lower.append(point)
        if len(upper) >= 2 and len(lower) >= 2:
            return upper, lower, used
    return None


def _boundary_pattern(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    highs = [swing for swing in visible if swing.swing_type == "high"][-4:]
    lows = [swing for swing in visible if swing.swing_type == "low"][-4:]
    if len(highs) < 2 or len(lows) < 2:
        return []
    upper_points = [(swing.pivot_index, swing.pivot_price) for swing in highs]
    lower_points = [(swing.pivot_index, swing.pivot_price) for swing in lows]
    upper_slope, upper_intercept = _fit_line(upper_points)
    lower_slope, lower_intercept = _fit_line(lower_points)
    family = _family_from_slopes(upper_slope / max(atr, _EPS), lower_slope / max(atr, _EPS))
    if family is None:
        return []
    used = tuple(highs + lows)
    upper_at = upper_intercept + upper_slope * asof_index
    lower_at = lower_intercept + lower_slope * asof_index
    return [
        _assemble(
            frame,
            timeframe,
            family,
            _BOUNDARY_DIRECTION[family],
            used,
            asof_index,
            atr,
            upper_slope,
            lower_slope,
            upper_at,
            lower_at,
            abs(upper_at - lower_at) / max(atr, _EPS),
            0.0,
            "swing",
            None,
        )
    ]


def _family_from_slopes(upper_slope: float, lower_slope: float) -> str | None:
    """Classify two ATR-per-bar slopes into one boundary family."""
    flat = SLOPE_FLAT_ATR
    if abs(upper_slope) <= flat and abs(lower_slope) <= flat:
        return "rectangle"
    if abs(upper_slope) <= flat and lower_slope > flat:
        return "ascending_triangle"
    if abs(lower_slope) <= flat and upper_slope < -flat:
        return "descending_triangle"
    if upper_slope < -flat and lower_slope > flat:
        return "symmetrical_triangle"
    if upper_slope > flat and lower_slope < -flat:
        return "broadening"
    if upper_slope > flat and lower_slope > flat:
        if abs(upper_slope - lower_slope) <= PARALLEL_SLOPE_ATR:
            return "ascending_channel"
        if lower_slope > upper_slope + CONVERGENCE_SLOPE_ATR:
            return "rising_wedge"
        return None
    if upper_slope < -flat and lower_slope < -flat:
        if abs(upper_slope - lower_slope) <= PARALLEL_SLOPE_ATR:
            return "descending_channel"
        if upper_slope < lower_slope - CONVERGENCE_SLOPE_ATR:
            return "falling_wedge"
        return None
    return None


def _cups(
    visible: Sequence[Swing],
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    highs = [swing for swing in visible if swing.swing_type == "high"]
    lows = [swing for swing in visible if swing.swing_type == "low"]
    found = _cup_side(lows, highs, "bullish", frame, timeframe, asof_index, atr)
    found.extend(_cup_side(highs, lows, "bearish", frame, timeframe, asof_index, atr))
    return found


def _cup_side(
    bottoms: Sequence[Swing],
    lips: Sequence[Swing],
    direction: str,
    frame: pd.DataFrame,
    timeframe: str,
    asof_index: int,
    atr: float,
) -> list[Candidate]:
    """Rounded recovery. ``bottoms`` are the cup extremes and ``lips`` the rims."""
    found: list[Candidate] = []
    for bottom in bottoms:
        prior = [swing for swing in lips if swing.pivot_index < bottom.pivot_index]
        later = [swing for swing in lips if swing.pivot_index > bottom.pivot_index]
        if not prior or not later:
            continue
        left = prior[-1]
        right = later[0]
        gap = abs(left.pivot_price - right.pivot_price)
        if gap > SIMILAR_PRICE_ATR * atr:
            continue
        if bottom.pivot_index - left.pivot_index < MIN_CUP_SIDE_BARS:
            continue
        if right.pivot_index - bottom.pivot_index < MIN_CUP_SIDE_BARS:
            continue
        lip = (left.pivot_price + right.pivot_price) / 2.0
        depth = (lip - bottom.pivot_price) if direction == "bullish" else (bottom.pivot_price - lip)
        if depth < CUP_DEPTH_ATR * atr:
            continue
        handles = [swing for swing in bottoms if swing.pivot_index > right.pivot_index]
        if not handles:
            continue
        handle = handles[0]
        retrace = (
            right.pivot_price - handle.pivot_price
            if direction == "bullish"
            else handle.pivot_price - right.pivot_price
        )
        if retrace < HANDLE_RETRACE_MIN * depth or retrace > HANDLE_RETRACE_MAX * depth:
            continue
        if direction == "bullish" and handle.pivot_price <= bottom.pivot_price:
            continue
        if direction == "bearish" and handle.pivot_price >= bottom.pivot_price:
            continue
        upper_points, lower_points = _cup_lines(left, right, bottom, handle, direction)
        upper_slope, upper_intercept = _fit_line(upper_points)
        lower_slope, lower_intercept = _fit_line(lower_points)
        found.append(
            _assemble(
                frame,
                timeframe,
                "cup_and_handle",
                direction,
                (left, bottom, right, handle),
                asof_index,
                atr,
                upper_slope,
                lower_slope,
                upper_intercept + upper_slope * asof_index,
                lower_intercept + lower_slope * asof_index,
                depth / max(atr, _EPS),
                retrace / max(depth, _EPS),
                "rounded_proxy",
                gap,
            )
        )
    return found


def _cup_lines(
    left: Swing,
    right: Swing,
    bottom: Swing,
    handle: Swing,
    direction: str,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    lips = [
        (left.pivot_index, left.pivot_price),
        (right.pivot_index, right.pivot_price),
    ]
    bowl = [
        (bottom.pivot_index, bottom.pivot_price),
        (handle.pivot_index, handle.pivot_price),
    ]
    if direction == "bullish":
        return lips, bowl
    return bowl, lips


def _assemble(
    frame: pd.DataFrame,
    timeframe: str,
    pattern: str,
    direction: str,
    used: Sequence[Swing],
    asof_index: int,
    atr: float,
    upper_slope: float,
    lower_slope: float,
    upper_at: float,
    lower_at: float,
    impulse_atr: float,
    retrace: float,
    geometry_kind: str,
    similar_gap: float | None,
) -> Candidate:
    """Build one candidate from boundary lines known at ``asof_index``."""
    swings = tuple(used)
    first_conf = min(swings, key=lambda swing: swing.confirmation_index)
    last_conf = max(swings, key=lambda swing: swing.confirmation_index)
    first_pivot = min(swing.pivot_index for swing in swings)
    last_pivot = max(swing.pivot_index for swing in swings)
    width = max(last_pivot - first_pivot, 1)
    height_start = _height(upper_at, upper_slope, lower_at, lower_slope, asof_index, first_pivot)
    height_end = _height(upper_at, upper_slope, lower_at, lower_slope, asof_index, last_pivot)
    raw_change = (height_start - height_end) / max(abs(height_start), _EPS)
    high_points = [
        (swing.pivot_index, swing.pivot_price)
        for swing in swings
        if swing.swing_type == "high"
    ]
    low_points = [
        (swing.pivot_index, swing.pivot_price)
        for swing in swings
        if swing.swing_type == "low"
    ]
    upper_error, upper_touches = _line_fit(high_points, upper_slope, upper_at, asof_index, atr)
    lower_error, lower_touches = _line_fit(low_points, lower_slope, lower_at, asof_index, atr)
    close = float(frame["close"].iloc[asof_index])
    span = upper_at - lower_at
    if abs(span) > _EPS:
        position = (close - lower_at) / span
    else:
        position = 0.5
    contraction, expansion = _volume_ratios(
        frame["volume"].to_numpy(dtype=np.float64),
        first_pivot,
        last_pivot,
    )
    last_touch = _last_touch(
        high_points,
        low_points,
        upper_slope,
        upper_at,
        lower_slope,
        lower_at,
        asof_index,
        atr,
        last_pivot,
    )
    recency = float(np.log1p(max(asof_index - last_touch, 0)) / np.log1p(WINDOW_BARS))
    maturity = float(np.clip((asof_index - first_pivot) / width, 0.0, 3.0))
    values = {
        "timeframe_id": float(TIMEFRAME_ID[timeframe]),
        "formation_width_bars": float(width),
        "formation_height_atr": abs(span) / max(atr, _EPS),
        "upper_boundary_slope": upper_slope / max(atr, _EPS),
        "lower_boundary_slope": lower_slope / max(atr, _EPS),
        "upper_boundary_distance_atr": (upper_at - close) / max(atr, _EPS),
        "lower_boundary_distance_atr": (close - lower_at) / max(atr, _EPS),
        "boundary_convergence_ratio": max(0.0, raw_change),
        "boundary_divergence_ratio": max(0.0, -raw_change),
        "swing_high_count": float(len(high_points)),
        "swing_low_count": float(len(low_points)),
        "upper_boundary_touches": float(upper_touches),
        "lower_boundary_touches": float(lower_touches),
        "upper_boundary_error_atr": upper_error,
        "lower_boundary_error_atr": lower_error,
        "price_position_in_formation": position,
        "volume_contraction_ratio": contraction,
        "volume_expansion_ratio": expansion,
        "bars_since_last_interaction": recency,
        "impulse_move_atr": float(impulse_atr),
        "retracement_ratio": float(retrace),
        "formation_maturity_ratio": maturity,
    }
    features = np.array(
        [values[name] for name in MODEL_CANDIDATE_FEATURES],
        dtype=np.float64,
    )
    features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
    score = _rule_score(upper_touches, lower_touches, upper_error, lower_error, similar_gap, atr)
    start_swing = min(swings, key=lambda swing: swing.pivot_index)
    return Candidate(
        candidate_id=(
            f"{timeframe}|{pattern}|{_iso(first_conf.confirmation_time)}|"
            f"{_iso(last_conf.confirmation_time)}"
        ),
        timeframe=timeframe,
        pattern=pattern,
        direction=direction,
        rule_score=score,
        geometry_kind=geometry_kind,
        swing_confirmation_indices=tuple(
            sorted(swing.confirmation_index for swing in swings)
        ),
        first_confirmation_index=first_conf.confirmation_index,
        last_confirmation_index=last_conf.confirmation_index,
        first_pivot_index=first_pivot,
        last_pivot_index=last_pivot,
        upper_price_at_asof=float(upper_at),
        lower_price_at_asof=float(lower_at),
        upper_slope=float(upper_slope),
        lower_slope=float(lower_slope),
        atr=float(atr),
        origin_close=close,
        start_time=start_swing.pivot_time,
        asof_time=pd.Timestamp(frame["time"].iloc[asof_index]),
        features=features,
    )


def _rule_score(
    upper_touches: int,
    lower_touches: int,
    upper_error: float,
    lower_error: float,
    similar_gap: float | None,
    atr: float,
) -> float:
    """Preliminary score from touches, fit error, and price similarity."""
    touch_score = min(upper_touches + lower_touches, 6) / 6.0
    error_score = math.exp(-0.5 * (upper_error + lower_error))
    if similar_gap is None:
        gap_score = 1.0
    else:
        gap_score = 1.0 - min(1.0, similar_gap / max(SIMILAR_PRICE_ATR * atr, _EPS))
    return float(np.clip((touch_score + error_score + gap_score) / 3.0, 0.0, 1.0))


def _fit_line(points: Sequence[tuple[int, float]]) -> tuple[float, float]:
    """Return price-per-bar slope and intercept of ``price = intercept + slope * index``."""
    if not points:
        return 0.0, 0.0
    xs = np.array([point[0] for point in points], dtype=np.float64)
    ys = np.array([point[1] for point in points], dtype=np.float64)
    if len(points) == 1 or np.unique(xs).size < 2:
        return 0.0, float(np.mean(ys))
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def _line_fit(
    points: Sequence[tuple[int, float]],
    slope: float,
    price_at_asof: float,
    asof_index: int,
    atr: float,
) -> tuple[float, int]:
    """Mean absolute residual in ATR, and the number of points within tolerance."""
    if not points:
        return 0.0, 0
    errors: list[float] = []
    touches = 0
    for index, price in points:
        predicted = price_at_asof + slope * (index - asof_index)
        error = abs(price - predicted)
        errors.append(error)
        if error <= TOUCH_TOL_ATR * atr:
            touches += 1
    return float(np.mean(errors) / max(atr, _EPS)), touches


def _height(
    upper_at: float,
    upper_slope: float,
    lower_at: float,
    lower_slope: float,
    asof_index: int,
    index: int,
) -> float:
    """Signed upper-minus-lower distance at ``index``."""
    upper = upper_at + upper_slope * (index - asof_index)
    lower = lower_at + lower_slope * (index - asof_index)
    return upper - lower


def _volume_ratios(volume: np.ndarray, first: int, last: int) -> tuple[float, float]:
    """Return contraction and expansion of the second half versus the first."""
    if last <= first:
        return 1.0, 1.0
    mid = first + max((last - first) // 2, 1)
    mid = min(mid, last)
    first_mean = float(np.mean(volume[first:mid])) if mid > first else float(volume[first])
    second_mean = float(np.mean(volume[mid : last + 1]))
    expansion = second_mean / first_mean if first_mean > _EPS else 1.0
    contraction = first_mean / second_mean if second_mean > _EPS else 1.0
    return float(contraction), float(expansion)


def _last_touch(
    highs: Sequence[tuple[int, float]],
    lows: Sequence[tuple[int, float]],
    upper_slope: float,
    upper_at: float,
    lower_slope: float,
    lower_at: float,
    asof_index: int,
    atr: float,
    fallback: int,
) -> int:
    """Latest pivot that sits within the touch tolerance of either boundary."""
    latest = fallback
    groups = (
        (highs, upper_slope, upper_at),
        (lows, lower_slope, lower_at),
    )
    for points, slope, price_at in groups:
        for index, price in points:
            predicted = price_at + slope * (index - asof_index)
            if abs(price - predicted) <= TOUCH_TOL_ATR * atr:
                latest = max(latest, index)
    return latest


def _visible_in_window(swings: Sequence[Swing], asof_index: int) -> list[Swing]:
    """Confirmed swings whose pivot lies in the 192 bars ending at ``asof_index``."""
    start = max(0, asof_index - WINDOW_BARS + 1)
    chosen = [
        swing
        for swing in swings
        if swing.confirmation_index <= asof_index and swing.pivot_index >= start
    ]
    chosen.sort(key=lambda swing: (swing.pivot_index, swing.confirmation_index))
    return chosen


def _asof_atr(frame: pd.DataFrame, asof_index: int) -> float:
    """Positive ATR at the as-of bar."""
    atr = float(frame["atr"].iloc[asof_index]) if "atr" in frame.columns else np.nan
    if np.isfinite(atr) and atr > 0.0:
        return atr
    return max(abs(float(frame["close"].iloc[asof_index])) * 0.01, _EPS)


def _price_span(candidate: Candidate) -> tuple[float, float]:
    lower = min(candidate.lower_price_at_asof, candidate.upper_price_at_asof)
    upper = max(candidate.lower_price_at_asof, candidate.upper_price_at_asof)
    return lower, upper


def _ranges_overlap(
    left: tuple[float, float] | tuple[pd.Timestamp, pd.Timestamp],
    right: tuple[float, float] | tuple[pd.Timestamp, pd.Timestamp],
) -> bool:
    """True when two closed intervals share a point."""
    return left[0] <= right[1] and right[0] <= left[1]


def _timeframe_order(left: Candidate, right: Candidate) -> tuple[Candidate, Candidate]:
    if TIMEFRAME_ID[left.timeframe] <= TIMEFRAME_ID[right.timeframe]:
        return left, right
    return right, left


def _iso(stamp: pd.Timestamp) -> str:
    value = pd.Timestamp(stamp)
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
