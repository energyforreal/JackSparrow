"""Portfolio Sharpe ratio computation."""

from __future__ import annotations

from backend.services.portfolio_service import PortfolioService


def test_sharpe_zero_for_insufficient_trades() -> None:
    assert PortfolioService._compute_sharpe_ratio([]) == 0.0
    assert PortfolioService._compute_sharpe_ratio([1.0]) == 0.0


def test_sharpe_positive_for_consistent_wins() -> None:
    pnls = [10.0, 12.0, 11.0, 9.0]
    sharpe = PortfolioService._compute_sharpe_ratio(pnls)
    assert sharpe > 0.0
