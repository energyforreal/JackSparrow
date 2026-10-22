"""Forecast metrics, Gate 4, and the cost-aware policy.

Primary scores average the 24 non-overlapping phases of a 24-bar horizon.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, log_loss

from research.forecast_30m.contract import (
    AMBIGUOUS,
    BEARISH,
    BULLISH,
    COST_STRESS,
    EXPIRY,
    GATE5_MAX_DRAWDOWN,
    GATE5_MIN_TRADES,
    HORIZON_BARS,
    MIN_PHASE_ROWS,
    MIN_TP_COST_RATIO,
    NEUTRAL,
    ROUND_TRIP_COST,
    SL_FIRST,
    THRESHOLD_GRID,
    TP_FIRST,
)


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Macro-F1 over the three direction classes.

    Args:
        y_true: Integer labels.
        y_pred: Integer predictions.

    Returns:
        Macro-F1. Missing classes score zero for that class.
    """
    return float(
        f1_score(
            y_true,
            y_pred,
            labels=[0, 1, 2],
            average="macro",
            zero_division=0,
        )
    )


def mean_absolute_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """MAE of a return forecast."""
    return float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred))))


def brier_score(y_true: np.ndarray, probability: np.ndarray) -> float:
    """Brier score of a binary probability."""
    return float(np.mean((np.asarray(probability) - np.asarray(y_true)) ** 2))


def direction_log_loss(y_true: np.ndarray, probability: np.ndarray) -> float:
    """Multiclass log loss. Probabilities are clipped and renormalized."""
    clipped = np.clip(np.asarray(probability, dtype=np.float64), 1e-6, None)
    clipped = clipped / clipped.sum(axis=1, keepdims=True)
    return float(log_loss(np.asarray(y_true).astype(int), clipped, labels=[0, 1, 2]))


def phase_average(
    bar_index: np.ndarray,
    metric: Callable[[np.ndarray], float],
    *,
    horizon_bars: int = HORIZON_BARS,
    min_rows: int = MIN_PHASE_ROWS,
) -> float:
    """Average a metric over non-overlapping phases.

    Args:
        bar_index: Original bar position of each scored row.
        metric: Function of a boolean phase mask. It returns one score.
        horizon_bars: Phase count. Equal to the forecast horizon.
        min_rows: Phases with fewer rows are skipped.

    Returns:
        Mean of the available phase scores.

    Raises:
        ValueError: If fewer than half of the phases qualify.
    """
    scores = []
    for offset in range(int(horizon_bars)):
        mask = (np.asarray(bar_index) % int(horizon_bars)) == offset
        if int(mask.sum()) < int(min_rows):
            continue
        scores.append(float(metric(mask)))
    if len(scores) < int(horizon_bars) // 2:
        raise ValueError("not enough non-overlapping phase rows to score")
    return float(np.mean(scores))


def gate4_passed(
    model_scores: Sequence[float],
    baseline_scores: Sequence[float],
    *,
    higher_is_better: bool,
    min_delta: float = 0.0,
    relative: bool = False,
) -> dict[str, Any]:
    """Require a material improvement on at least two folds.

    Args:
        model_scores: One primary score per walk-forward fold.
        baseline_scores: Baseline score on the same folds.
        higher_is_better: Expectancy is higher-better. Log loss and MAE are not.
        min_delta: Minimum improvement. Absolute, unless ``relative`` is set.
        relative: When true, ``min_delta`` is a fraction of the baseline score.

    Returns:
        Win count and the pass flag. A non-finite score is not a win.
    """
    wins = 0
    for model, baseline in zip(model_scores, baseline_scores, strict=True):
        if not np.isfinite(model) or not np.isfinite(baseline):
            continue
        if relative:
            required = baseline * (1.0 + min_delta if higher_is_better else 1.0 - min_delta)
        elif higher_is_better:
            required = baseline + min_delta
        else:
            required = baseline - min_delta
        if higher_is_better and model > required:
            wins += 1
        elif not higher_is_better and model < required:
            wins += 1
    return {"wins": wins, "folds": len(model_scores), "passed": wins >= 2}


