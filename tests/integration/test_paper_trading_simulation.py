"""
Integration tests for paper trading simulation.

Uses real execution engine APIs: simulated fills via get_ticker (no place_order in paper),
position manager, manage_position for SL/TP, and RiskManager.Portfolio / Position helpers.
"""

import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("PAPER_TRADING_MODE", "true")

from agent.core.execution import execution_module
from agent.core.config import settings
from agent.events.event_bus import event_bus
from agent.events.schemas import RiskApprovedEvent, PositionClosedEvent
from agent.risk.risk_manager import RiskManager, Position as RMPosition


def _ticker_result(close: float, **extra) -> dict:
    """Delta-style ticker payload with fresh timestamp (required for paper fill freshness)."""
    body = {
        "close": close,
        "open": close * 0.998,
        "high": close * 1.002,
        "low": close * 0.997,
        "volume": 1000.0,
        "change_24h": 2.5,
        "timestamp": time.time(),
    }
    body.update(extra)
    return {"result": body}


@pytest.fixture
def mock_delta_client():
    """Mock Delta Exchange client that simulates API responses."""
    client = MagicMock()

    async def _get_ticker(*_a, **_kw):
        return _ticker_result(50000.0)

    client.get_ticker = AsyncMock(side_effect=_get_ticker)
    client.place_order = AsyncMock(
        side_effect=AssertionError("place_order should not be called in paper trading mode!")
    )
    return client


@pytest.fixture
def exec_module(mock_delta_client):
    """Configure execution module with mocked Delta client for tests."""
    execution_module.delta_client = mock_delta_client
    execution_module._initialized = True
    execution_module.exchange_connected = True
    execution_module.position_manager.positions.clear()
    return execution_module


@pytest.fixture(autouse=True)
def reset_execution_positions(exec_module):
    """Avoid position leakage between tests on the shared execution_module singleton."""
    exec_module.position_manager.positions.clear()
    yield
    exec_module.position_manager.positions.clear()


