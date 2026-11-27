"""Algorithmic entry policy: score and brackets, not ML confidence."""

from agent.core.algorithmic_entry_policy import algorithmic_entry_reject
from research.swinging.contract import ALGO_DECISION_PATH


def test_qualified_score_passes_without_confidence_floor() -> None:
    reason = algorithmic_entry_reject(
        decision_path=ALGO_DECISION_PATH,
        signal="BUY",
        algo_score=72,
        algo_signal_validated=True,
        invalidation="",
    )
    assert reason is None


def test_below_qualified_score_rejects() -> None:
    reason = algorithmic_entry_reject(
        decision_path=ALGO_DECISION_PATH,
        signal="BUY",
        algo_score=64.9,
        algo_signal_validated=True,
    )
    assert reason == "below_algorithmic_threshold"


def test_hold_and_wrong_path_reject() -> None:
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="HOLD",
            algo_score=80,
        )
        == "invalid_signal"
    )
    assert (
        algorithmic_entry_reject(
            decision_path="mtf_fusion",
            signal="BUY",
            algo_score=80,
        )
        == "invalid_decision_path"
    )


def test_structural_invalidation_and_unvalidated_flag() -> None:
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="BUY",
            algo_score=72,
            invalidation="bearish_choch",
        )
        == "structural_invalidation"
    )
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="SELL",
            algo_score=72,
            algo_signal_validated=False,
        )
        == "algorithmic_signal_not_validated"
    )


def test_brackets_require_correct_side() -> None:
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="BUY",
            algo_score=72,
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profit=52000.0,
            check_brackets=True,
        )
        is None
    )
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="BUY",
            algo_score=72,
            entry_price=50000.0,
            stop_loss=0.0,
            take_profit=52000.0,
            check_brackets=True,
        )
        == "algorithmic_invalid_brackets"
    )
    assert (
        algorithmic_entry_reject(
            decision_path=ALGO_DECISION_PATH,
            signal="SELL",
            algo_score=80,
            entry_price=50000.0,
            stop_loss=49000.0,
            take_profit=48000.0,
            check_brackets=True,
        )
        == "algorithmic_invalid_brackets"
    )