def trade_return(
    path_code: int,
    *,
    side: str,
    tp_pct: float,
    sl_pct: float,
    forward_return: float,
    cost: float,
) -> float:
    """Marked result of one non-overlapping barrier trade.

    Ambiguous paths are scored as a stop. The stored label remains ambiguous.

    Args:
        path_code: Path code for the traded side.
        side: ``long`` or ``short``.
        tp_pct: Take-profit distance as a fraction of price.
        sl_pct: Stop distance as a fraction of price.
        forward_return: Close-to-close simple return.
        cost: Round-trip cost as a fraction of price.

    Returns:
        Net return for a unit position.
    """
    expiry = forward_return if side == "long" else -forward_return
    if path_code == TP_FIRST:
        gross = tp_pct
    elif path_code in (SL_FIRST, AMBIGUOUS):
        gross = -sl_pct
    elif path_code == EXPIRY:
        gross = expiry
    else:
        return np.nan
    return float(gross - cost)


def phase_policy_stats(
    frame: pd.DataFrame,
    *,
    long_probability: np.ndarray,
    short_probability: np.ndarray,
    long_threshold: float,
    short_threshold: float,
    cost: float,
) -> list[dict[str, float]]:
    """Score each non-overlapping entry phase.

    Args:
        frame: Rows with path codes, barrier distances, return, and ``bar_index``.
        long_probability: Calibrated long TP-first probability.
        short_probability: Calibrated short TP-first probability.
        long_threshold: Minimum long probability.
        short_threshold: Minimum short probability.
        cost: Round-trip cost.

    Returns:
        One stats dict per phase that has at least one decision row.
    """
    stats = []
    bar_index = frame["bar_index"].to_numpy(dtype=np.int64)
    for offset in range(HORIZON_BARS):
        positions = np.flatnonzero((bar_index % HORIZON_BARS) == offset)
        if positions.size < MIN_PHASE_ROWS:
            continue
        subset = frame.iloc[positions].reset_index(drop=True)
        returns = _policy_returns(
            subset,
            long_probability[positions],
            short_probability[positions],
            long_threshold,
            short_threshold,
            cost,
        )
        finite = returns[np.isfinite(returns)]
        stats.append(_return_stats(finite, decisions=int(positions.size)))
    return stats


def choose_thresholds(
    frame: pd.DataFrame,
    *,
    long_probability: np.ndarray,
    short_probability: np.ndarray,
    cost: float = ROUND_TRIP_COST,
) -> dict[str, Any]:
    """Pick thresholds on a calibration block.

    Args:
        frame: Calibration rows only.
        long_probability: Probabilities aligned to ``frame``.
        short_probability: Probabilities aligned to ``frame``.
        cost: Round-trip cost.

    Returns:
        Chosen thresholds. A pair must clear 20 median trades, positive
        expectancy, and a profit factor above 1 on the phases that traded.
    """
    best: dict[str, Any] | None = None
    saw_enough_trades = False
    for long_threshold in THRESHOLD_GRID:
        for short_threshold in THRESHOLD_GRID:
            phases = phase_policy_stats(
                frame,
                long_probability=long_probability,
                short_probability=short_probability,
                long_threshold=float(long_threshold),
                short_threshold=float(short_threshold),
                cost=cost,
            )
            if not phases:
                continue
            trades = _median_number(phases, "trades", traded_only=False)
            expectancy = _median_number(phases, "expectancy", traded_only=True)
            profit_factor = _median_number(phases, "profit_factor", traded_only=True)
            if trades is None or trades < GATE5_MIN_TRADES:
                continue
            saw_enough_trades = True
            if expectancy is None or expectancy <= 0.0:
                continue
            if profit_factor is None or profit_factor <= 1.0:
                continue
            candidate = {
                "long_threshold": float(long_threshold),
                "short_threshold": float(short_threshold),
                "median_expectancy": expectancy,
                "median_profit_factor": profit_factor,
                "median_trades": trades,
            }
            if best is None or expectancy > float(best["median_expectancy"]):
                best = candidate
    if best is None:
        reason = (
            "no_positive_calibration_expectancy"
            if saw_enough_trades
            else "no_threshold_with_enough_trades"
        )
        return {"selected": None, "reason": reason}
    best["reason"] = "max_median_calibration_expectancy"
    return {"selected": best, "reason": best["reason"]}