@pytest.fixture(autouse=True)
def no_redis_slow_path():
    """Avoid real Redis connections in execution paths (get_cache -> fast fallback)."""
    with patch("agent.core.redis_config.get_cache", new_callable=AsyncMock, return_value=None):
        with patch(
            "agent.core.paper_trade_entry.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            yield


@pytest.fixture
def risk_manager():
    return RiskManager()


@pytest.mark.asyncio
async def test_paper_trading_mode_prevents_real_api_calls(exec_module, mock_delta_client):
    """Paper trading does not call place_order; uses get_ticker for fill price."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow(),
            },
        )

        await exec_module._handle_risk_approved(event)

        mock_delta_client.place_order.assert_not_called()
        mock_delta_client.get_ticker.assert_called_once_with("BTCUSD")


@pytest.mark.asyncio
async def test_paper_trade_uses_current_market_price(exec_module, mock_delta_client):
    """Simulated BUY uses ticker mid clamped to approval price within max_slippage_percent, then spread/slip."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        mock_delta_client.get_ticker = AsyncMock(
            side_effect=lambda *_a, **_kw: _ticker_result(51000.0)
        )

        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow(),
            },
        )

        published_events = []
        original_publish = event_bus.publish

        async def capture_publish(event):
            published_events.append(event)

        event_bus.publish = capture_publish

        try:
            with patch("agent.core.execution.random.uniform", return_value=0.001):
                await exec_module._handle_risk_approved(event)

            fill_events = [
                e for e in published_events
                if hasattr(e, "payload") and "fill_price" in e.payload
            ]
            assert len(fill_events) > 0, "OrderFillEvent should be published"
            fill_price = fill_events[0].payload.get("fill_price")
            half = float(getattr(settings, "half_spread_pct", 0.0002) or 0.0002)
            expected_mid = 50250.0
            expected = expected_mid * (1.0 + half + 0.001)
            assert abs(fill_price - expected) < 1.0, (
                f"Fill should follow anchored mid {expected_mid} (+ costs), got {fill_price}"
            )
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_paper_trade_falls_back_to_approval_price_when_ticker_unavailable(
    exec_module, mock_delta_client
):
    """When ticker fetch fails, paper fill uses approval price as reference mid (logged)."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        mock_delta_client.get_ticker.side_effect = Exception("API error")

        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow(),
            },
        )

        published_events = []
        original_publish = event_bus.publish

        async def capture_publish(event):
            published_events.append(event)

        event_bus.publish = capture_publish

        try:
            with patch("agent.core.execution.random.uniform", return_value=0.001):
                await exec_module._handle_risk_approved(event)

            fill_events = [
                e for e in published_events
                if hasattr(e, "payload") and "fill_price" in e.payload
            ]
            assert len(fill_events) == 1, "OrderFillEvent should be published using price hint fallback"
            fill_price = fill_events[0].payload.get("fill_price")
            half = float(getattr(settings, "half_spread_pct", 0.0002) or 0.0002)
            expected = 50000.0 * (1.0 + half + 0.001)
            assert abs(fill_price - expected) < 1.0, fill_price
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_double_close_is_idempotent(exec_module, mock_delta_client):
    """Second close on same symbol must not emit a second PositionClosedEvent (ledger-safe)."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        exec_module.position_manager.open_position(
            symbol="BTCUSD",
            side="long",
            quantity=0.02,
            entry_price=50000.0,
            order_id="abc12345",
        )
        mock_delta_client.get_ticker = AsyncMock(
            side_effect=lambda *_a, **_kw: _ticker_result(51000.0)
        )
        closed_events = []
        original_publish = event_bus.publish

        async def capture_publish(ev):
            if isinstance(ev, PositionClosedEvent):
                closed_events.append(ev)

        event_bus.publish = capture_publish
        try:
            with patch("agent.core.execution.random.uniform", return_value=0.0005):
                r1 = await exec_module.close_position("BTCUSD", exit_reason="signal_reversal")
                r2 = await exec_module.close_position("BTCUSD", exit_reason="market_close")
            assert r1.success is True
            assert r2.success is False
            assert r2.error_message in (
                "already_closed",
                "No open position for BTCUSD",
            )
            assert len(closed_events) == 1
            mgr = await exec_module.manage_position("BTCUSD")
            assert mgr.get("reason") in ("position_not_open", "No position found")
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_risk_approved_rejects_overlapping_entry(exec_module, mock_delta_client):
    """Second entry on same symbol while a position is open is rejected (paper aligned with validate_trade)."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        exec_module.position_manager.open_position(
            symbol="BTCUSD",
            side="long",
            quantity=0.02,
            entry_price=50000.0,
            order_id="open1",
        )
        mock_delta_client.get_ticker.reset_mock()
        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,
                "price": 50000.0,
                "timestamp": datetime.utcnow(),
            },
        )
        await exec_module._handle_risk_approved(event)
        mock_delta_client.get_ticker.assert_not_called()


@pytest.mark.asyncio
async def test_manage_position_stop_loss_triggers_close(exec_module, mock_delta_client):
    """manage_position closes when mark breaches stop_loss (paper)."""
    with patch("agent.core.execution.settings.paper_trading_mode", True):
        exec_module.position_manager.open_position(
            symbol="BTCUSD",
            side="long",
            quantity=0.02,
            entry_price=50000.0,
            order_id="e1",
            stop_loss=49000.0,
            take_profit=55000.0,
        )
        mock_delta_client.get_ticker = AsyncMock(
            side_effect=lambda *_a, **_kw: _ticker_result(48800.0)
        )
        closed_events = []
        original_publish = event_bus.publish

        async def capture_publish(ev):
            if isinstance(ev, PositionClosedEvent):
                closed_events.append(ev)

        event_bus.publish = capture_publish
        try:
            exec_module.position_manager.update_position("BTCUSD", 48900.0)
            with patch("agent.core.execution.random.uniform", return_value=0.0005):
                out = await exec_module.manage_position("BTCUSD")
            assert out.get("position_status") == "closed"
            assert len(closed_events) == 1
            assert closed_events[0].payload.get("exit_reason") == "stop_loss_hit"
        finally:
            event_bus.publish = original_publish


def test_rm_position_should_close_long_stop():
    """RiskManager.Position SL/TP helpers (used by portfolio logic elsewhere)."""
    from datetime import datetime as dt

    p = RMPosition(
        symbol="BTCUSD",
        side="long",
        size=0.02,
        entry_price=50000.0,
        entry_time=dt.now(timezone.utc),
        stop_loss=49000.0,
        take_profit=52500.0,
    )
    p.update_price(48900.0)
    hit, reason = p.should_close()
    assert hit and reason == "stop_loss_hit"

    p2 = RMPosition(
        symbol="BTCUSD",
        side="long",
        size=0.02,
        entry_price=50000.0,
        entry_time=dt.now(timezone.utc),
        stop_loss=49000.0,
        take_profit=52500.0,
    )
    p2.update_price(52600.0)
    hit2, reason2 = p2.should_close()
    assert hit2 and reason2 == "take_profit_hit"


def test_rm_position_should_close_short_stop():
    from datetime import datetime as dt

    p = RMPosition(
        symbol="BTCUSD",
        side="short",
        size=0.02,
        entry_price=50000.0,
        entry_time=dt.now(timezone.utc),
        stop_loss=51000.0,
        take_profit=47500.0,
    )
    p.update_price(51100.0)
    hit, reason = p.should_close()
    assert hit and reason == "stop_loss_hit"

    p2 = RMPosition(
        symbol="BTCUSD",
        side="short",
        size=0.02,
        entry_price=50000.0,
        entry_time=dt.now(timezone.utc),
        stop_loss=51000.0,
        take_profit=47500.0,
    )
    p2.update_price(47500.0)
    hit2, reason2 = p2.should_close()
    assert hit2 and reason2 == "take_profit_hit"


@pytest.mark.asyncio
async def test_portfolio_record_trade_updates_cash(risk_manager):
    """Portfolio cash reflects realized PnL after record_trade."""
    await risk_manager.initialize(initial_balance=10000.0)
    assert risk_manager.portfolio is not None
    before = risk_manager.portfolio.cash_balance
    risk_manager.portfolio.record_trade({"symbol": "BTCUSD", "pnl": 20.0})
    assert abs(risk_manager.portfolio.cash_balance - (before + 20.0)) < 0.01


@pytest.mark.asyncio
async def test_consecutive_losses_via_portfolio_trade_history(risk_manager):
    """record_trade appends history; consecutive loss semantics can be asserted externally."""
    await risk_manager.initialize(initial_balance=10000.0)
    risk_manager.portfolio.record_trade({"symbol": "BTCUSD", "pnl": -20.0})
    risk_manager.portfolio.record_trade({"symbol": "BTCUSD", "pnl": -20.0})
    assert len(risk_manager.portfolio.trade_history) == 2
