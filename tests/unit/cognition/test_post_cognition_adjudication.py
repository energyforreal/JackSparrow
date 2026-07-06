"""Post-cognition adjudication parity and helper tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.core.cognition_orchestration import (
    PostCognitionAdjudication,
    check_adjudication_parity,
    run_post_cognition_adjudication,
)
from agent.core.strategy_types import MLValidationSnapshot, StrategyCandidate


def _ml_validation() -> MLValidationSnapshot:
    return MLValidationSnapshot(
        expected_return=0.01,
        threshold=0.005,
        short_threshold=0.005,
        regime="neutral",
        confirms_long=True,
        confirms_short=False,
    )


def _strategy(direction: str = "LONG") -> StrategyCandidate:
    return StrategyCandidate(
        signal="LONG" if direction == "LONG" else ("SHORT" if direction == "SHORT" else "HOLD"),
        direction=direction,
        strength=0.6,
        confidence=0.6,
        thesis_type="breakout",
    )


def _thesis(signal: str = "LONG", thesis_type: str = "breakout") -> MagicMock:
    tv = MagicMock()
    tv.signal = signal
    tv.thesis_type = thesis_type
    tv.reason_codes = []
    tv.intended_horizon_bars = 2
    return tv


@patch("agent.core.cognition_orchestration.cognition_temporal_authority_enabled", return_value=False)
@patch("agent.core.cognition_orchestration.cognition_scorer_enabled", return_value=False)
@patch("agent.core.cognition_orchestration.cognition_selector_enabled", return_value=False)
def test_adjudication_identical_inputs_same_scores(
    _sel: MagicMock,
    _sco: MagicMock,
    _temp: MagicMock,
) -> None:
    tv = _thesis()
    strat = _strategy("LONG")
    ml = _ml_validation()
    mc = {"symbol": "BTCUSD", "features": {"adx_14": 28.0}}
    a = run_post_cognition_adjudication(
        thesis_verdict=tv,
        strategy_candidate=strat,
        ml_validation=ml,
        structure=MagicMock(),
        market_context=mc,
        collapse_rate=0.0,
        eps=0.001,
    )
    b = run_post_cognition_adjudication(
        thesis_verdict=tv,
        strategy_candidate=strat,
        ml_validation=ml,
        structure=MagicMock(),
        market_context=mc,
        collapse_rate=0.0,
        eps=0.001,
    )
    assert a.trade_score.score == b.trade_score.score
    assert a.ml_confirms == b.ml_confirms


@patch("agent.core.cognition_orchestration.cognition_temporal_authority_enabled", return_value=False)
@patch("agent.core.cognition_orchestration.cognition_scorer_enabled", return_value=False)
@patch("agent.core.cognition_orchestration.cognition_selector_enabled", return_value=False)
@patch("agent.core.cognition_orchestration.logger")
def test_parity_no_warning_when_matching(
    mock_logger: MagicMock,
    _sel: MagicMock,
    _sco: MagicMock,
    _temp: MagicMock,
) -> None:
    tv = _thesis()
    strat = _strategy()
    ml = _ml_validation()
    adj = run_post_cognition_adjudication(
        thesis_verdict=tv,
        strategy_candidate=strat,
        ml_validation=ml,
        structure=MagicMock(),
        market_context={"features": {}},
        collapse_rate=0.0,
        eps=0.001,
    )
    check_adjudication_parity(
        provisional=adj,
        authoritative=adj,
        provisional_thesis=tv,
        authoritative_thesis=tv,
    )
    mock_logger.warning.assert_not_called()
