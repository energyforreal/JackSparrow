"""Multi-timeframe algorithmic score shared by research and the live path.

The score is a weighted sum of trend, structure, pattern, zone, candle,
volume, and momentum evidence. It does not train a model and it does not
import execution.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from feature_store.pattern_features.candlestick_patterns import CandlestickPatternEngine
from feature_store.pattern_features.chart_patterns import ChartPatternEngine
from feature_store.transformer_btcusd.structure import add_market_structure_features
from feature_store.unified_feature_engine import UnifiedFeatureEngine
from research.swinging.contract import (
    ALGO_BOS_LOOKBACK,
    ALGO_HIGH_QUALITY_SCORE,
    ALGO_QUALIFIED_SCORE,
    ALGO_WEIGHTS,
    BAR_MINUTES,
    RESOLUTIONS,
    STOP_ATR_MULT,
    TAKE_PROFIT_ATR_MULT,
)
from research.swinging.quality import decision_data_issues, normalize_ohlcv

_BULL_CHART = (
    "chp_bull_flag",
    "chp_asc_triangle",
    "chp_double_bottom",
    "chp_ihs_detected",
    "tl_breakout_up",
)
_BEAR_CHART = (
    "chp_bear_flag",
    "chp_desc_triangle",
    "chp_double_top",
    "chp_hs_detected",
    "tl_breakout_down",
)
_BULL_CANDLE = (
    "cdl_bull_engulfing",
    "cdl_hammer",
    "cdl_inv_hammer",
    "cdl_morning_star",
)
_BEAR_CANDLE = (
    "cdl_bear_engulfing",
    "cdl_shooting_star",
    "cdl_hanging_man",
    "cdl_evening_star",
)


def resolve_weights(weights: Mapping[str, float] | None = None) -> dict[str, float]:
    """Return score weights renormalized so they sum to 100.

    Args:
        weights: Optional overrides for keys in ``ALGO_WEIGHTS``.

    Returns:
        Weights that sum to 100.

    Raises:
        ValueError: If the supplied weights are not positive.
    """
    resolved = dict(ALGO_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key in resolved:
                resolved[key] = float(value)
    total = sum(resolved.values())
    if total <= 0.0:
        raise ValueError("algorithmic weights must sum to a positive number")
    return {key: 100.0 * value / total for key, value in resolved.items()}


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Build one causal analysis frame from OHLCV.

    Args:
        frame: Candles with time, open, high, low, close, and volume.

    Returns:
        The same bars plus structure, candle, chart, and indicator columns.
        BOS and CHoCH columns come from the structure loop and are not part
        of the transformer feature contract.
    """
    work = normalize_ohlcv(frame)
    structured = add_market_structure_features(work.copy()).reset_index(drop=True)
    candles = CandlestickPatternEngine().compute_all(work).reset_index(drop=True)
    charts = ChartPatternEngine().compute_all(work).reset_index(drop=True)
    features = UnifiedFeatureEngine().compute_batch(work).reset_index(drop=True)
    extras = []
    for source in (candles, charts, features):
        keep = [column for column in source.columns if column not in structured.columns]
        if keep:
            extras.append(source.loc[:, keep])
    out = pd.concat([structured, *extras], axis=1) if extras else structured
    out = out.copy()
    close = out["close"].astype(float)
    out["ema_20"] = close.ewm(span=20, adjust=False).mean()
    out["ema_50"] = close.ewm(span=50, adjust=False).mean()
    out["ema_200"] = close.ewm(span=200, adjust=False).mean()
    out["ema_20_slope"] = out["ema_20"].diff().fillna(0.0)
    if "atr_14" not in out.columns and "atr" in out.columns:
        out["atr_14"] = out["atr"]
    return out