def gate5_passed(
    frame: pd.DataFrame,
    probabilities: Mapping[str, np.ndarray],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """Apply the pre-registered economic gate.

    Args:
        frame: Holdout decision rows.
        probabilities: ``long`` and ``short`` calibrated probabilities.
        thresholds: ``long_threshold`` and ``short_threshold``.

    Returns:
        Per-cost phase medians and the pass flag.
    """
    costs = {}
    for multiplier in COST_STRESS:
        phases = phase_policy_stats(
            frame,
            long_probability=probabilities["long"],
            short_probability=probabilities["short"],
            long_threshold=float(thresholds["long_threshold"]),
            short_threshold=float(thresholds["short_threshold"]),
            cost=ROUND_TRIP_COST * float(multiplier),
        )
        costs[str(multiplier)] = _median_phase(phases)
    base = costs["1.0"]
    stressed = costs["1.5"]
    reasons = []
    if base["trades"] is None or base["trades"] <= GATE5_MIN_TRADES:
        reasons.append("too_few_trades")
    if base["expectancy"] is None or base["expectancy"] <= 0.0:
        reasons.append("expectancy_not_positive")
    if stressed["expectancy"] is None or stressed["expectancy"] <= 0.0:
        reasons.append("fragile_to_higher_cost")
    if base["profit_factor"] is None or base["profit_factor"] <= 1.0:
        reasons.append("profit_factor_not_above_one")
    drawdown = base["max_drawdown"]
    if drawdown is not None and drawdown < GATE5_MAX_DRAWDOWN:
        reasons.append("drawdown_beyond_limit")
    return {"passed": not reasons, "reasons": reasons, "costs": costs}


def binary_log_loss(y_true: np.ndarray, probability: np.ndarray) -> float:
    """Log loss of a binary probability, clipped away from 0 and 1."""
    clipped = np.clip(probability, 1e-6, 1.0 - 1e-6)
    return float(log_loss(y_true, np.column_stack([1.0 - clipped, clipped]), labels=[0, 1]))


def _policy_returns(
    frame: pd.DataFrame,
    long_probability: np.ndarray,
    short_probability: np.ndarray,
    long_threshold: float,
    short_threshold: float,
    cost: float,
) -> np.ndarray:
    returns = np.full(len(frame), np.nan, dtype=np.float64)
    tp_pct = frame["tp_pct"].to_numpy(dtype=np.float64)
    sl_pct = frame["sl_pct"].to_numpy(dtype=np.float64)
    forward = frame["forward_return_24"].to_numpy(dtype=np.float64)
    long_code = frame["long_path_code"].to_numpy(dtype=np.int64)
    short_code = frame["short_path_code"].to_numpy(dtype=np.int64)
    tradable = tp_pct >= MIN_TP_COST_RATIO * cost
    for index in range(len(frame)):
        if not tradable[index]:
            continue
        take_long = (
            long_probability[index] >= long_threshold
            and long_probability[index] > short_probability[index]
        )
        take_short = (
            short_probability[index] >= short_threshold
            and short_probability[index] > long_probability[index]
        )
        if take_long:
            returns[index] = trade_return(
                int(long_code[index]),
                side="long",
                tp_pct=float(tp_pct[index]),
                sl_pct=float(sl_pct[index]),
                forward_return=float(forward[index]),
                cost=cost,
            )
        elif take_short:
            returns[index] = trade_return(
                int(short_code[index]),
                side="short",
                tp_pct=float(tp_pct[index]),
                sl_pct=float(sl_pct[index]),
                forward_return=float(forward[index]),
                cost=cost,
            )
    return returns


def _return_stats(trade_returns: np.ndarray, *, decisions: int) -> dict[str, float]:
    if trade_returns.size == 0:
        return {
            "trades": 0.0,
            "decisions": float(decisions),
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
        }
    wins = float(trade_returns[trade_returns > 0.0].sum())
    losses = float(-trade_returns[trade_returns < 0.0].sum())
    if losses == 0.0:
        profit_factor = float("inf") if wins > 0.0 else 0.0
    else:
        profit_factor = wins / losses
    equity = np.cumsum(trade_returns)
    drawdown = float((equity - np.maximum.accumulate(equity)).min())
    return {
        "trades": float(trade_returns.size),
        "decisions": float(decisions),
        "expectancy": float(trade_returns.mean()),
        "profit_factor": float(profit_factor),
        "max_drawdown": drawdown,
    }


def barrier_expectancy(
    frame: pd.DataFrame,
    probability: np.ndarray,
    *,
    side: str,
    breakeven: float,
    cost: float = ROUND_TRIP_COST,
) -> float:
    """Mean phase expectancy of trades whose probability clears breakeven.

    Phases with no trades are left out of the average. The score is undefined
    when the fold does not place the minimum number of trades.

    Args:
        frame: Rows with path codes, distances, the forward return, and ``bar_index``.
        probability: Take-profit probability aligned to ``frame``.
        side: ``long`` or ``short``.
        breakeven: Precision required to clear the barrier after cost.
        cost: Round-trip cost.

    Returns:
        Mean expectancy of the traded phases, or NaN when too few trades exist.
    """
    if not np.isfinite(breakeven):
        return float("nan")
    code_column = "long_path_code" if side == "long" else "short_path_code"
    codes = frame[code_column].to_numpy(dtype=np.int64)
    tp_pct = frame["tp_pct"].to_numpy(dtype=np.float64)
    sl_pct = frame["sl_pct"].to_numpy(dtype=np.float64)
    forward = frame["forward_return_24"].to_numpy(dtype=np.float64)
    bars = frame["bar_index"].to_numpy(dtype=np.int64)
    take = np.asarray(probability, dtype=np.float64) >= float(breakeven)
    phase_scores = []
    trades = 0
    for offset in range(HORIZON_BARS):
        mask = (bars % HORIZON_BARS) == offset
        if int(mask.sum()) < MIN_PHASE_ROWS:
            continue
        chosen = np.flatnonzero(mask & take)
        if chosen.size == 0:
            continue
        returns = [
            trade_return(
                int(codes[index]),
                side=side,
                tp_pct=float(tp_pct[index]),
                sl_pct=float(sl_pct[index]),
                forward_return=float(forward[index]),
                cost=cost,
            )
            for index in chosen.tolist()
        ]
        finite = [value for value in returns if np.isfinite(value)]
        if not finite:
            continue
        phase_scores.append(float(np.mean(finite)))
        trades += len(finite)
    if trades < GATE5_MIN_TRADES or len(phase_scores) < HORIZON_BARS // 2:
        return float("nan")
    return float(np.mean(phase_scores))


def _median_number(
    phases: Sequence[Mapping[str, float]],
    key: str,
    *,
    traded_only: bool,
) -> float | None:
    """Median of one phase field. Empty-trade phases stay out of payoff medians."""
    chosen = phases
    if traded_only:
        chosen = [row for row in phases if float(row["trades"]) > 0.0]
    if not chosen:
        return None
    values = [
        float(row[key])
        for row in chosen
        if np.isfinite(row[key]) or float(row[key]) == float("inf")
    ]
    if not values:
        return None
    return float(np.median(values))


def one_position_policy(
    frame: pd.DataFrame,
    long_probability: np.ndarray,
    short_probability: np.ndarray,
    *,
    threshold: float,
    cost: float = ROUND_TRIP_COST,
    horizon_bars: int = HORIZON_BARS,
    series_length: int | None = None,
    series_origin: int = 0,
) -> dict[str, Any]:
    """Take one side per event. Skip events while a position is open.

    Args:
        frame: Event rows with path codes, distances, return, and ``bar_index``.
        long_probability: Calibrated or raw long TP-first probability.
        short_probability: Short TP-first probability, aligned to ``frame``.
        threshold: Minimum probability on the chosen side.
        cost: Round-trip cost as a fraction of price.
        horizon_bars: Bars a position occupies, including the fill bar.
        series_length: When set, overlay each trade's PnL on a bar series of
            this length. Signal ``bar_index`` is shifted by ``series_origin``.
        series_origin: ``bar_index`` of the first slot in the overlay series.

    Returns:
        Trade count, expectancy, profit factor, drawdown, per-trade returns,
        and the optional bar-level overlay.
    """
    order = np.argsort(frame["bar_index"].to_numpy(dtype=np.int64), kind="stable")
    bar_index = frame["bar_index"].to_numpy(dtype=np.int64)
    long_p = np.asarray(long_probability, dtype=np.float64)
    short_p = np.asarray(short_probability, dtype=np.float64)
    busy_until = -10**9
    pnls: list[float] = []
    overlay: np.ndarray | None = None
    if series_length is not None:
        overlay = np.zeros(int(series_length), dtype=np.float64)
    for position in order.tolist():
        signal_bar = int(bar_index[position])
        if signal_bar < busy_until:
            continue
        take_long = (
            long_p[position] >= threshold and long_p[position] > short_p[position]
        )
        take_short = (
            short_p[position] >= threshold and short_p[position] > long_p[position]
        )
        if not take_long and not take_short:
            continue
        side = "long" if take_long else "short"
        code_column = "long_path_code" if side == "long" else "short_path_code"
        pnl = trade_return(
            int(frame.iloc[position][code_column]),
            side=side,
            tp_pct=float(frame.iloc[position]["tp_pct"]),
            sl_pct=float(frame.iloc[position]["sl_pct"]),
            forward_return=float(frame.iloc[position]["forward_return_24"]),
            cost=cost,
        )
        if not np.isfinite(pnl):
            continue
        pnls.append(float(pnl))
        busy_until = signal_bar + int(horizon_bars)
        if overlay is not None:
            slot = signal_bar - int(series_origin)
            if 0 <= slot < overlay.size:
                overlay[slot] = float(pnl)
    stats = _return_stats(np.asarray(pnls, dtype=np.float64), decisions=int(len(frame)))
    stats["bar_returns"] = overlay
    stats["trade_returns"] = np.asarray(pnls, dtype=np.float64)
    return stats


def buy_and_hold_bar_returns(
    open_first: float,
    close_last: float,
    *,
    n_bars: int,
    cost: float = ROUND_TRIP_COST,
) -> np.ndarray:
    """Place the marked buy-and-hold result on the first bar of a series.

    Args:
        open_first: Fill price at the first confirmation open.
        close_last: Exit price at the last confirmation close.
        n_bars: Length of the overlay series.
        cost: One round trip charged on the position.

    Returns:
        Array of length ``n_bars``. Slot 0 holds the net result. The rest are 0.
    """
    series = np.zeros(int(n_bars), dtype=np.float64)
    if n_bars < 1 or open_first <= 0.0 or close_last <= 0.0:
        return series
    series[0] = float(close_last / open_first - 1.0 - cost)
    return series


def circular_block_bootstrap_means(
    series: np.ndarray,
    *,
    block_length: int,
    draws: int,
    seed: int,
) -> np.ndarray:
    """Circular block bootstrap of the mean of a bar-level return series.

    Args:
        series: Aligned bar returns. Zeros are kept.
        block_length: Number of consecutive bars in each block.
        draws: Number of resampled series.
        seed: Generator seed.

    Returns:
        One mean per draw.

    Raises:
        ValueError: If the series is empty or the block length is not positive.
    """
    values = np.asarray(series, dtype=np.float64)
    if values.size == 0:
        raise ValueError("bootstrap series is empty")
    if block_length < 1:
        raise ValueError("block_length must be positive")
    length = int(values.size)
    width = min(int(block_length), length)
    wrapped = np.concatenate([values, values[:width]])
    rng = np.random.default_rng(int(seed))
    n_blocks = int(np.ceil(length / width))
    means = np.empty(int(draws), dtype=np.float64)
    for draw in range(int(draws)):
        starts = rng.integers(0, length, size=n_blocks)
        sample = np.concatenate([wrapped[int(start) : int(start) + width] for start in starts])
        means[draw] = float(sample[:length].mean())
    return means


def confirmation_gate(
    policy_bar_returns: np.ndarray,
    buy_and_hold: np.ndarray,
    *,
    trades: int,
    expectancy: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
    min_trades: int = GATE5_MIN_TRADES,
    max_drawdown_limit: float = GATE5_MAX_DRAWDOWN,
    block_length: int,
    draws: int,
    seed: int,
    alpha: float,
) -> dict[str, Any]:
    """Apply the pre-registered confirmation tests.

    Args:
        policy_bar_returns: Overlay of trade PnL on confirmation bars.
        buy_and_hold: Overlay of the one-shot long return on the same bars.
        trades: Number of filled confirmation trades.
        expectancy: Mean trade return.
        profit_factor: Gross wins over gross losses.
        max_drawdown: Minimum cumulative trade equity.
        min_trades: Floor that maps to ``insufficient_confirmation_window``.
        max_drawdown_limit: Worst allowed drawdown.
        block_length: Bootstrap block size in bars.
        draws: Bootstrap replications.
        seed: Bootstrap seed.
        alpha: One-sided quantile. The mean must sit above zero and above
            buy-and-hold at this tail.

    Returns:
        Pass flag, reasons, and bootstrap quantiles. Fewer than ``min_trades``
        trades is not a pass and names the confirmation window as too short.
    """
    if trades < int(min_trades):
        return {
            "passed": False,
            "reason": "insufficient_confirmation_window",
            "reasons": ["insufficient_confirmation_window"],
            "trades": int(trades),
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
        }
    reasons: list[str] = []
    if expectancy is None or not np.isfinite(expectancy) or expectancy <= 0.0:
        reasons.append("expectancy_not_positive")
    if not _profit_factor_clears(profit_factor):
        reasons.append("profit_factor_not_above_one")
    if max_drawdown is not None and max_drawdown < max_drawdown_limit:
        reasons.append("drawdown_beyond_limit")
    policy_means = circular_block_bootstrap_means(
        policy_bar_returns,
        block_length=block_length,
        draws=draws,
        seed=seed,
    )
    difference = np.asarray(policy_bar_returns, dtype=np.float64) - np.asarray(
        buy_and_hold, dtype=np.float64
    )
    diff_means = circular_block_bootstrap_means(
        difference,
        block_length=block_length,
        draws=draws,
        seed=seed,
    )
    policy_quantile = float(np.quantile(policy_means, float(alpha)))
    diff_quantile = float(np.quantile(diff_means, float(alpha)))
    if policy_quantile <= 0.0:
        reasons.append("bootstrap_not_above_zero")
    if diff_quantile <= 0.0:
        reasons.append("bootstrap_not_above_buy_and_hold")
    return {
        "passed": not reasons,
        "reason": None if not reasons else reasons[0],
        "reasons": reasons,
        "trades": int(trades),
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "bootstrap_policy_quantile": policy_quantile,
        "bootstrap_diff_quantile": diff_quantile,
        "bootstrap_draws": int(draws),
        "bootstrap_block_bars": int(block_length),
    }


def development_policy_gate(
    stats: Mapping[str, Any],
    *,
    min_trades: int = GATE5_MIN_TRADES,
) -> dict[str, Any]:
    """Walk-forward economic gate for the one-position policy.

    Args:
        stats: Output of :func:`one_position_policy`.
        min_trades: Minimum filled trades across the walk-forward rows.

    Returns:
        Pass flag and fail reasons.
    """
    trades = int(stats.get("trades") or 0)
    expectancy = stats.get("expectancy")
    profit_factor = stats.get("profit_factor")
    reasons: list[str] = []
    if trades < int(min_trades):
        reasons.append("too_few_trades")
    if expectancy is None or not np.isfinite(expectancy) or float(expectancy) <= 0.0:
        reasons.append("expectancy_not_positive")
    if not _profit_factor_clears(profit_factor):
        reasons.append("profit_factor_not_above_one")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "trades": trades,
        "expectancy": None if expectancy is None else float(expectancy),
        "profit_factor": None if profit_factor is None else float(profit_factor),
    }


