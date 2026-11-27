"""Walk-forward replay of the algorithmic score.

Weights and the 65/80 cutoffs may be searched with Optuna. The search does
not fit a classifier or a regressor. Fills, fees, slippage, and funding stay
in ``outcomes.py``.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from research.swinging.contract import (
    ALGO_BOS_LOOKBACK,
    ALGO_HIGH_QUALITY_SCORE,
    ALGO_QUALIFIED_SCORE,
    ALGO_WEIGHTS,
    BAR_MINUTES,
    RESOLUTIONS,
    max_hold_bars,
)
from research.swinging.evaluate import trade_metrics
from research.swinging.mtf_score import (
    decide_scores,
    prepare_frame,
    resolve_weights,
    side_fractions,
)
from research.swinging.outcomes import simulate_portfolio
from research.swinging.quality import normalize_ohlcv
from research.swinging.splits import chronological_bounds, purged_folds


def component_rows(
    frames: Mapping[str, pd.DataFrame],
    *,
    bos_lookback: int = ALGO_BOS_LOOKBACK,
    warmup: int = 30,
) -> pd.DataFrame:
    """Score fractions for every closed 5m bar that has higher-timeframe context.

    Args:
        frames: OHLCV for ``5m``, ``15m``, ``1h``, and ``4h``.
        bos_lookback: 1h bars a BOS or CHoCH may still influence.
        warmup: Leading 5m bars skipped so indicators have a past.

    Returns:
        One row per usable 5m bar. Columns are fractions, not points, so a
        later weight change does not rebuild features.
    """
    from research.swinging.quality import decision_data_issues

    missing = [name for name in RESOLUTIONS if name not in frames]
    if missing:
        raise ValueError(f"missing resolutions: {', '.join(missing)}")
    issues = [item for item in decision_data_issues(frames) if not item.startswith("missing_")]
    if issues:
        raise ValueError("algorithmic frames rejected: " + ", ".join(issues))
    prepared = {name: prepare_frame(frames[name]) for name in RESOLUTIONS}
    five = prepared["5m"]
    records: list[dict[str, Any]] = []
    for index in range(max(0, warmup), len(five)):
        opened = pd.Timestamp(five["time"].iloc[index])
        if opened.tzinfo is None:
            opened = opened.tz_localize("UTC")
        decision_time = opened + pd.Timedelta(minutes=BAR_MINUTES["5m"])
        snapshot: dict[str, pd.Series] = {}
        available = True
        for name in RESOLUTIONS:
            closes = pd.to_datetime(prepared[name]["time"], utc=True) + pd.Timedelta(
                minutes=BAR_MINUTES[name]
            )
            position = int(closes.searchsorted(decision_time, side="right")) - 1
            if position < 0:
                available = False
                break
            snapshot[name] = prepared[name].iloc[position]
        if not available:
            continue
        long_frac, long_note = side_fractions(snapshot, "long", bos_lookback)
        short_frac, short_note = side_fractions(snapshot, "short", bos_lookback)
        atr = float(snapshot["5m"].get("atr_14") or 0.0)
        if atr <= 0.0:
            atr = float(snapshot["5m"].get("atr") or 0.0)
        record: dict[str, Any] = {
            "bar_index": int(index),
            "signal_timestamp": opened.isoformat(),
            "atr_14": atr,
            "long_invalidation": long_note,
            "short_invalidation": short_note,
        }
        for key, value in long_frac.items():
            record[f"long_{key}"] = float(value)
        for key, value in short_frac.items():
            record[f"short_{key}"] = float(value)
        records.append(record)
    return pd.DataFrame.from_records(records)


def _row_decision(
    row: Mapping[str, Any],
    weights: Mapping[str, float],
    qualified_score: float,
    high_quality_score: float,
) -> dict[str, Any]:
    long_score = sum(float(weights[key]) * float(row.get(f"long_{key}") or 0.0) for key in weights)
    short_score = sum(
        float(weights[key]) * float(row.get(f"short_{key}") or 0.0) for key in weights
    )
    return decide_scores(
        long_score=long_score,
        short_score=short_score,
        long_invalidation=str(row.get("long_invalidation") or ""),
        short_invalidation=str(row.get("short_invalidation") or ""),
        qualified_score=qualified_score,
        high_quality_score=high_quality_score,
    )


def rows_to_setups(
    rows: pd.DataFrame,
    weights: Mapping[str, float],
    qualified_score: float,
    high_quality_score: float,
) -> pd.DataFrame:
    """Convert scored rows into simulator setups.

    Args:
        rows: Output of ``component_rows`` or a chronological slice of it.
        weights: Renormalized component weights.
        qualified_score: Minimum points that become a setup.
        high_quality_score: Strong-signal cutoff recorded on the decision only.

    Returns:
        Setup rows the portfolio simulator can fill. Holds are omitted.
    """
    records: list[dict[str, Any]] = []
    if rows.empty:
        return pd.DataFrame(records)
    for row in rows.to_dict(orient="records"):
        decision = _row_decision(row, weights, qualified_score, high_quality_score)
        if decision["action"] not in ("long", "short"):
            continue
        records.append(
            {
                "setup_id": f"algo:{int(row['bar_index'])}:{decision['action']}",
                "signal_timestamp": row["signal_timestamp"],
                "bar_index": int(row["bar_index"]),
                "direction": decision["action"],
                "timeframe": "5m",
                "atr_14": float(row.get("atr_14") or 0.0),
                "algorithmic_score": float(decision["score"]) / 100.0,
                "algo_score": float(decision["score"]),
            }
        )
    return pd.DataFrame.from_records(records)


def _taken_returns(setups: pd.DataFrame, bars: pd.DataFrame) -> list[float]:
    if setups.empty:
        return []
    simulated = simulate_portfolio(setups, bars)
    if simulated.empty or "simulated" not in simulated.columns:
        return []
    taken = simulated[simulated["simulated"] == True]  # noqa: E712
    if taken.empty or "net_return" not in taken.columns:
        return []
    return [float(value) for value in taken["net_return"].tolist()]


def walk_forward_algo(
    frames: Mapping[str, pd.DataFrame],
    *,
    weights: Mapping[str, float] | None = None,
    qualified_score: float | None = None,
    high_quality_score: float | None = None,
    n_splits: int = 3,
    embargo: int | None = None,
) -> dict[str, Any]:
    """Replay one fixed score through purged folds and a sealed tail.

    Args:
        frames: Multi-timeframe OHLCV. The 5m frame is the signal and fill series.
        weights: Score weights. Defaults to the design values.
        qualified_score: Hold threshold.
        high_quality_score: Strong-signal threshold.
        n_splits: Validation blocks inside the development span.
        embargo: Bars removed from the end of each training side. The default
            is the 5m max hold so a train trade cannot close inside validation.
            This runner does not refit weights, so the embargo only drops
            empty training sides the same way the ML walk-forward does.

    Returns:
        Fold metrics, pooled development metrics, and the sealed-test metrics.
        Costs are the simulator's fees, slippage, and funding.
    """
    resolved = resolve_weights(weights)
    qualified = ALGO_QUALIFIED_SCORE if qualified_score is None else float(qualified_score)
    high = ALGO_HIGH_QUALITY_SCORE if high_quality_score is None else float(high_quality_score)
    rows = component_rows(frames)
    bars = normalize_ohlcv(frames["5m"])
    hold = max_hold_bars("5m") if embargo is None else int(embargo)
    folds: list[dict[str, Any]] = []
    pooled: list[float] = []
    if len(rows) >= 3:
        try:
            fold_iter = purged_folds(len(rows), n_splits=n_splits, embargo=hold)
        except ValueError:
            fold_iter = ()
        for _train, validation in fold_iter:
            returns = _taken_returns(
                rows_to_setups(rows.iloc[validation], resolved, qualified, high),
                bars,
            )
            folds.append(trade_metrics(returns))
            pooled.extend(returns)
        _, _, sealed = chronological_bounds(len(rows))
        sealed_returns = _taken_returns(
            rows_to_setups(rows.iloc[sealed:], resolved, qualified, high),
            bars,
        )
    else:
        sealed_returns = []
    return {
        "embargo_bars": int(hold),
        "folds": folds,
        "development": trade_metrics(pooled),
        "sealed_test": trade_metrics(sealed_returns),
        "weights": resolved,
        "qualified_score": qualified,
        "high_quality_score": high,
        "rows": int(len(rows)),
    }


def tune_algo_weights(
    frames: Mapping[str, pd.DataFrame],
    *,
    n_trials: int = 20,
    rows: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Search score weights and cutoffs on the development span only.

    Args:
        frames: Multi-timeframe OHLCV.
        n_trials: Optuna trials. Each trial resimulates development trades.
        rows: Optional precomputed component rows.

    Returns:
        Best weights renormalized to 100, the chosen cutoffs, and the
        development-span net expectancy. No tree model is fit.

    Raises:
        ValueError: If the frame is too short to split.
    """
    import optuna

    scored = component_rows(frames) if rows is None else rows
    if len(scored) < 3:
        raise ValueError("not enough closed bars to tune algorithmic weights")
    train_end, _, _sealed = chronological_bounds(len(scored))
    usable_end = max(1, train_end - max_hold_bars("5m"))
    train_rows = scored.iloc[:usable_end]
    bars = normalize_ohlcv(frames["5m"])

    def objective(trial: optuna.Trial) -> float:
        raw = {key: trial.suggest_float(key, 0.0, 40.0) for key in ALGO_WEIGHTS}
        total = sum(raw.values())
        if total <= 0.0:
            return -1.0
        weights = {key: 100.0 * value / total for key, value in raw.items()}
        qualified = trial.suggest_float("qualified_score", 50.0, 85.0)
        high = trial.suggest_float("high_quality_score", qualified, 100.0)
        returns = _taken_returns(
            rows_to_setups(train_rows, weights, qualified, high),
            bars,
        )
        metrics = trade_metrics(returns)
        if int(metrics["trades"]) == 0:
            return -1.0
        return float(metrics["net_expectancy"])

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=max(1, int(n_trials)))
    best = study.best_params
    raw_best = {key: float(best[key]) for key in ALGO_WEIGHTS}
    total_best = sum(raw_best.values()) or 1.0
    return {
        "weights": {key: 100.0 * value / total_best for key, value in raw_best.items()},
        "qualified_score": float(best["qualified_score"]),
        "high_quality_score": float(best["high_quality_score"]),
        "development_expectancy": float(study.best_value),
    }
