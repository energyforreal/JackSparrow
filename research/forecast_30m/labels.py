"""Targets A, B, and C for the 24-bar BTCUSD horizon.

Bar ``t`` is the signal. Only bars ``t+1`` through ``t+24`` enter a label.
A same-bar profit and stop touch is ``AMBIGUOUS``. Missing future timestamps
stay unlabeled. Nothing in this module fills a gap.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from research.forecast_30m.contract import (
    AMBIGUOUS,
    ATR_PERIOD,
    BARRIER_GRID,
    BEARISH,
    BULLISH,
    DIRECTION_NAMES,
    EXPIRY,
    HORIZON_BARS,
    MAX_AMBIGUOUS_SHARE,
    MAX_NO_SKILL_LOSS,
    MAX_PRECISION_GAP,
    MIN_NEUTRAL_COST_MULTIPLE,
    MIN_PATH_RATE,
    MINORITY_FLOOR,
    NEUTRAL,
    PATH_NAMES,
    ROUND_TRIP_COST,
    SL_FIRST,
    SPEC_VERSION,
    THETA_GRID,
    TP_FIRST,
    UNLABELED,
)
from research.forecast_30m.integrity import bar_seconds, to_epoch_seconds

_EPS = 1e-12


def causal_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    period: int = ATR_PERIOD,
) -> np.ndarray:
    """Simple mean of true range, using only bars at or before each index.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Trailing window. The first ``period`` rows are NaN.

    Returns:
        ATR aligned to ``close``. Non-positive results are left as computed.
    """
    previous = np.roll(close, 1)
    previous[0] = np.nan
    true_range = np.nanmax(
        np.vstack(
            [
                high - low,
                np.abs(high - previous),
                np.abs(low - previous),
            ]
        ),
        axis=0,
    )
    return (
        pd.Series(true_range)
        .rolling(int(period), min_periods=int(period))
        .mean()
        .to_numpy(dtype=np.float64)
    )


def classify_path(
    future_high: np.ndarray,
    future_low: np.ndarray,
    take_profit: float,
    stop: float,
    *,
    short: bool,
) -> int:
    """Walk one future path in bar order.

    Args:
        future_high: Highs of bars ``t+1`` onward.
        future_low: Lows of those bars.
        take_profit: Profit price.
        stop: Stop price.
        short: When true, profit is a low print and the stop is a high print.

    Returns:
        ``TP_FIRST``, ``SL_FIRST``, ``EXPIRY``, or ``AMBIGUOUS``.
    """
    for high, low in zip(future_high, future_low, strict=False):
        if short:
            profit_hit = float(low) <= take_profit
            stop_hit = float(high) >= stop
        else:
            profit_hit = float(high) >= take_profit
            stop_hit = float(low) <= stop
        if profit_hit and stop_hit:
            return AMBIGUOUS
        if profit_hit:
            return TP_FIRST
        if stop_hit:
            return SL_FIRST
    return EXPIRY


def future_positions(
    epoch_s: np.ndarray,
    *,
    bar_length: int,
    horizon_bars: int = HORIZON_BARS,
) -> np.ndarray:
    """Map each row to the positions of the next ``horizon_bars`` timestamps.

    Args:
        epoch_s: Unix seconds, one per row, unique and ascending.
        bar_length: Bar size in seconds.
        horizon_bars: Path length.

    Returns:
        Integer array of shape ``(n, horizon_bars)``. Missing bars are ``-1``.
    """
    epochs = np.asarray(epoch_s, dtype=np.int64)
    locator = {int(stamp): index for index, stamp in enumerate(epochs.tolist())}
    positions = np.full((len(epochs), int(horizon_bars)), -1, dtype=np.int64)
    for step in range(1, int(horizon_bars) + 1):
        targets = epochs + step * int(bar_length)
        positions[:, step - 1] = [locator.get(int(stamp), -1) for stamp in targets]
    return positions


def cusum_event_mask(
    close: np.ndarray,
    *,
    threshold: float,
) -> np.ndarray:
    """Symmetric CUSUM on close-to-close log returns.

    An event is recorded at bar ``t`` when the cumulative log move from the
    last reset reaches ``threshold``. Both accumulators reset after an event.
    Bar 0 is never an event. Non-positive prices skip that step.

    Args:
        close: Close prices, oldest first.
        threshold: Absolute log-return height that fires an event.

    Returns:
        Boolean mask, one flag per close.
    """
    prices = np.asarray(close, dtype=np.float64)
    events = np.zeros(prices.shape[0], dtype=bool)
    if prices.size < 2 or threshold <= 0.0:
        return events
    position = 0.0
    negative = 0.0
    previous = float(prices[0])
    for index in range(1, prices.size):
        price = float(prices[index])
        if not np.isfinite(price) or price <= _EPS or not np.isfinite(previous) or previous <= _EPS:
            previous = price
            continue
        move = float(np.log(price / previous))
        previous = price
        position = max(0.0, position + move)
        negative = min(0.0, negative + move)
        if position >= threshold or negative <= -threshold:
            events[index] = True
            position = 0.0
            negative = 0.0
    return events


def attach_targets(
    frame: pd.DataFrame,
    *,
    theta: float | None,
    tp_mult: float | None,
    sl_mult: float | None,
    horizon_bars: int = HORIZON_BARS,
    atr_period: int = ATR_PERIOD,
    entry: str = "close",
    tp_pct_fixed: float | None = None,
    sl_pct_fixed: float | None = None,
    event_mask: np.ndarray | None = None,
) -> pd.DataFrame:
    """Attach direction, forward return, and both barrier paths.

    Args:
        frame: Sorted OHLCV with a ``time`` column.
        theta: Neutral band in units of ATR / close. ``None`` leaves direction unlabeled.
        tp_mult: Take-profit distance in ATR. ``None`` leaves barrier labels empty
            unless fixed percents are set.
        sl_mult: Stop distance in ATR. Required when ``tp_mult`` is set.
        horizon_bars: Future bars required.
        atr_period: Causal ATR window.
        entry: ``close`` uses the signal close. ``next_open`` uses the open of
            bar ``t+1``.
        tp_pct_fixed: Take-profit as a fraction of the fill. Set with
            ``sl_pct_fixed`` instead of ATR multiples.
        sl_pct_fixed: Stop as a fraction of the fill.
        event_mask: When set, only those rows can receive a label.

    Returns:
        Copy with label columns. Unlabeled rows use ``-1`` and NaN.

    Raises:
        ValueError: If timestamps are duplicated or unsorted, the entry rule is
            unknown, or barrier arguments are only half-set.
    """
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"OHLCV frame is missing columns: {sorted(missing)}")
    stamps = pd.to_datetime(frame["time"], utc=True)
    if stamps.duplicated().any() or not stamps.is_monotonic_increasing:
        raise ValueError("OHLCV timestamps must be unique and strictly increasing")
    if entry not in {"close", "next_open"}:
        raise ValueError(f"unknown entry rule: {entry}")
    if (tp_mult is None) != (sl_mult is None):
        raise ValueError("tp_mult and sl_mult must be set together")
    if (tp_pct_fixed is None) != (sl_pct_fixed is None):
        raise ValueError("tp_pct_fixed and sl_pct_fixed must be set together")
    if tp_mult is not None and tp_pct_fixed is not None:
        raise ValueError("use either ATR multiples or fixed percents")

    out = frame.copy().reset_index(drop=True)
    close = out["close"].to_numpy(dtype=np.float64)
    high = out["high"].to_numpy(dtype=np.float64)
    low = out["low"].to_numpy(dtype=np.float64)
    open_ = out["open"].to_numpy(dtype=np.float64)
    epochs = to_epoch_seconds(out["time"])
    atr = causal_atr(high, low, close, period=atr_period)
    positions = future_positions(
        epochs,
        bar_length=bar_seconds(),
        horizon_bars=horizon_bars,
    )
    horizon_ok = (positions >= 0).all(axis=1)
    atr_ok = np.isfinite(atr) & (atr > _EPS)
    close_ok = np.isfinite(close) & (close > _EPS)
    fill_ok = _fill_ok(positions, open_, entry)
    eligible = horizon_ok & close_ok & fill_ok
    if theta is not None or tp_mult is not None:
        eligible = eligible & atr_ok
    if event_mask is not None:
        eligible = eligible & np.asarray(event_mask, dtype=bool)

    n = len(out)
    direction = np.full(n, UNLABELED, dtype=np.int64)
    forward = np.full(n, np.nan, dtype=np.float64)
    log_return = np.full(n, np.nan, dtype=np.float64)
    long_code = np.full(n, UNLABELED, dtype=np.int64)
    short_code = np.full(n, UNLABELED, dtype=np.int64)
    band = np.full(n, np.nan, dtype=np.float64)
    tp_pct = np.full(n, np.nan, dtype=np.float64)
    sl_pct = np.full(n, np.nan, dtype=np.float64)

    use_barriers = tp_mult is not None or tp_pct_fixed is not None
    for index in np.flatnonzero(eligible).tolist():
        future = positions[index]
        fill_index = int(future[0]) if entry == "next_open" else index
        entry_price = float(open_[fill_index] if entry == "next_open" else close[index])
        end_close = float(close[int(future[-1])])
        if entry_price <= _EPS or end_close <= _EPS:
            continue
        simple = end_close / entry_price - 1.0
        forward[index] = simple
        log_return[index] = float(np.log(end_close / entry_price))
        if theta is not None:
            width = float(theta) * float(atr[index]) / entry_price
            band[index] = width
            if simple > width:
                direction[index] = BULLISH
            elif simple < -width:
                direction[index] = BEARISH
            else:
                direction[index] = NEUTRAL
        if not use_barriers:
            continue
        if tp_pct_fixed is not None:
            tp_fraction = float(tp_pct_fixed)
            sl_fraction = float(sl_pct_fixed)
        else:
            tp_fraction = float(tp_mult) * float(atr[index]) / entry_price
            sl_fraction = float(sl_mult) * float(atr[index]) / entry_price
        tp_pct[index] = tp_fraction
        sl_pct[index] = sl_fraction
        long_tp = entry_price * (1.0 + tp_fraction)
        long_sl = entry_price * (1.0 - sl_fraction)
        short_tp = entry_price * (1.0 - tp_fraction)
        short_sl = entry_price * (1.0 + sl_fraction)
        future_high = high[future]
        future_low = low[future]
        long_code[index] = _path_with_fill_gap(
            entry_price, future_high, future_low, long_tp, long_sl, short=False
        )
        short_code[index] = _path_with_fill_gap(
            entry_price, future_high, future_low, short_tp, short_sl, short=True
        )

    out["atr"] = atr
    out["neutral_band"] = band
    out["y_direction"] = direction
    out["forward_return_24"] = forward
    out["forward_log_return_24"] = log_return
    out["long_path_code"] = long_code
    out["short_path_code"] = short_code
    out["long_tp_first_24"] = _binary_target(long_code)
    out["short_tp_first_24"] = _binary_target(short_code)
    out["tp_pct"] = tp_pct
    out["sl_pct"] = sl_pct
    out["horizon_ok"] = horizon_ok
    out["label_row_ok"] = eligible
    out["entry_rule"] = entry
    return out


def development_supervised_mask(
    epoch_s: np.ndarray,
    *,
    holdout_start: int,
    bar_length: int,
    horizon_bars: int = HORIZON_BARS,
    horizon_ok: np.ndarray | None = None,
) -> np.ndarray:
    """Rows whose signal and entire label path sit before the holdout.

    Args:
        epoch_s: Unix seconds.
        holdout_start: First holdout timestamp, in Unix seconds.
        bar_length: Bar size in seconds.
        horizon_bars: Label length.
        horizon_ok: Optional mask of rows that have every future bar.

    Returns:
        Boolean mask. A path that touches the holdout is excluded.
    """
    epochs = np.asarray(epoch_s, dtype=np.int64)
    horizon_end = epochs + int(horizon_bars) * int(bar_length)
    mask = (epochs < int(holdout_start)) & (horizon_end < int(holdout_start))
    if horizon_ok is not None:
        mask = mask & np.asarray(horizon_ok, dtype=bool)
    return mask


def measure_label_grid(
    frame: pd.DataFrame,
    *,
    holdout_start: int,
    cost: float = ROUND_TRIP_COST,
) -> dict[str, Any]:
    """Score the theta and barrier grids on development rows only.

    Args:
        frame: Full OHLCV series. Holdout rows are not used as labels.
        holdout_start: Unix seconds of the first holdout bar.
        cost: Round-trip cost as a fraction of price.

    Returns:
        Candidate tables plus the selected theta and barrier pair.
    """
    close = frame["close"].to_numpy(dtype=np.float64)
    high = frame["high"].to_numpy(dtype=np.float64)
    low = frame["low"].to_numpy(dtype=np.float64)
    epochs = to_epoch_seconds(frame["time"])
    atr = causal_atr(high, low, close)
    positions = future_positions(epochs, bar_length=bar_seconds())
    horizon_ok = (positions >= 0).all(axis=1)
    usable = (
        development_supervised_mask(
            epochs,
            holdout_start=holdout_start,
            bar_length=bar_seconds(),
            horizon_ok=horizon_ok,
        )
        & np.isfinite(atr)
        & (atr > _EPS)
        & np.isfinite(close)
        & (close > _EPS)
    )
    indexes = np.flatnonzero(usable)
    end_close = np.full(len(frame), np.nan)
    for index in indexes.tolist():
        end_close[index] = close[int(positions[index, -1])]
    simple = end_close / close - 1.0
    atr_pct = atr / close

    theta_rows = [
        _score_theta(float(theta), simple, atr_pct, usable, cost) for theta in THETA_GRID
    ]
    barrier_rows = []
    for tp_mult, sl_mult in BARRIER_GRID:
        codes = _path_codes_for_multiples(
            close, high, low, atr, positions, usable, tp_mult, sl_mult
        )
        barrier_rows.append(
            _score_barrier(
                tp_mult,
                sl_mult,
                codes["long"],
                codes["short"],
                atr_pct,
                simple,
                usable,
                cost,
            )
        )
    return {
        "spec_version": SPEC_VERSION,
        "development_rows": int(usable.sum()),
        "round_trip_cost": float(cost),
        "theta": select_theta(theta_rows),
        "barrier": select_barrier(barrier_rows),
    }


def measure_direction_theta(
    frame: pd.DataFrame,
    *,
    holdout_start: int,
) -> dict[str, Any]:
    """Score the theta grid on development bars using class floors only.

    The 12-hour return is marked from the next-bar open to the horizon close.
    Cost is not a pass criterion.

    Args:
        frame: Full OHLCV series. Holdout rows are not used as labels.
        holdout_start: Unix seconds of the first embargo bar.

    Returns:
        Candidate table plus the selected theta.
    """
    close = frame["close"].to_numpy(dtype=np.float64)
    high = frame["high"].to_numpy(dtype=np.float64)
    low = frame["low"].to_numpy(dtype=np.float64)
    open_ = frame["open"].to_numpy(dtype=np.float64)
    epochs = to_epoch_seconds(frame["time"])
    atr = causal_atr(high, low, close)
    positions = future_positions(epochs, bar_length=bar_seconds())
    horizon_ok = (positions >= 0).all(axis=1)
    fill_index = positions[:, 0]
    fill_ok = fill_index >= 0
    entry = np.full(len(frame), np.nan, dtype=np.float64)
    entry[fill_ok] = open_[fill_index[fill_ok]]
    end_close = np.full(len(frame), np.nan, dtype=np.float64)
    usable = (
        development_supervised_mask(
            epochs,
            holdout_start=holdout_start,
            bar_length=bar_seconds(),
            horizon_ok=horizon_ok,
        )
        & fill_ok
        & np.isfinite(atr)
        & (atr > _EPS)
        & np.isfinite(entry)
        & (entry > _EPS)
    )
    for index in np.flatnonzero(usable).tolist():
        end_price = float(close[int(positions[index, -1])])
        if end_price > _EPS:
            end_close[index] = end_price
    simple = end_close / entry - 1.0
    atr_pct = atr / entry
    theta_rows = [
        _score_theta_class_floor(float(theta), simple, atr_pct, usable) for theta in THETA_GRID
    ]
    return {
        "development_rows": int(usable.sum()),
        "theta": select_theta_class_floor(theta_rows),
        "entry": "next_open",
    }


def select_theta_class_floor(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep the smallest theta whose three classes all meet the floor.

    Args:
        candidates: One row per grid value.

    Returns:
        The selected row, or ``selected: null`` when none pass.
    """
    passing = [dict(row) for row in candidates if row.get("passed")]
    if not passing:
        return {"selected": None, "reason": "no_theta_passed", "candidates": list(candidates)}
    best = min(passing, key=lambda row: float(row["theta"]))
    return {
        "selected": best,
        "reason": "smallest_theta_meeting_class_floor",
        "candidates": list(candidates),
    }