def path_net_return(
    frame: pd.DataFrame,
    *,
    side: str,
    cost: float = ROUND_TRIP_COST,
) -> np.ndarray:
    """Net marked return of taking every event on one side.

    Args:
        frame: Event rows with path codes, distances, and the forward return.
        side: ``long`` or ``short``.
        cost: Round-trip cost as a fraction of price.

    Returns:
        One net return per row. Unlabeled paths are NaN.
    """
    code_column = "long_path_code" if side == "long" else "short_path_code"
    codes = frame[code_column].to_numpy(dtype=np.int64)
    tp_pct = frame["tp_pct"].to_numpy(dtype=np.float64)
    sl_pct = frame["sl_pct"].to_numpy(dtype=np.float64)
    forward = frame["forward_return_24"].to_numpy(dtype=np.float64)
    returns = np.full(len(frame), np.nan, dtype=np.float64)
    for index in range(len(frame)):
        returns[index] = trade_return(
            int(codes[index]),
            side=side,
            tp_pct=float(tp_pct[index]),
            sl_pct=float(sl_pct[index]),
            forward_return=float(forward[index]),
            cost=cost,
        )
    return returns


def always_in_expectancy(
    frame: pd.DataFrame,
    *,
    cost: float = ROUND_TRIP_COST,
) -> dict[str, float]:
    """Mean net return of taking every event long and every event short.

    Args:
        frame: Event rows.
        cost: Round-trip cost.

    Returns:
        Per-side means and their average.
    """
    long_pnl = path_net_return(frame, side="long", cost=cost)
    short_pnl = path_net_return(frame, side="short", cost=cost)
    long_mean = float(np.nanmean(long_pnl))
    short_mean = float(np.nanmean(short_pnl))
    return {
        "long": long_mean,
        "short": short_mean,
        "average": float(np.mean([long_mean, short_mean])),
        "rows": int(len(frame)),
    }


