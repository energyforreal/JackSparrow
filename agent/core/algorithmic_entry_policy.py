"""Eligibility checks for algorithmic entries.

Scoring and classification stay in the multi-timeframe scorer. This policy
decides whether a scored algorithmic signal may continue to portfolio and
risk checks. It does not apply transformer confidence floors, feature-dict
filters, or the algorithmic order flag. Risk approval and
``algorithmic_order_block`` stay downstream.
"""

from __future__ import annotations

from typing import Any

from research.swinging.contract import ALGO_DECISION_PATH, ALGO_QUALIFIED_SCORE

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_EMPTY_INVALIDATION = frozenset({"", "none", "null"})


def _invalidation_text(value: object) -> str:
    """Return the first non-empty invalidation code."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _invalidation_text(item)
            if text:
                return text
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY_INVALIDATION:
        return ""
    return text


def _bracket_reject(
    signal: str,
    entry_price: Any,
    stop_loss: Any,
    take_profit: Any,
) -> str | None:
    """Reject when stop and target are missing or on the wrong side of price."""
    side = "buy" if signal in ("BUY", "STRONG_BUY") else "sell"
    try:
        price = float(entry_price)
        stop = float(stop_loss)
        take = float(take_profit)
    except (TypeError, ValueError):
        return "algorithmic_invalid_brackets"
    if price <= 0.0 or stop <= 0.0 or take <= 0.0:
        return "algorithmic_invalid_brackets"
    if side == "buy" and not (stop < price < take):
        return "algorithmic_invalid_brackets"
    if side == "sell" and not (take < price < stop):
        return "algorithmic_invalid_brackets"
    return None


def algorithmic_entry_reject(
    *,
    decision_path: str | None,
    signal: str | None,
    algo_score: Any,
    algo_signal_validated: bool | None = None,
    invalidation: object = None,
    qualified_score: float = ALGO_QUALIFIED_SCORE,
    entry_price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    check_brackets: bool = False,
) -> str | None:
    """Return a reject reason, or ``None`` when the entry may continue.

    Bracket geometry is checked only when ``check_brackets`` is true, after
    an entry price is known. Confidence floors and feature filters are not
    consulted.

    Args:
        decision_path: Market-context path. Must be ``algorithmic``.
        signal: Wire signal from the decision payload.
        algo_score: Scorer points. Qualified entries are at least 65.
        algo_signal_validated: Explicit scorer flag. ``None`` defers to signal.
        invalidation: Structural or conflict code from the scorer.
        qualified_score: Minimum score that may continue. Defaults to contract.
        entry_price: Live entry price used for bracket geometry.
        stop_loss: Proposed stop from the algorithmic execution plan.
        take_profit: Proposed target from the algorithmic execution plan.
        check_brackets: When true, missing or crossed brackets reject.

    Returns:
        Stable reject code, or ``None`` when eligible.
    """
    if decision_path != ALGO_DECISION_PATH:
        return "invalid_decision_path"
    if signal not in _ENTRY_SIGNALS:
        return "invalid_signal"
    try:
        score = float(algo_score)
    except (TypeError, ValueError):
        return "below_algorithmic_threshold"
    if score < float(qualified_score):
        return "below_algorithmic_threshold"
    if _invalidation_text(invalidation):
        return "structural_invalidation"
    if algo_signal_validated is False:
        return "algorithmic_signal_not_validated"
    if check_brackets:
        return _bracket_reject(signal, entry_price, stop_loss, take_profit)
    return None
