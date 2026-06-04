"""Unit tests for portfolio-fraction entry lot sizing (fixed leverage)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.futures_utils import entry_lots_from_portfolio_margin, price_to_lots


def test_price_to_lots_scales_with_sixty_percent_portfolio() -> None:
    """60% of 100k INR margin budget yields more lots than fixed 1-lot sizing."""
    portfolio_inr = 100_000.0
    fraction = 0.60
    usdinr = 83.0
    leverage = 5
    entry_price = 50_000.0
    contract_value_btc = 0.001

    margin_inr = portfolio_inr * fraction
    usd_margin = margin_inr / usdinr
    lots = price_to_lots(
        usd_margin=usd_margin,
        btc_price=entry_price,
        leverage=leverage,
        contract_value_btc=contract_value_btc,
        max_lots=100,
        min_lots=1,
    )

    assert lots > 1
    assert lots == 72


def test_price_to_lots_unchanged_when_leverage_fixed_and_margin_lower() -> None:
    """Lowering margin fraction reduces lots; leverage held constant."""
    usdinr = 83.0
    leverage = 5
    entry_price = 50_000.0
    cv = 0.001

    high = price_to_lots(
        usd_margin=100_000 * 0.60 / usdinr,
        btc_price=entry_price,
        leverage=leverage,
        contract_value_btc=cv,
        max_lots=100,
        min_lots=1,
    )
    low = price_to_lots(
        usd_margin=100_000 * 0.20 / usdinr,
        btc_price=entry_price,
        leverage=leverage,
        contract_value_btc=cv,
        max_lots=100,
        min_lots=1,
    )

    assert high > low


@pytest.mark.asyncio
async def test_minimal_entry_quantity_from_portfolio_fraction(
    monkeypatch,
) -> None:
    """TradingHandler publishes quantity > fixed_lot_size when portfolio sizing is on."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from agent.core.config import settings
    from agent.core.product_specs import ContractSpecs
    import agent.events.handlers.trading_handler as trading_handler_mod
    from agent.events.handlers.trading_handler import TradingEventHandler
    from agent.events.schemas import DecisionReadyEvent, EventType

    monkeypatch.setattr(settings, "ai_signal_minimal_entry_gates", True)
    monkeypatch.setattr(settings, "portfolio_fraction_lot_sizing", True)
    monkeypatch.setattr(settings, "entry_portfolio_margin_fraction", 0.60)
    monkeypatch.setattr(settings, "isolated_margin_leverage", 5)
    monkeypatch.setattr(settings, "usdinr_fallback_rate", 83.0)

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(trading_handler_mod.event_bus, "publish", capture_publish)

    fake_state = MagicMock()
    fake_state.config = {"market_data": {"price": 50_000.0}}
    fake_state.portfolio_value = 100_000.0
    monkeypatch.setattr(
        trading_handler_mod,
        "context_manager",
        MagicMock(get_state=lambda: fake_state),
    )

    async def fake_specs(symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol="BTCUSD",
            contract_value_btc=0.001,
            tick_size=0.5,
            product_id=27,
            taker_commission_rate=0.0005,
        )

    monkeypatch.setattr(trading_handler_mod, "get_contract_specs", fake_specs)

    risk = MagicMock()
    risk._initialized = True
    risk.portfolio = None
    risk.validate_trade = AsyncMock(return_value={"approved": True, "reason": "ok"})
    handler = TradingEventHandler(risk_manager=risk, execution_module=None)
    monkeypatch.setattr(
        handler,
        "_get_current_price",
        AsyncMock(return_value=50_000.0),
    )
    monkeypatch.setattr(
        handler,
        "_get_available_cash_inr",
        AsyncMock(return_value=500_000.0),
    )
    monkeypatch.setattr(
        handler,
        "_get_usdinr_rate",
        AsyncMock(return_value=83.0),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.71,
            "position_size": 0.1,
            "timestamp": datetime.now(timezone.utc),
            "reasoning_chain": {
                "market_context": {"features": {}},
                "model_predictions": [{"signal": "BUY", "confidence": 0.71}],
            },
            "ml_signal_validated": True,
        },
    )

    await handler.handle_decision_ready_for_trading(event)

    risk_events = [
        e for e in published if getattr(e, "event_type", None) == EventType.RISK_APPROVED
    ]
    assert len(risk_events) == 1
    qty = float(risk_events[0].payload["quantity"])
    assert qty > float(getattr(settings, "fixed_lot_size", 1))
    assert risk_events[0].payload.get("entry_portfolio_margin_fraction") == 0.60
    risk.validate_trade.assert_awaited_once()
    call_kw = risk.validate_trade.await_args.kwargs
    assert call_kw["proposed_size"] == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_proposed_size_matches_entry_portfolio_fraction(monkeypatch) -> None:
    """validate_trade receives the same fraction used for lot sizing (BUG-01)."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from agent.core.config import settings
    from agent.core.product_specs import ContractSpecs
    import agent.events.handlers.trading_handler as trading_handler_mod
    from agent.events.handlers.trading_handler import TradingEventHandler
    from agent.events.schemas import DecisionReadyEvent

    monkeypatch.setattr(settings, "ai_signal_minimal_entry_gates", True)
    monkeypatch.setattr(settings, "portfolio_fraction_lot_sizing", True)
    monkeypatch.setattr(settings, "entry_portfolio_margin_fraction", 0.60)
    monkeypatch.setattr(settings, "max_position_size", 0.10)
    monkeypatch.setattr(settings, "isolated_margin_leverage", 5)
    monkeypatch.setattr(settings, "usdinr_fallback_rate", 83.0)

    monkeypatch.setattr(trading_handler_mod.event_bus, "publish", AsyncMock())

    fake_state = MagicMock()
    fake_state.config = {"market_data": {"price": 50_000.0}}
    fake_state.portfolio_value = 100_000.0
    monkeypatch.setattr(
        trading_handler_mod,
        "context_manager",
        MagicMock(get_state=lambda: fake_state),
    )

    async def fake_specs(symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol="BTCUSD",
            contract_value_btc=0.001,
            tick_size=0.5,
            product_id=27,
            taker_commission_rate=0.0005,
        )

    monkeypatch.setattr(trading_handler_mod, "get_contract_specs", fake_specs)

    risk = MagicMock()
    risk._initialized = True
    risk.portfolio = None
    risk.validate_trade = AsyncMock(return_value={"approved": True, "reason": "ok"})
    handler = TradingEventHandler(risk_manager=risk, execution_module=None)
    monkeypatch.setattr(handler, "_get_current_price", AsyncMock(return_value=50_000.0))
    monkeypatch.setattr(handler, "_get_available_cash_inr", AsyncMock(return_value=500_000.0))
    monkeypatch.setattr(handler, "_get_usdinr_rate", AsyncMock(return_value=83.0))
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        AsyncMock(side_effect=lambda c, mp: c),
    )

    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.71,
            "position_size": 0.1,
            "timestamp": datetime.now(timezone.utc),
            "reasoning_chain": {
                "market_context": {"features": {}},
                "model_predictions": [{"signal": "BUY", "confidence": 0.71}],
            },
            "ml_signal_validated": True,
        },
    )
    await handler.handle_decision_ready_for_trading(event)
    assert risk.validate_trade.await_called
    assert risk.validate_trade.await_args.kwargs["proposed_size"] == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_portfolio_value_inr_uses_live_wallet_when_provided(monkeypatch) -> None:
    """Sizing base must match live wallet so 60% margin leaves 40% reserve."""
    from unittest.mock import AsyncMock, MagicMock

    from agent.events.handlers.trading_handler import TradingEventHandler

    risk = MagicMock()
    risk.portfolio = MagicMock()
    risk.portfolio.total_value = 100_000.0 / 83.0
    handler = TradingEventHandler(risk_manager=risk, execution_module=None)
    monkeypatch.setattr(handler, "_get_usdinr_rate", AsyncMock(return_value=83.0))
    val = await handler._get_portfolio_value_inr(
        None,
        "BTCUSD",
        available_cash_inr=30_000.0,
    )
    assert val == pytest.approx(30_000.0, rel=0.01)


@pytest.mark.asyncio
async def test_portfolio_value_inr_falls_back_to_book_without_wallet(monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from agent.events.handlers.trading_handler import TradingEventHandler

    risk = MagicMock()
    risk.portfolio = MagicMock()
    risk.portfolio.total_value = 100_000.0 / 83.0
    handler = TradingEventHandler(risk_manager=risk, execution_module=None)
    monkeypatch.setattr(handler, "_get_usdinr_rate", AsyncMock(return_value=83.0))
    val = await handler._get_portfolio_value_inr(None, "BTCUSD")
    assert val == pytest.approx(100_000.0, rel=0.01)


def test_entry_lots_use_equity_budget_capped_by_cash() -> None:
    """60% of total equity, then affordable cash cap inside futures_utils."""
    lots, margin_inr = entry_lots_from_portfolio_margin(
        portfolio_value_inr=100_000.0,
        margin_fraction=0.60,
        usdinr_rate=83.0,
        btc_price=50_000.0,
        leverage=5,
        contract_value_btc=0.001,
        max_lots=100,
        min_lots=1,
        available_cash_inr=30_000.0,
    )
    assert margin_inr <= 60_000.0
    assert margin_inr >= 18_000.0
    assert lots >= 1