def render_labels_v4_yaml(report: Mapping[str, Any]) -> str:
    """Render the frozen v4 direction choice.

    Args:
        report: Output of :func:`measure_direction_theta`.

    Returns:
        YAML text.
    """
    theta = report["theta"]["selected"]
    theta_text = "null" if theta is None else f"{float(theta['theta']):.2f}"
    lines = [
        "# Chosen on development by the v4 class-floor rule. Cost is not used.",
        f"spec_version: {report.get('spec_version', 'forecast-30m-h24-v4')}",
        "entry: next_open",
        f"theta: {theta_text}",
        f"theta_reason: {report['theta']['reason']}",
        f"development_rows: {int(report['development_rows'])}",
        "",
    ]
    return "\n".join(lines)


def select_theta(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the pre-registered theta rule.

    Args:
        candidates: One row per grid value, including a ``passed`` flag.

    Returns:
        The selected row, or ``selected: null`` when none pass.
    """
    passing = [dict(row) for row in candidates if row.get("passed")]
    if not passing:
        return {"selected": None, "reason": "no_theta_passed", "candidates": list(candidates)}
    best = min(passing, key=lambda row: float(row["theta"]))
    return {
        "selected": best,
        "reason": "smallest_band_covering_cost",
        "candidates": list(candidates),
    }


def select_barrier(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the pre-registered barrier rule.

    Args:
        candidates: One row per ``(tp, sl)`` pair.

    Returns:
        The selected row, or ``selected: null`` when none pass.
    """
    passing = [dict(row) for row in candidates if row.get("passed")]
    if not passing:
        return {
            "selected": None,
            "reason": "no_barrier_passed",
            "candidates": list(candidates),
        }
    asymmetric = [
        row for row in passing if float(row["tp_mult"]) != float(row["sl_mult"])
    ]
    if not asymmetric:
        return {
            "selected": None,
            "reason": "symmetric_barrier_is_one_path",
            "candidates": list(candidates),
        }
    best = max(asymmetric, key=lambda row: float(row["no_skill_expectancy"]))
    return {
        "selected": best,
        "reason": "highest_no_skill_expectancy",
        "candidates": list(candidates),
    }


def score_fixed_percent_barrier(
    long_codes: np.ndarray,
    short_codes: np.ndarray,
    simple: np.ndarray,
    usable: np.ndarray,
    *,
    tp_pct: float,
    sl_pct: float,
    cost: float,
) -> dict[str, Any]:
    """Score the pre-registered fixed-percent barrier on development events.

    Args:
        long_codes: Long path codes aligned to the series.
        short_codes: Short path codes aligned to the series.
        simple: Signed simple returns from the fill to the horizon close.
        usable: Development-event mask.
        tp_pct: Take-profit as a fraction of the fill.
        sl_pct: Stop as a fraction of the fill.
        cost: Round-trip cost as a fraction of price.

    Returns:
        The same fields as the ATR barrier screen, with a single candidate.
    """
    ones = np.ones(len(simple), dtype=np.float64)
    row = _score_barrier(
        tp_pct,
        sl_pct,
        long_codes,
        short_codes,
        ones,
        simple,
        usable,
        cost,
    )
    row["tp_mult"] = None
    row["sl_mult"] = None
    row["tp_pct"] = float(tp_pct)
    row["sl_pct"] = float(sl_pct)
    row["median_tp_pct"] = float(tp_pct)
    row["median_sl_pct"] = float(sl_pct)
    return row


def render_labels_v3_yaml(report: Mapping[str, Any]) -> str:
    """Render the frozen v3 event and barrier choice.

    Args:
        report: Output of the v3 barrier screen.

    Returns:
        YAML text. A failed screen still records the registered numbers.
    """
    barrier = report.get("barrier") or {}
    selected = barrier.get("selected")
    passed = bool(selected is not None and selected.get("passed"))
    lines = [
        "# Chosen by the pre-registered v3 event rule. Not a grid search.",
        f"spec_version: {report['spec_version']}",
        "entry: next_open",
        f"cusum_threshold: {float(report['cusum_threshold']):.2f}",
        f"tp_pct: {float(report['tp_pct']):.2f}",
        f"sl_pct: {float(report['sl_pct']):.2f}",
        f"policy_threshold: {float(report['policy_threshold']):.2f}",
        f"breakeven_precision: {float(report['breakeven_precision']):.2f}",
        f"round_trip_cost: {float(report['round_trip_cost']):.6f}",
        f"development_events: {int(report['development_events'])}",
        f"barrier_passed: {str(passed).lower()}",
        f"barrier_reason: {barrier.get('reason', 'unscored')}",
        "",
    ]
    return "\n".join(lines)


def render_labels_yaml(report: Mapping[str, Any]) -> str:
    """Render the frozen label choice.

    Args:
        report: Output of :func:`measure_label_grid`.

    Returns:
        YAML text. Null selections are written as ``null``.
    """
    theta = report["theta"]["selected"]
    barrier = report["barrier"]["selected"]
    theta_text = "null" if theta is None else f"{float(theta['theta']):.2f}"
    if barrier is None:
        tp_text = "null"
        sl_text = "null"
    else:
        tp_text = f"{float(barrier['tp_mult']):.2f}"
        sl_text = f"{float(barrier['sl_mult']):.2f}"
    lines = [
        "# Chosen on the development prefix by the v2 rules.",
        f"spec_version: {SPEC_VERSION}",
        f"theta: {theta_text}",
        f"theta_reason: {report['theta']['reason']}",
        f"tp_mult: {tp_text}",
        f"sl_mult: {sl_text}",
        f"barrier_reason: {report['barrier']['reason']}",
        f"round_trip_cost: {float(report['round_trip_cost']):.6f}",
        f"development_rows: {int(report['development_rows'])}",
        "entry: close",
        "ambiguous_policy: retain_path_code_and_drop_from_binary_heads",
        "",
    ]
    return "\n".join(lines)


def _fill_ok(positions: np.ndarray, open_: np.ndarray, entry: str) -> np.ndarray:
    """Rows whose fill price exists and is positive."""
    if entry != "next_open":
        return np.ones(len(open_), dtype=bool)
    fill_index = positions[:, 0]
    ok = np.zeros(len(open_), dtype=bool)
    valid = fill_index >= 0
    ok[valid] = np.isfinite(open_[fill_index[valid]]) & (open_[fill_index[valid]] > _EPS)
    return ok


def _path_with_fill_gap(
    entry_price: float,
    future_high: np.ndarray,
    future_low: np.ndarray,
    take_profit: float,
    stop: float,
    *,
    short: bool,
) -> int:
    """Classify a gap at the fill open, then walk the remaining path."""
    if short:
        profit_hit = entry_price <= take_profit
        stop_hit = entry_price >= stop
    else:
        profit_hit = entry_price >= take_profit
        stop_hit = entry_price <= stop
    if profit_hit and stop_hit:
        return AMBIGUOUS
    if profit_hit:
        return TP_FIRST
    if stop_hit:
        return SL_FIRST
    return classify_path(future_high, future_low, take_profit, stop, short=short)


def _binary_target(codes: np.ndarray) -> np.ndarray:
    out = np.full(codes.shape, np.nan, dtype=np.float64)
    labeled = (codes >= 0) & (codes != AMBIGUOUS)
    out[labeled & (codes == TP_FIRST)] = 1.0
    out[labeled & (codes != TP_FIRST)] = 0.0
    return out


def _score_theta(
    theta: float,
    simple: np.ndarray,
    atr_pct: np.ndarray,
    usable: np.ndarray,
    cost: float,
) -> dict[str, Any]:
    band = theta * atr_pct
    rows = usable & np.isfinite(simple) & np.isfinite(band)
    returns = simple[rows]
    bands = band[rows]
    direction = np.full(returns.shape, NEUTRAL, dtype=np.int64)
    direction[returns > bands] = BULLISH
    direction[returns < -bands] = BEARISH
    rates = {}
    means = {}
    reasons: list[str] = []
    for code, name in enumerate(DIRECTION_NAMES):
        rates[name] = float(np.mean(direction == code)) if len(direction) else 0.0
        class_returns = returns[direction == code]
        means[name] = float(class_returns.mean()) if len(class_returns) else None
        if rates[name] < MINORITY_FLOOR:
            reasons.append(f"{name.lower()}_below_floor")
    bull = means["BULLISH"]
    bear = means["BEARISH"]
    gap = None if bull is None or bear is None else float(bull - bear)
    median_band = float(np.median(bands)) if len(bands) else None
    if bull is None or bull <= cost:
        reasons.append("bullish_mean_not_above_cost")
    if bear is None or bear >= -cost:
        reasons.append("bearish_mean_not_below_cost")
    if gap is None or median_band is None or gap < median_band:
        reasons.append("return_gap_below_band")
    minimum_band = MIN_NEUTRAL_COST_MULTIPLE * cost
    if median_band is None or median_band < minimum_band:
        reasons.append("neutral_band_below_cost")
    return {
        "theta": theta,
        "rows": int(rows.sum()),
        "class_rates": rates,
        "mean_return": means,
        "return_gap": gap,
        "median_band": median_band,
        "passed": not reasons,
        "fail_reasons": reasons,
    }


def _score_theta_class_floor(
    theta: float,
    simple: np.ndarray,
    atr_pct: np.ndarray,
    usable: np.ndarray,
) -> dict[str, Any]:
    """Theta pass rule used by v4: class floors only."""
    band = theta * atr_pct
    rows = usable & np.isfinite(simple) & np.isfinite(band)
    returns = simple[rows]
    bands = band[rows]
    direction = np.full(returns.shape, NEUTRAL, dtype=np.int64)
    direction[returns > bands] = BULLISH
    direction[returns < -bands] = BEARISH
    rates = {}
    means = {}
    reasons: list[str] = []
    for code, name in enumerate(DIRECTION_NAMES):
        rates[name] = float(np.mean(direction == code)) if len(direction) else 0.0
        class_returns = returns[direction == code]
        means[name] = float(class_returns.mean()) if len(class_returns) else None
        if rates[name] < MINORITY_FLOOR:
            reasons.append(f"{name.lower()}_below_floor")
    bull = means["BULLISH"]
    bear = means["BEARISH"]
    gap = None if bull is None or bear is None else float(bull - bear)
    median_band = float(np.median(bands)) if len(bands) else None
    return {
        "theta": theta,
        "rows": int(rows.sum()),
        "class_rates": rates,
        "mean_return": means,
        "return_gap": gap,
        "median_band": median_band,
        "passed": not reasons,
        "fail_reasons": reasons,
    }


def _score_barrier(
    tp_mult: float,
    sl_mult: float,
    long_codes: np.ndarray,
    short_codes: np.ndarray,
    atr_pct: np.ndarray,
    simple: np.ndarray,
    usable: np.ndarray,
    cost: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    side_stats = {}
    path_floors = []
    signed = {"long": simple, "short": -simple}
    codes_by_side = {"long": long_codes, "short": short_codes}
    expectancies = []
    for name in ("long", "short"):
        codes = codes_by_side[name]
        labeled = usable & (codes >= 0)
        stats = _path_stats(codes[labeled])
        side_stats[name] = stats
        if stats["min_path_rate"] < MIN_PATH_RATE:
            reasons.append(f"{name}_path_rate_below_floor")
        if stats["ambiguous_share"] > MAX_AMBIGUOUS_SHARE:
            reasons.append(f"{name}_ambiguous_share")
        path_floors.append(stats["min_path_rate"])
        expectancies.append(
            _no_skill_expectancy(
                codes, atr_pct, signed[name], usable, tp_mult, sl_mult, cost
            )
        )
    finite_expectancy = [value for value in expectancies if np.isfinite(value)]
    no_skill = float(np.mean(finite_expectancy)) if finite_expectancy else None
    median_tp = float(np.median((tp_mult * atr_pct)[usable])) if usable.any() else None
    median_sl = float(np.median((sl_mult * atr_pct)[usable])) if usable.any() else None
    ratio = None if median_tp is None or cost <= 0 else float(median_tp / cost)
    breakeven = None
    if median_tp is not None and median_sl is not None and (median_tp + median_sl) > _EPS:
        breakeven = float((median_sl + cost) / (median_tp + median_sl))
    tp_rate = min(float(side_stats[name]["tp_first_rate"]) for name in ("long", "short"))
    skill_gap = None if breakeven is None else float(tp_rate - breakeven)
    if no_skill is None or no_skill < -MAX_NO_SKILL_LOSS:
        reasons.append("no_skill_expectancy_too_negative")
    if skill_gap is None or skill_gap < -MAX_PRECISION_GAP:
        reasons.append("tp_rate_far_below_breakeven")
    return {
        "tp_mult": float(tp_mult),
        "sl_mult": float(sl_mult),
        "median_tp_pct": median_tp,
        "median_sl_pct": median_sl,
        "tp_cost_ratio": ratio,
        "breakeven_precision": breakeven,
        "no_skill_expectancy": no_skill,
        "skill_gap": skill_gap,
        "min_path_rate": float(min(path_floors) if path_floors else 0.0),
        "sides": side_stats,
        "passed": not reasons,
        "fail_reasons": reasons,
    }


def _no_skill_expectancy(
    codes: np.ndarray,
    atr_pct: np.ndarray,
    signed_return: np.ndarray,
    usable: np.ndarray,
    tp_mult: float,
    sl_mult: float,
    cost: float,
) -> float:
    """Mean marked result of taking every labeled path on one side."""
    labeled = usable & (codes >= 0) & np.isfinite(signed_return)
    if not labeled.any():
        return float("nan")
    path = codes[labeled]
    tp_pct = tp_mult * atr_pct[labeled]
    sl_pct = sl_mult * atr_pct[labeled]
    outcome = signed_return[labeled]
    pnl = np.full(path.shape, np.nan, dtype=np.float64)
    take_profit = path == TP_FIRST
    stop = (path == SL_FIRST) | (path == AMBIGUOUS)
    expiry = path == EXPIRY
    pnl[take_profit] = tp_pct[take_profit] - cost
    pnl[stop] = -sl_pct[stop] - cost
    pnl[expiry] = outcome[expiry] - cost
    return float(np.nanmean(pnl))


def _path_stats(codes: np.ndarray) -> dict[str, float]:
    total = max(int(codes.size), 1)
    counts = {name: int(np.sum(codes == code)) for code, name in enumerate(PATH_NAMES)}
    tp_count = counts["TP_FIRST"]
    ambiguous = counts["AMBIGUOUS"]
    decisive = tp_count + ambiguous
    share = 0.0 if decisive == 0 else ambiguous / decisive
    rates = {name: counts[name] / total for name in ("TP_FIRST", "SL_FIRST", "EXPIRY")}
    return {
        "counts": counts,
        "min_path_rate": float(min(rates.values())),
        "ambiguous_share": float(share),
        "tp_first_rate": float(rates["TP_FIRST"]),
    }


def _path_codes_for_multiples(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr: np.ndarray,
    positions: np.ndarray,
    usable: np.ndarray,
    tp_mult: float,
    sl_mult: float,
) -> dict[str, np.ndarray]:
    n = len(close)
    long_codes = np.full(n, UNLABELED, dtype=np.int64)
    short_codes = np.full(n, UNLABELED, dtype=np.int64)
    for index in np.flatnonzero(usable).tolist():
        future = positions[index]
        entry = float(close[index])
        width = float(atr[index])
        future_high = high[future]
        future_low = low[future]
        long_codes[index] = classify_path(
            future_high,
            future_low,
            entry + tp_mult * width,
            entry - sl_mult * width,
            short=False,
        )
        short_codes[index] = classify_path(
            future_high,
            future_low,
            entry - tp_mult * width,
            entry + sl_mult * width,
            short=True,
        )
    return {"long": long_codes, "short": short_codes}
