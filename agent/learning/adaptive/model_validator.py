"""F1 macro validation gate for adaptive retrain accept/reject."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
from sklearn.metrics import f1_score

from agent.learning.adaptive.retrain_engine import _unwrap_classifier


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Macro F1 with zero_division=0 (matches notebook)."""
    return float(
        f1_score(
            y_true,
            y_pred,
            average="macro",
            zero_division=0,
        )
    )


def validate_f1_improvement(
    old_model: Any,
    new_model: Any,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    min_improvement: float = 0.0,
) -> Tuple[bool, float, float]:
    """Accept new model only if macro F1 is not worse than old (+ margin).

    Args:
        old_model: Dict pipeline or XGBClassifier.
        new_model: Retrained classifier.
        X_val: Validation features.
        y_val: Validation labels.
        min_improvement: Require new_f1 >= old_f1 + this value.

    Returns:
        (accepted, old_f1, new_f1)
    """
    old_c = _unwrap_classifier(old_model)
    new_c = _unwrap_classifier(new_model)
    old_pred = old_c.predict(X_val)
    new_pred = new_c.predict(X_val)
    old_f1 = macro_f1(y_val, old_pred)
    new_f1 = macro_f1(y_val, new_pred)
    accepted = new_f1 >= old_f1 + float(min_improvement)
    return accepted, old_f1, new_f1


def val_win_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Classification accuracy as a proxy for directional win rate on the val slice."""
    if y_true.size == 0:
        return 0.0
    return float(np.mean(y_true == y_pred))


def val_profit_factor_proxy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Ratio of correct to incorrect predictions (classification analogue of profit factor)."""
    n = int(y_true.size)
    if n == 0:
        return 1.0
    wins = int(np.sum(y_true == y_pred))
    losses = n - wins
    return float(wins / max(losses, 1))


def val_max_drawdown_proxy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Max drawdown on cumulative \"equity\" where each correct prediction adds 1."""
    if y_true.size == 0:
        return 0.0
    correct = (y_true == y_pred).astype(np.float64)
    eq = np.cumsum(correct)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.maximum(peak, 1.0)
    return float(np.max(dd))


def validation_scorecard(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Aggregate metrics for adaptive promotion audit (no prices required)."""
    return {
        "macro_f1": macro_f1(y_true, y_pred),
        "val_win_rate": val_win_rate(y_true, y_pred),
        "val_profit_factor_proxy": val_profit_factor_proxy(y_true, y_pred),
        "val_max_drawdown_proxy": val_max_drawdown_proxy(y_true, y_pred),
    }


def validate_model_upgrade(
    old_model: Any,
    new_model: Any,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    min_improvement: float = 0.0,
    require_scorecard: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """F1 gate plus optional scorecard dominance (new not worse on key proxies).

    When ``require_scorecard`` is True, the new model must match or beat the old
    model on win-rate and PF proxy (within small tolerance), and have lower or
    equal max-drawdown proxy.
    """
    old_c = _unwrap_classifier(old_model)
    new_c = _unwrap_classifier(new_model)
    old_pred = old_c.predict(X_val)
    new_pred = new_c.predict(X_val)
    old_f1 = macro_f1(y_val, old_pred)
    new_f1 = macro_f1(y_val, new_pred)
    f1_ok = new_f1 >= old_f1 + float(min_improvement)

    old_sc = validation_scorecard(y_val, old_pred)
    new_sc = validation_scorecard(y_val, new_pred)
    detail: Dict[str, Any] = {
        "old_f1": old_f1,
        "new_f1": new_f1,
        "old_scorecard": old_sc,
        "new_scorecard": new_sc,
    }

    if not f1_ok:
        detail["rejected_reason"] = "f1_gate"
        return False, detail

    if not require_scorecard:
        detail["rejected_reason"] = None
        return True, detail

    tol_wr = float(0.02)
    tol_pf = float(0.05)
    tol_dd = float(0.02)

    wr_ok = new_sc["val_win_rate"] + tol_wr >= old_sc["val_win_rate"]
    pf_ok = new_sc["val_profit_factor_proxy"] + tol_pf >= old_sc["val_profit_factor_proxy"]
    dd_ok = new_sc["val_max_drawdown_proxy"] <= old_sc["val_max_drawdown_proxy"] + tol_dd

    if wr_ok and pf_ok and dd_ok:
        detail["rejected_reason"] = None
        return True, detail

    detail["rejected_reason"] = "scorecard_gate"
    detail["gates"] = {"win_rate": wr_ok, "profit_factor_proxy": pf_ok, "max_drawdown_proxy": dd_ok}
    return False, detail
