"""F1 macro validation gate for adaptive retrain accept/reject."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
from sklearn.metrics import f1_score, roc_auc_score

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


def validate_v43_style_five_gates(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    proba: Optional[np.ndarray] = None,
    *,
    min_auc: float = 0.55,
    min_ic: float = 0.03,
    min_win_rate: float = 0.74,
    min_sharpe: float = 1.0,
) -> Tuple[bool, Dict[str, Any]]:
    """Five validation checks on a holdout slice (classification).

    Uses macro OvR AUC when ``predict_proba`` matrix is provided, Spearman IC
    between max class probability and hit indicator, accuracy vs ``min_win_rate``,
    hit-rate excess over random 1/3 baseline, and Sharpe on +/-1 per-row outcomes.
    """
    detail: Dict[str, Any] = {}
    yt = np.asarray(y_true, dtype=np.int64).ravel()
    yp = np.asarray(y_pred, dtype=np.int64).ravel()
    n = int(yt.size)
    if n < 30:
        detail["rejected_reason"] = "five_gates_insufficient_rows"
        return False, detail

    classes = sorted(int(x) for x in np.unique(yt).tolist())
    try:
        if proba is not None and isinstance(proba, np.ndarray):
            pr = np.asarray(proba, dtype=np.float64)
            if pr.ndim == 2 and pr.shape[0] == n and pr.shape[1] >= 2:
                auc = float(
                    roc_auc_score(yt, pr, multi_class="ovr", average="macro", labels=classes)
                )
            else:
                auc = float(val_win_rate(yt, yp))
        else:
            auc = float(val_win_rate(yt, yp))
    except Exception:
        auc = float(val_win_rate(yt, yp))

    hit = (yt == yp).astype(np.float64)
    win_rate = float(val_win_rate(yt, yp))
    try:
        from scipy.stats import spearmanr

        if proba is not None and isinstance(proba, np.ndarray):
            pr = np.asarray(proba, dtype=np.float64)
            if pr.ndim == 2 and pr.shape[0] == n:
                score = np.max(pr, axis=1)
            else:
                score = hit
        else:
            score = hit
        if float(np.std(score)) < 1e-12:
            ic = 1.0 if win_rate >= 0.99 else 0.0
        else:
            ic_raw = spearmanr(score, hit).correlation
            if ic_raw is None or (isinstance(ic_raw, float) and np.isnan(ic_raw)):
                ic = 1.0 if win_rate >= 0.99 else 0.0
            else:
                ic = float(abs(ic_raw))
    except Exception:
        ic = 1.0 if win_rate >= 0.99 else 0.0

    excess = float(np.mean(hit) - (1.0 / max(len(classes), 3)))
    per = 2.0 * hit - 1.0
    std = float(np.std(per))
    if std <= 1e-9 and abs(float(np.mean(per))) >= 1.0 - 1e-9:
        sharpe = float(min(10.0, np.sqrt(n)))
    else:
        sharpe = float(np.mean(per) / std * np.sqrt(n)) if std > 1e-9 else 0.0

    gates = {
        "auc_macro_ovr": auc,
        "ic_abs": ic,
        "win_rate": win_rate,
        "oos_return_proxy": excess,
        "sharpe_proxy": sharpe,
    }
    detail["five_gates"] = gates
    ok1 = auc >= min_auc
    ok2 = ic >= min_ic
    ok3 = win_rate >= min_win_rate
    ok4 = excess >= 0.0
    ok5 = sharpe >= min_sharpe
    ok = ok1 and ok2 and ok3 and ok4 and ok5
    if not ok:
        detail["rejected_reason"] = "five_gates"
        detail["five_gate_failures"] = {
            "auc": ok1,
            "ic": ok2,
            "win_rate": ok3,
            "return_proxy": ok4,
            "sharpe": ok5,
        }
    return ok, detail


def validate_model_upgrade(
    old_model: Any,
    new_model: Any,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    min_improvement: float = 0.0,
    require_scorecard: bool = False,
    require_five_gates: bool = False,
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
    new_proba = None
    pred_proba = getattr(new_c, "predict_proba", None)
    if callable(pred_proba):
        try:
            new_proba = pred_proba(X_val)
        except Exception:
            new_proba = None
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
        if require_five_gates:
            fg_ok, fg_detail = validate_v43_style_five_gates(y_val, new_pred, new_proba)
            detail.update(fg_detail)
            if not fg_ok:
                return False, detail
        detail["rejected_reason"] = None
        return True, detail

    tol_wr = float(0.02)
    tol_pf = float(0.05)
    tol_dd = float(0.02)

    wr_ok = new_sc["val_win_rate"] + tol_wr >= old_sc["val_win_rate"]
    pf_ok = new_sc["val_profit_factor_proxy"] + tol_pf >= old_sc["val_profit_factor_proxy"]
    dd_ok = new_sc["val_max_drawdown_proxy"] <= old_sc["val_max_drawdown_proxy"] + tol_dd

    if wr_ok and pf_ok and dd_ok:
        if require_five_gates:
            fg_ok, fg_detail = validate_v43_style_five_gates(y_val, new_pred, new_proba)
            detail.update(fg_detail)
            if not fg_ok:
                return False, detail
        detail["rejected_reason"] = None
        return True, detail

    detail["rejected_reason"] = "scorecard_gate"
    detail["gates"] = {"win_rate": wr_ok, "profit_factor_proxy": pf_ok, "max_drawdown_proxy": dd_ok}
    return False, detail
