"""Walk-forward comparison of algorithm-only, ML-only, and hybrid decisions.

All three strategies read the same net returns, costs, and fills. This module
does not place orders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from research.swinging.contract import COLAB_DATA_ROOT, STRATEGIES, max_hold_bars
from research.swinging.fusion import decide_frame
from research.swinging.splits import chronological_bounds, purged_folds

PredictFn = Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame]


def trade_metrics(returns: Sequence[float], regimes: Sequence[str] | None = None) -> dict[str, Any]:
    """Summarize a list of net trade returns.

    Args:
        returns: Net returns of trades the strategy actually took.
        regimes: Optional regime label per trade.

    Returns:
        Expectancy, profit factor, drawdown, frequency, and per-trade Sharpe.
        An empty list scores as no trades rather than as a profit.
    """
    values = np.asarray(list(returns), dtype=float)
    if values.size == 0:
        return {
            "trades": 0,
            "net_expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "per_trade_sharpe": 0.0,
            "by_regime": {},
        }
    wins = values[values > 0.0]
    losses = values[values < 0.0]
    if losses.size == 0:
        profit_factor = None if wins.size else 0.0
    else:
        profit_factor = float(wins.sum() / abs(losses.sum())) if wins.size else 0.0
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(equity)
    drawdown = float((peak - equity).max()) if equity.size else 0.0
    deviation = float(values.std(ddof=0))
    sharpe = 0.0 if deviation == 0.0 else float(values.mean() / deviation * np.sqrt(values.size))
    by_regime: dict[str, float] = {}
    if regimes is not None:
        grouped: dict[str, list[float]] = {}
        for label, value in zip(regimes, values):
            grouped.setdefault(str(label), []).append(float(value))
        by_regime = {
            label: float(np.mean(samples)) for label, samples in grouped.items()
        }
    return {
        "trades": int(values.size),
        "net_expectancy": float(values.mean()),
        "profit_factor": profit_factor,
        "max_drawdown": drawdown,
        "per_trade_sharpe": sharpe,
        "by_regime": by_regime,
    }


def _taken_returns(frame: pd.DataFrame, strategy: str) -> tuple[list[float], list[str]]:
    returns: list[float] = []
    regimes: list[str] = []
    for record in frame.to_dict(orient="records"):
        decision = decide_frame(record, strategy)
        if decision["action"] not in ("long", "short"):
            continue
        if decision["action"] != record.get("direction"):
            continue
        returns.append(float(record.get("net_return") or 0.0))
        regimes.append(str(record.get("regime_target") or "unknown"))
    return returns, regimes


def compare_strategies(frame: pd.DataFrame) -> dict[str, Any]:
    """Score the three strategies on one shared outcome frame.

    Args:
        frame: Rows with ``net_return``, ``direction``, ``algorithmic_score``,
            ``win_probability``, and ``expected_net_return``.

    Returns:
        Metrics for each strategy. Costs and fills are the columns already on
        ``frame``; this function does not resimulate them.
    """
    report = {}
    for strategy in STRATEGIES:
        returns, regimes = _taken_returns(frame, strategy)
        report[strategy] = trade_metrics(returns, regimes)
    return report


def walk_forward_compare(
    frame: pd.DataFrame,
    predict: PredictFn,
    *,
    n_splits: int = 3,
    embargo: int | None = None,
) -> dict[str, Any]:
    """Fit on each purged training side and score the three strategies.

    Args:
        frame: Chronological supervised rows.
        predict: ``(train, validation) -> validation`` with ``win_probability``
            and ``expected_net_return`` filled from the training side only.
        n_splits: Walk-forward folds inside the development span.
        embargo: Bars dropped before each validation block. Defaults to the
            longest configured hold.

    Returns:
        Fold metrics, the pooled development comparison, and one sealed-test
        comparison.
    """
    hold = embargo if embargo is not None else max(max_hold_bars(name) for name in ("5m", "15m", "1h", "4h"))
    folds = []
    pooled: list[pd.DataFrame] = []
    for train_indexes, validation_indexes in purged_folds(
        len(frame),
        n_splits=n_splits,
        embargo=hold,
    ):
        train = frame.iloc[train_indexes]
        validation = frame.iloc[validation_indexes]
        predicted = predict(train, validation.copy())
        folds.append(compare_strategies(predicted))
        pooled.append(predicted)
    development = compare_strategies(pd.concat(pooled, ignore_index=True)) if pooled else {}
    _, _, sealed = chronological_bounds(len(frame))
    sealed_frame = predict(frame.iloc[:sealed], frame.iloc[sealed:].copy())
    return {
        "embargo_bars": int(hold),
        "folds": folds,
        "development": development,
        "sealed_test": compare_strategies(sealed_frame),
    }


def materialize_comparison(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = "BTCUSD",
) -> dict[str, Any]:
    """Score stored outcomes with the setup-effectiveness artifact.

    Args:
        root: Local dataset root.
        symbol: Instrument.

    Returns:
        Strategy comparison written to ``experiments/comparison.json``.
    """
    import joblib

    from research.swinging.models import score_features

    dataset = Path(root)
    artifact = joblib.load(dataset / "experiments" / "setup_effectiveness" / "models.joblib")
    frames = []
    for resolution in ("5m", "15m", "1h", "4h"):
        path = dataset / symbol / resolution / "outcomes.parquet"
        if path.is_file():
            frames.append(pd.read_parquet(path))
    if not frames:
        raise FileNotFoundError("outcomes parquet is missing")
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.sort_values("signal_timestamp").reset_index(drop=True)
    columns = list(artifact["feature_columns"])
    matrix = frame.reindex(columns=columns).apply(pd.to_numeric, errors="coerce").fillna(0.0)
    scored = score_features(artifact, matrix.to_numpy(dtype=float))
    frame["win_probability"] = scored["event_probability"]
    frame["expected_net_return"] = scored["expected_net_return"]
    report = compare_strategies(frame)
    destination = dataset / "experiments" / "comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
