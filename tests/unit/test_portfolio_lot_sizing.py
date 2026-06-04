"""Portfolio-fraction entry lot sizing (60% margin budget)."""

from agent.core.futures_utils import (
    entry_lots_from_portfolio_margin,
    max_affordable_lots_from_cash,
    price_to_lots,
)
from agent.risk.risk_manager import RiskManager
import pytest


def test_entry_lots_uses_sixty_percent_portfolio_margin_budget() -> None:
    portfolio_inr = 20000.0
    usdinr = 83.0
    btc = 100_000.0
    lots, margin_inr = entry_lots_from_portfolio_margin(
        portfolio_value_inr=portfolio_inr,
        margin_fraction=0.60,
        usdinr_rate=usdinr,
        btc_price=btc,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
        available_cash_inr=portfolio_inr,
    )
    expected = price_to_lots(
        usd_margin=12000.0 / usdinr,
        btc_price=btc,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
    )
    assert lots == expected
    assert lots >= 1
    assert margin_inr > 0


def test_entry_lots_wallet_base_leaves_forty_percent_reserve() -> None:
    """60% margin from wallet base must satisfy the 40% post-trade reserve rule."""
    usdinr = 86.0
    btc = 66_000.0
    wallet_inr = 15_740.0
    lots, margin_inr = entry_lots_from_portfolio_margin(
        portfolio_value_inr=wallet_inr,
        margin_fraction=0.60,
        usdinr_rate=usdinr,
        btc_price=btc,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
        available_cash_inr=wallet_inr,
        fee_reserve_fraction=0.02,
    )
    assert lots >= 1
    post_cash = wallet_inr - margin_inr
    assert post_cash >= wallet_inr * 0.40 - 1.0


def test_entry_lots_capped_by_live_wallet_not_book_value() -> None:
    """Book portfolio may be $10k+ while testnet wallet is ~₹14k."""
    usdinr = 83.0
    btc = 66_000.0
    book_inr = 830_000.0  # $10k book
    wallet_inr = 14_000.0
    lots, _margin_inr = entry_lots_from_portfolio_margin(
        portfolio_value_inr=book_inr,
        margin_fraction=0.60,
        usdinr_rate=usdinr,
        btc_price=btc,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
        available_cash_inr=wallet_inr,
    )
    max_lots = max_affordable_lots_from_cash(
        available_cash_inr=wallet_inr,
        usdinr_rate=usdinr,
        btc_price=btc,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
    )
    assert lots <= max_lots
    assert lots < 100
    assert lots >= 1


@pytest.mark.asyncio
async def test_validate_trade_budget_uses_margin_inr_override() -> None:
    rm = RiskManager()
    await rm.initialize(10000.0)
    result = await rm.validate_trade(
        symbol="BTCUSD",
        side="short",
        proposed_size=0.6,
        entry_price=100_000.0,
        required_balance_override=6000.0,
        available_balance_override=10000.0,
    )
    assert result["approved"] is True

    result_fail = await rm.validate_trade(
        symbol="BTCUSD",
        side="short",
        proposed_size=0.6,
        entry_price=100_000.0,
        required_balance_override=12000.0,
        available_balance_override=10000.0,
    )
    assert result_fail["approved"] is False
    assert "Insufficient budget" in result_fail["reason"]


@pytest.mark.asyncio
async def test_cash_reserve_uses_live_wallet_not_in_memory_book() -> None:
    """40% reserve must be of available cash, not portfolio.total_value × FX."""
    rm = RiskManager()
    await rm.initialize(20_000.0)  # stale USD book → would imply ~₹17.2L reserve floor
    wallet_inr = 15_740.0
    margin_inr = 9_444.0  # 60% of wallet (matches entry_portfolio_margin_fraction)
    result = await rm.validate_trade(
        symbol="BTCUSD",
        side="long",
        proposed_size=0.6,
        entry_price=66_000.0,
        required_balance_override=margin_inr,
        available_balance_override=wallet_inr,
    )
    assert result["approved"] is True
    assert "cash_reserve_breach" not in (result.get("reason") or "")