def probability_quintiles(
    probability: np.ndarray,
    realized: np.ndarray,
    *,
    bins: int = 5,
) -> list[dict[str, float]]:
    """Mean realized return by predicted-probability quintile.

    Args:
        probability: Model scores aligned to ``realized``.
        realized: Net path returns. Non-finite rows are dropped.
        bins: Number of quantile bins.

    Returns:
        One row per occupied bin, low probability first.
    """
    scores = np.asarray(probability, dtype=np.float64)
    outcomes = np.asarray(realized, dtype=np.float64)
    mask = np.isfinite(scores) & np.isfinite(outcomes)
    if int(mask.sum()) < int(bins):
        return []
    frame = pd.DataFrame({"probability": scores[mask], "realized": outcomes[mask]})
    frame["bin"] = pd.qcut(frame["probability"], q=int(bins), labels=False, duplicates="drop")
    rows = []
    for bin_id, group in frame.groupby("bin", sort=True):
        rows.append(
            {
                "bin": int(bin_id),
                "rows": int(len(group)),
                "mean_probability": float(group["probability"].mean()),
                "mean_realized": float(group["realized"].mean()),
            }
        )
    return rows


def ranking_statistical_gate(
    fold_model: Sequence[float],
    fold_baseline: Sequence[float],
) -> dict[str, Any]:
    """A head ranks when Brier beats the training base rate on two folds.

    Args:
        fold_model: Model Brier scores, lower better.
        fold_baseline: Base-rate Brier scores on the same folds.

    Returns:
        Win count and the pass flag.
    """
    return gate4_passed(fold_model, fold_baseline, higher_is_better=False, min_delta=0.0)