def _num(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _flag(row: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    for name in names:
        if _num(row.get(name)) > 0.0:
            return True
    return False


def _trend_fraction(row: Mapping[str, Any], direction: str) -> float:
    close = _num(row.get("close"))
    ema20 = _num(row.get("ema_20"))
    ema50 = _num(row.get("ema_50"))
    ema200 = _num(row.get("ema_200"))
    slope = _num(row.get("ema_20_slope"))
    if direction == "long":
        if close > ema20 > ema50 > ema200 and slope > 0.0:
            return 1.0
        if close > ema50 > ema200 and slope > 0.0:
            return 0.5
        return 0.0
    if close < ema20 < ema50 < ema200 and slope < 0.0:
        return 1.0
    if close < ema50 < ema200 and slope < 0.0:
        return 0.5
    return 0.0


def _structure_fraction(
    row: Mapping[str, Any],
    direction: str,
    lookback: int,
) -> tuple[float, str]:
    """Score swing bias, confirming BOS, and invalidating CHoCH.

    Args:
        row: One closed 1h analysis bar.
        direction: ``long`` or ``short``.
        lookback: Maximum age, in 1h bars, of a confirming or invalidating break.

    Returns:
        Fraction in ``[0, 1]`` and an invalidation code. An opposing CHoCH
        that is at least as recent as the last BOS zeros the component.
    """
    sign = 1.0 if direction == "long" else -1.0
    bias = _num(row.get("structure_bias")) * sign
    bos_side = _num(row.get("last_bos_side")) * sign
    choch_side = _num(row.get("last_choch_side")) * sign
    bos_age = _num(row.get("bars_since_bos"), default=1.0e9)
    choch_age = _num(row.get("bars_since_choch"), default=1.0e9)
    choch_against = choch_side < 0.0 and choch_age <= float(lookback)
    if choch_against and choch_age <= bos_age:
        code = "bearish_choch" if direction == "long" else "bullish_choch"
        return 0.0, code
    recent_bos = bos_side > 0.0 and bos_age <= float(lookback)
    if bias > 0.2 or (bias > 0.0 and recent_bos):
        return 1.0, ""
    if bias > 0.0 or recent_bos:
        return 0.5, ""
    return 0.0, ""


def _pattern_fraction(row: Mapping[str, Any], direction: str) -> float:
    names = _BULL_CHART if direction == "long" else _BEAR_CHART
    if _flag(row, names):
        return 1.0
    trend_name = "tl_uptrend_detected" if direction == "long" else "tl_downtrend_detected"
    if _flag(row, (trend_name,)):
        return 0.5
    return 0.0


def _zone_fraction(row: Mapping[str, Any], direction: str) -> float:
    if direction == "long":
        distance = _num(row.get("dist_to_support_atr"), default=99.0)
        touched = _num(row.get("support_touch_count")) > 0.0 or _flag(row, ("sr_at_support",))
        rejected = _num(row.get("close")) >= _num(row.get("open"))
    else:
        distance = _num(row.get("dist_to_resistance_atr"), default=99.0)
        touched = _num(row.get("resistance_touch_count")) > 0.0 or _flag(
            row, ("sr_at_resistance",)
        )
        rejected = _num(row.get("close")) <= _num(row.get("open"))
    if touched and distance <= 1.0 and rejected:
        return 1.0
    return 0.0


def _confirm_fraction(row: Mapping[str, Any], direction: str) -> float:
    names = _BULL_CANDLE if direction == "long" else _BEAR_CANDLE
    if _flag(row, names):
        return 1.0
    bull = _num(row.get("cdl_bull_score"))
    bear = _num(row.get("cdl_bear_score"))
    if direction == "long" and bull > bear and bull > 0.0:
        return 0.5
    if direction == "short" and bear > bull and bear > 0.0:
        return 0.5
    return 0.0


def _volume_fraction(row: Mapping[str, Any]) -> float:
    ratio = _num(row.get("volume_ratio"))
    if ratio <= 0.0:
        ratio = _num(row.get("breakout_vol_ratio"))
    if ratio >= 1.2:
        return 1.0
    if ratio >= 1.0:
        return 0.5
    return 0.0


def _momentum_fraction(row: Mapping[str, Any], direction: str) -> float:
    rsi = _num(row.get("rsi_14"), default=50.0)
    histogram = _num(row.get("macd_histogram"))
    if direction == "long":
        if rsi >= 55.0 and histogram > 0.0:
            return 1.0
        if rsi >= 50.0 or histogram > 0.0:
            return 0.5
        return 0.0
    if rsi <= 45.0 and histogram < 0.0:
        return 1.0
    if rsi <= 50.0 or histogram < 0.0:
        return 0.5
    return 0.0


def side_fractions(
    rows: Mapping[str, Mapping[str, Any]],
    direction: str,
    lookback: int = ALGO_BOS_LOOKBACK,
) -> tuple[dict[str, float], str]:
    """Return component fractions for one direction.

    Args:
        rows: Closed analysis bars keyed by ``5m``, ``15m``, ``1h``, and ``4h``.
        direction: ``long`` or ``short``.
        lookback: BOS and CHoCH age limit on the 1h frame.

    Returns:
        Fractions keyed like ``ALGO_WEIGHTS``, and a structure invalidation code.
    """
    structure, invalidation = _structure_fraction(rows["1h"], direction, lookback)
    fractions = {
        "trend_4h": _trend_fraction(rows["4h"], direction),
        "structure_1h": structure,
        "pattern_15m": _pattern_fraction(rows["15m"], direction),
        "zone_rejection": _zone_fraction(rows["1h"], direction),
        "confirm_5m": _confirm_fraction(rows["5m"], direction),
        "volume": _volume_fraction(rows["5m"]),
        "momentum": _momentum_fraction(rows["5m"], direction),
    }
    return fractions, invalidation


def decide_scores(
    *,
    long_score: float,
    short_score: float,
    long_invalidation: str = "",
    short_invalidation: str = "",
    qualified_score: float = ALGO_QUALIFIED_SCORE,
    high_quality_score: float = ALGO_HIGH_QUALITY_SCORE,
) -> dict[str, Any]:
    """Turn the two directional totals into a trade or a hold.

    Args:
        long_score: Long points out of 100.
        short_score: Short points out of 100.
        long_invalidation: Set when 1h structure invalidates a long.
        short_invalidation: Set when 1h structure invalidates a short.
        qualified_score: Minimum points that may trade. Design value, not a proof.
        high_quality_score: Points that map to a strong signal.

    Returns:
        Action, wire signal, quality, score, and invalidation.
    """
    qualified = float(qualified_score)
    high = float(high_quality_score)
    candidates: list[tuple[str, float, str]] = []
    if not long_invalidation and long_score >= qualified:
        candidates.append(("long", float(long_score), ""))
    if not short_invalidation and short_score >= qualified:
        candidates.append(("short", float(short_score), ""))
    reported = long_score >= short_score
    reported_score = float(long_score if reported else short_score)
    reported_note = long_invalidation if reported else short_invalidation
    if len(candidates) == 2 and abs(candidates[0][1] - candidates[1][1]) < 5.0:
        action, score, note = "abstain", reported_score, "direction_conflict"
        signal, quality = "HOLD", "none"
    elif not candidates:
        action, score, note = "abstain", reported_score, reported_note or "below_threshold"
        signal, quality = "HOLD", "none"
    else:
        action, score, note = max(candidates, key=lambda item: item[1])
        if score >= high:
            signal = "STRONG_BUY" if action == "long" else "STRONG_SELL"
            quality = "high"
        else:
            signal = "BUY" if action == "long" else "SELL"
            quality = "qualified"
    return {
        "action": action,
        "signal": signal,
        "quality": quality,
        "score": float(score),
        "long_score": float(long_score),
        "short_score": float(short_score),
        "invalidation": note,
    }


def _closed_row(
    frame: pd.DataFrame,
    resolution: str,
    decision_time: pd.Timestamp,
) -> pd.Series | None:
    """Return the last bar whose close is at or before ``decision_time``.

    ``time`` is the bar open. A higher-timeframe bar is not used while it is
    still forming.
    """
    if frame.empty or "time" not in frame.columns:
        return None
    opens = pd.to_datetime(frame["time"], utc=True)
    closes = opens + pd.Timedelta(minutes=BAR_MINUTES[resolution])
    decision = pd.Timestamp(decision_time)
    if decision.tzinfo is None:
        decision = decision.tz_localize("UTC")
    position = int(closes.searchsorted(decision, side="right")) - 1
    if position < 0:
        return None
    return frame.iloc[position]


def _points(fractions: Mapping[str, float], weights: Mapping[str, float]) -> dict[str, float]:
    return {key: float(weights[key]) * float(fractions[key]) for key in weights}


def _brackets(direction: str, close: float, atr: float) -> tuple[float, float]:
    risk = STOP_ATR_MULT * atr
    reward = TAKE_PROFIT_ATR_MULT * atr
    if direction == "short":
        return close + risk, close - reward
    return close - risk, close + reward


def engine_a_direction(frame: pd.DataFrame, resolution: str, index: int) -> str | None:
    """Return the best accepted Engine A direction on one bar.

    Args:
        frame: Normalized OHLCV.
        resolution: Setup timeframe.
        index: Bar position shared with ``generate_setups``.

    Returns:
        ``long``, ``short``, or ``None`` when that bar has no accepted setup.
    """
    from research.swinging.setups import generate_setups

    generated = generate_setups(frame, resolution, indexes=[int(index)])
    if generated.empty or "status" not in generated.columns:
        return None
    accepted = generated[generated["status"] == "accepted"]
    if accepted.empty:
        return None
    best = accepted.sort_values("algorithmic_score", ascending=False).iloc[0]
    direction = str(best.get("direction") or "")
    if direction in ("long", "short"):
        return direction
    return None


def score_snapshot(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
    qualified_score: float | None = None,
    high_quality_score: float | None = None,
    bos_lookback: int = ALGO_BOS_LOOKBACK,
    engine_directions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Score one aligned set of closed bars.

    Args:
        rows: Closed bars for each swinging resolution.
        weights: Optional weight overrides. Renormalized to 100.
        qualified_score: Hold threshold.
        high_quality_score: Strong-signal threshold.
        bos_lookback: 1h bars that a BOS or CHoCH may still influence.
        engine_directions: Accepted Engine A direction keyed by resolution.
            A match lifts that timeframe's pattern or confirmation fraction.

    Returns:
        Decision payload with component points, brackets, and the wire signal.
    """
    resolved = resolve_weights(weights)
    qualified = ALGO_QUALIFIED_SCORE if qualified_score is None else float(qualified_score)
    high = ALGO_HIGH_QUALITY_SCORE if high_quality_score is None else float(high_quality_score)
    directions = engine_directions or {}
    long_frac, long_note = side_fractions(rows, "long", bos_lookback)
    short_frac, short_note = side_fractions(rows, "short", bos_lookback)
    for resolution, found in directions.items():
        if resolution == "15m" and found == "long":
            long_frac["pattern_15m"] = max(long_frac["pattern_15m"], 1.0)
        elif resolution == "15m" and found == "short":
            short_frac["pattern_15m"] = max(short_frac["pattern_15m"], 1.0)
        elif resolution == "5m" and found == "long":
            long_frac["confirm_5m"] = max(long_frac["confirm_5m"], 1.0)
        elif resolution == "5m" and found == "short":
            short_frac["confirm_5m"] = max(short_frac["confirm_5m"], 1.0)
    long_points = _points(long_frac, resolved)
    short_points = _points(short_frac, resolved)
    decision = decide_scores(
        long_score=sum(long_points.values()),
        short_score=sum(short_points.values()),
        long_invalidation=long_note,
        short_invalidation=short_note,
        qualified_score=qualified,
        high_quality_score=high,
    )
    five = rows["5m"]
    close = _num(five.get("close"))
    atr = _num(five.get("atr_14"))
    if atr <= 0.0:
        atr = _num(five.get("atr"))
    if atr <= 0.0:
        atr = max(abs(close) * 0.01, 1e-9)
    bracket_side = decision["action"] if decision["action"] in ("long", "short") else "long"
    stop, take = _brackets(bracket_side, close, atr)
    confidence = max(0.0, min(1.0, decision["score"] / 100.0))
    chosen = long_points if decision["long_score"] >= decision["short_score"] else short_points
    return {
        **decision,
        "components": chosen,
        "long_components": long_points,
        "short_components": short_points,
        "confidence": confidence,
        "position_size": 0.0,
        "atr": atr,
        "close": close,
        "stop_price": stop,
        "take_profit_price": take,
        "weights": resolved,
    }


def _hold_result(reason: str) -> dict[str, Any]:
    """Return a no-trade score payload."""
    return {
        "action": "abstain",
        "signal": "HOLD",
        "quality": "none",
        "score": 0.0,
        "long_score": 0.0,
        "short_score": 0.0,
        "invalidation": reason,
        "components": {},
        "long_components": {},
        "short_components": {},
        "confidence": 0.0,
        "position_size": 0.0,
        "atr": 0.0,
        "close": 0.0,
        "stop_price": 0.0,
        "take_profit_price": 0.0,
        "bar_index": None,
        "reason": reason,
    }


def score_frames(
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of: pd.Timestamp | None = None,
    weights: Mapping[str, float] | None = None,
    qualified_score: float | None = None,
    high_quality_score: float | None = None,
    bos_lookback: int = ALGO_BOS_LOOKBACK,
    include_engine_a: bool = False,
    prepared: Mapping[str, pd.DataFrame] | None = None,
    now: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Score the latest closed 5m bar using 15m, 1h, and 4h context.

    Args:
        frames: OHLCV keyed by resolution. Every swinging resolution is required
            unless ``prepared`` already contains those frames.
        as_of: Decision timestamp. When omitted, ``now`` is used so a forming
            bar is not scored. Historical replays omit both and use the close
            of the last 5m bar.
        weights: Optional weight overrides.
        qualified_score: Hold threshold.
        high_quality_score: Strong-signal threshold.
        bos_lookback: 1h lookback for BOS and CHoCH.
        include_engine_a: When true, an accepted Engine A setup on the closed
            5m or 15m bar lifts that component to full credit.
        prepared: Optional precomputed analysis frames. Avoids rebuilding
            indicators when the caller scores many bars.
        now: When set, missing, invalid, or stale closed candles hold. A
            still-forming last row does not hold by itself. Historical replays
            leave this unset.

    Returns:
        ``score_snapshot`` payload plus the 5m bar index. Missing higher-timeframe
        history returns a hold with reason ``missing_timeframe``.
    """
    source = frames if frames else (prepared or {})
    issues = decision_data_issues(source, now=now)
    if issues:
        hold = _hold_result(issues[0])
        hold["data_issues"] = issues
        return hold
    missing = [name for name in RESOLUTIONS if name not in frames and not (
        prepared is not None and name in prepared
    )]
    if missing:
        return _hold_result("missing_timeframe")
    analysis = dict(prepared) if prepared is not None else {
        name: prepare_frame(frames[name]) for name in RESOLUTIONS
    }
    five = analysis["5m"]
    if five.empty:
        return _hold_result("empty_frame")
    if as_of is not None:
        decision_time = pd.Timestamp(as_of)
    elif now is not None:
        decision_time = pd.Timestamp(now)
    else:
        opened = pd.Timestamp(five["time"].iloc[-1])
        if opened.tzinfo is None:
            opened = opened.tz_localize("UTC")
        decision_time = opened + pd.Timedelta(minutes=BAR_MINUTES["5m"])
    if decision_time.tzinfo is None:
        decision_time = decision_time.tz_localize("UTC")
    else:
        decision_time = decision_time.tz_convert("UTC")
    rows: dict[str, pd.Series] = {}
    for name in RESOLUTIONS:
        row = _closed_row(analysis[name], name, decision_time)
        if row is None:
            return _hold_result(f"no_closed_{name}")
        rows[name] = row
    engine_directions: dict[str, str] = {}
    if include_engine_a:
        for name in ("5m", "15m"):
            raw = normalize_ohlcv(frames[name])
            found = engine_a_direction(raw, name, int(rows[name].name))
            if found:
                engine_directions[name] = found
    scored = score_snapshot(
        rows,
        weights=weights,
        qualified_score=qualified_score,
        high_quality_score=high_quality_score,
        bos_lookback=bos_lookback,
        engine_directions=engine_directions,
    )
    scored["bar_index"] = int(rows["5m"].name)
    scored["decision_time"] = decision_time.isoformat()
    return scored
