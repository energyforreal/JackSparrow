"""Combine algorithmic evidence with calibrated model output.

This module does not import execution, risk, or order placement.
"""

from __future__ import annotations

from typing import Any, Mapping

from research.swinging.contract import ACCEPT_SCORE, ROUND_TRIP_COST, STRATEGIES


def decide(
    *,
    strategy: str,
    direction: str,
    algorithmic_score: float,
    win_probability: float,
    expected_net_return: float,
    probability_floor: float = 0.55,
    minimum_edge: float = 0.0,
) -> dict[str, Any]:
    """Choose long, short, or abstain for one strategy.

    Args:
        strategy: ``algorithm_only``, ``ml_only``, or ``hybrid``.
        direction: Setup direction. Neutral never trades.
        algorithmic_score: Engine A score in ``[0, 1]``.
        win_probability: Calibrated probability of a winning outcome.
        expected_net_return: Model expected net return after costs.
        probability_floor: Minimum win probability for an ML entry.
        minimum_edge: Minimum expected net return. Defaults to zero, which
            already sits above the cost embedded in the label.

    Returns:
        Action, reason, agreement, and the expected net return used.

    Raises:
        ValueError: If ``strategy`` is unknown.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    algo_trade = direction in ("long", "short") and float(algorithmic_score) >= ACCEPT_SCORE
    ml_trade = (
        direction in ("long", "short")
        and float(win_probability) >= probability_floor
        and float(expected_net_return) > minimum_edge
    )
    if strategy == "algorithm_only":
        action = direction if algo_trade else "abstain"
        reason = "algorithm_threshold" if algo_trade else "algorithm_abstain"
        agreement = "algorithm_only"
    elif strategy == "ml_only":
        action = direction if ml_trade else "abstain"
        reason = "ml_edge" if ml_trade else "ml_abstain"
        agreement = "ml_only"
    else:
        if algo_trade and ml_trade:
            action = direction
            reason = "hybrid_agree"
            agreement = "agree"
        elif algo_trade != ml_trade:
            action = "abstain"
            reason = "hybrid_disagree"
            agreement = "disagree"
        else:
            action = "abstain"
            reason = "hybrid_abstain"
            agreement = "disagree"
    return {
        "strategy": strategy,
        "action": action,
        "reason": reason,
        "agreement": agreement,
        "expected_net_return": float(expected_net_return),
        "round_trip_cost": ROUND_TRIP_COST,
    }


def decide_frame(row: Mapping[str, Any], strategy: str, **kwargs: float) -> dict[str, Any]:
    """Run ``decide`` on a mapping of setup and model fields.

    Args:
        row: Must include direction, score, win probability, and expected net.
        strategy: One of ``STRATEGIES``.
        **kwargs: Forwarded floors.

    Returns:
        Decision dictionary.
    """
    return decide(
        strategy=strategy,
        direction=str(row.get("direction") or "neutral"),
        algorithmic_score=float(row.get("algorithmic_score") or 0.0),
        win_probability=float(row.get("win_probability") or 0.0),
        expected_net_return=float(row.get("expected_net_return") or 0.0),
        **kwargs,
    )