def _profit_factor_clears(profit_factor: float | None) -> bool:
    """True when profit factor is finite and above 1, or is positive infinity."""
    if profit_factor is None:
        return False
    value = float(profit_factor)
    if value == float("inf"):
        return True
    return bool(np.isfinite(value) and value > 1.0)


def one_position_direction_policy(
    frame: pd.DataFrame,
    probability: np.ndarray,
    *,
    threshold: float,
    cost: float = ROUND_TRIP_COST,
    horizon_bars: int = HORIZON_BARS,
    series_length: int | None = None,
    series_origin: int = 0,
) -> dict[str, Any]:
    """Trade argmax direction when the class probability clears a floor.

    Neutral and sub-floor rows stay flat. A new trade is skipped while a
    ``horizon_bars`` position is open. Buy marks ``forward_return_24 - cost``.
    Sell marks the opposite return minus cost.

    Args:
        frame: Rows with ``bar_index`` and ``forward_return_24``.
        probability: Array of shape ``(n, 3)`` for BEARISH / NEUTRAL / BULLISH.
        threshold: Minimum probability on the chosen class.
        cost: Round-trip cost as a fraction of price.
        horizon_bars: Bars a position occupies, including the fill bar.
        series_length: Optional overlay length for confirmation scoring.
        series_origin: ``bar_index`` of the first overlay slot.

    Returns:
        Trade count, expectancy, profit factor, drawdown, and per-trade returns.
    """
    order = np.argsort(frame["bar_index"].to_numpy(dtype=np.int64), kind="stable")
    bar_index = frame["bar_index"].to_numpy(dtype=np.int64)
    forward = frame["forward_return_24"].to_numpy(dtype=np.float64)
    proba = np.asarray(probability, dtype=np.float64)
    if proba.ndim != 2 or proba.shape[1] < 3:
        raise ValueError("direction probability must have shape (n, 3)")
    busy_until = -10**9
    pnls: list[float] = []
    overlay: np.ndarray | None = None
    if series_length is not None:
        overlay = np.zeros(int(series_length), dtype=np.float64)
    for position in order.tolist():
        signal_bar = int(bar_index[position])
        if signal_bar < busy_until:
            continue
        row = proba[position]
        class_id = int(np.argmax(row))
        confidence = float(row[class_id])
        if class_id == NEUTRAL or confidence < float(threshold):
            continue
        marked = float(forward[position])
        if not np.isfinite(marked):
            continue
        if class_id == BULLISH:
            pnl = marked - float(cost)
        elif class_id == BEARISH:
            pnl = -marked - float(cost)
        else:
            continue
        pnls.append(float(pnl))
        busy_until = signal_bar + int(horizon_bars)
        if overlay is not None:
            slot = signal_bar - int(series_origin)
            if 0 <= slot < overlay.size:
                overlay[slot] = float(pnl)
    stats = _return_stats(np.asarray(pnls, dtype=np.float64), decisions=int(len(frame)))
    stats["bar_returns"] = overlay
    stats["trade_returns"] = np.asarray(pnls, dtype=np.float64)
    return stats


def choose_direction_floor(
    frame: pd.DataFrame,
    probability: np.ndarray,
    *,
    cost: float = ROUND_TRIP_COST,
    grid: Sequence[float] = THRESHOLD_GRID,
    min_trades: int = GATE5_MIN_TRADES,
    horizon_bars: int = HORIZON_BARS,
) -> dict[str, Any]:
    """Pick one probability floor on a calibration block.

    A candidate must show at least ``min_trades`` non-overlapping trades,
    positive expectancy, and a profit factor above 1 after ``cost``.

    Args:
        frame: Calibration rows only.
        probability: Class probabilities aligned to ``frame``.
        cost: Round-trip cost.
        grid: Floors to try, low to high.
        min_trades: Minimum filled trades.
        horizon_bars: Occupancy of one position.

    Returns:
        The selected floor, or ``selected: null`` when none pass.
    """
    best: dict[str, Any] | None = None
    saw_enough_trades = False
    candidates = []
    for floor in grid:
        stats = one_position_direction_policy(
            frame,
            probability,
            threshold=float(floor),
            cost=cost,
            horizon_bars=horizon_bars,
        )
        row = {
            "probability_floor": float(floor),
            "trades": int(stats["trades"]),
            "expectancy": stats["expectancy"],
            "profit_factor": stats["profit_factor"],
        }
        candidates.append(row)
        if int(stats["trades"]) < int(min_trades):
            continue
        saw_enough_trades = True
        if stats["expectancy"] is None or float(stats["expectancy"]) <= 0.0:
            continue
        if not _profit_factor_clears(stats.get("profit_factor")):
            continue
        if best is None or float(stats["expectancy"]) > float(best["expectancy"]):
            best = row
    if best is None:
        reason = (
            "no_positive_calibration_expectancy"
            if saw_enough_trades
            else "no_threshold_with_enough_trades"
        )
        return {"selected": None, "reason": reason, "candidates": candidates}
    return {
        "selected": best,
        "reason": "max_calibration_expectancy",
        "candidates": candidates,
    }


def direction_expectancy_fold_gate(
    fold_expectancies: Sequence[float | None],
) -> dict[str, Any]:
    """Require positive traded expectancy on at least two walk-forward folds."""
    wins = 0
    for value in fold_expectancies:
        if value is None or not np.isfinite(value):
            continue
        if float(value) > 0.0:
            wins += 1
    return {
        "wins": wins,
        "folds": len(fold_expectancies),
        "passed": wins >= 2,
    }


def _median_phase(phases: Sequence[Mapping[str, float]]) -> dict[str, float | None]:
    if not phases:
        return {
            "trades": 0.0,
            "expectancy": None,
            "profit_factor": None,
            "max_drawdown": None,
            "phases": 0.0,
        }
    return {
        "trades": _median_number(phases, "trades", traded_only=False),
        "expectancy": _median_number(phases, "expectancy", traded_only=True),
        "profit_factor": _median_number(phases, "profit_factor", traded_only=True),
        "max_drawdown": _median_number(phases, "max_drawdown", traded_only=True),
        "phases": float(len(phases)),
    }
