"""
Integration tests for paper trading simulation.

Tests that verify paper trading mode works correctly:
- No real API calls are made when paper trading is enabled
- Simulated trades execute correctly with realistic prices
- Portfolio tracking is accurate through trade cycles
- PnL calculations are correct for both long and short positions
- Position monitoring triggers exits correctly (stop loss/take profit)
- Portfolio value updates when positions close
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime

# Set up minimal environment for tests
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("PAPER_TRADING_MODE", "true")

from agent.core.execution import execution_module, ExecutionEngine
from agent.core.config import settings
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    RiskApprovedEvent,
    DecisionReadyEvent,
    PositionClosedEvent,
    MarketTickEvent,
    OrderFillEvent,
    EventType
)
from agent.core.context_manager import context_manager
from agent.risk.risk_manager import RiskManager


@pytest.fixture
def mock_delta_client():
    """Mock Delta Exchange client that simulates API responses."""
    client = MagicMock()
    client.get_ticker = AsyncMock(return_value={
        "result": {
            "close": 50000.0,
            "open": 49900.0,
            "high": 50100.0,
            "low": 49800.0,
            "volume": 1000.0,
            "change_24h": 2.5
        }
    })
    # Note: place_order should never be called in paper trading mode
    client.place_order = AsyncMock(side_effect=AssertionError(
        "place_order should not be called in paper trading mode!"
    ))
    return client


@pytest.fixture
def exec_module(mock_delta_client):
    """Configure execution module with mocked Delta client for tests."""
    execution_module.delta_client = mock_delta_client
    execution_module._initialized = True
    execution_module.exchange_connected = True
    return execution_module


@pytest.fixture
def risk_manager():
    """Create risk manager instance."""
    manager = RiskManager()
    return manager


@pytest.fixture(autouse=True)
def reset_context():
    """Reset context before each test (no-op if update_context not available)."""
    update_ctx = getattr(context_manager, "update_context", None)
    if update_ctx:
        update_ctx({
            "portfolio": {"value": 10000.0, "balance": 10000.0},
            "position": None,
            "position_opened": False,
            "position_closed": False
        })
    yield
    if update_ctx:
        update_ctx({
            "portfolio": {"value": 10000.0, "balance": 10000.0},
            "position": None,
            "position_opened": False,
            "position_closed": False
        })


@pytest.mark.asyncio
async def test_paper_trading_mode_prevents_real_api_calls(exec_module, mock_delta_client):
    """Test that paper trading mode prevents real place_order API calls."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,  # 0.02 BTC (~$1000 at $50k)
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow()
            }
        )
        
        await exec_module._handle_risk_approved(event)
        
        # Verify place_order was NOT called (paper trading simulates)
        mock_delta_client.place_order.assert_not_called()
        
        # Verify get_ticker WAS called (to get current price for simulation)
        mock_delta_client.get_ticker.assert_called_once_with("BTCUSD")


@pytest.mark.asyncio
async def test_paper_trade_uses_current_market_price(exec_module, mock_delta_client):
    """Test that simulated trades use current market price from ticker."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Set ticker to return specific price different from requested
        mock_delta_client.get_ticker.return_value = {
            "result": {
                "close": 51000.0,  # Market price (different from requested 50000.0)
                "open": 50900.0,
                "high": 51100.0,
                "low": 50800.0,
                "volume": 1000.0,
                "change_24h": 2.5
            }
        }
        
        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,  # 0.02 BTC
                "price": 50000.0,  # Requested price (should be ignored for fill)
                "risk_score": 0.8,
                "timestamp": datetime.utcnow()
            }
        )
        
        # Capture published events
        published_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            published_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_risk_approved(event)
            
            # Find OrderFillEvent
            fill_events = [
                e for e in published_events 
                if hasattr(e, 'payload') and 'fill_price' in e.payload
            ]
            assert len(fill_events) > 0, "OrderFillEvent should be published"
            
            # Verify fill price is from ticker (~51000), not requested price (50000)
            fill_price = fill_events[0].payload.get('fill_price')
            assert 50900 <= fill_price <= 51200, (
                f"Fill price should be from ticker (~51000), got {fill_price}"
            )
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_paper_trade_fails_when_ticker_unavailable(exec_module, mock_delta_client):
    """Test that paper trades are not executed when ticker fetch fails (no fallback)."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Make ticker fetch fail
        mock_delta_client.get_ticker.side_effect = Exception("API error")
        
        event = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 0.02,  # 0.02 BTC
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow()
            }
        )
        
        published_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            published_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_risk_approved(event)
            
            # Verify no OrderFillEvent is published when ticker fails
            fill_events = [
                e for e in published_events 
                if hasattr(e, 'payload') and 'fill_price' in e.payload
            ]
            assert len(fill_events) == 0, (
                "OrderFillEvent should NOT be published when ticker fails (no fallback)"
            )
        finally:
            event_bus.publish = original_publish


@pytest.mark.skip(reason="Uses _handle_exit_decision and update_context - not yet implemented")
@pytest.mark.asyncio
async def test_pnl_calculation_long_position_profit(exec_module):
    """Test PnL calculation for profitable long position."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Set up long position: $1000 position at $50k entry
        # Asset quantity = 1000 / 50000 = 0.02 BTC
        context_manager.update_context({
            "portfolio": {"value": 10000.0, "balance": 10000.0},
            "position": {
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 1000.0,  # Dollar value
                "entry_price": 50000.0,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
        # Exit at $51k (profit)
        exec_module.delta_client.get_ticker = AsyncMock(return_value={
            "result": {"close": 51000.0}
        })
        
        exit_event = DecisionReadyEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "signal": "SELL",
                "exit_reason": "take_profit",
                "current_price": 51000.0,
                "timestamp": datetime.utcnow()
            }
        )
        
        published_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            if isinstance(event, PositionClosedEvent):
                published_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_exit_decision(exit_event)
            
            assert len(published_events) > 0, "PositionClosedEvent should be published"
            pnl = published_events[0].payload.get('pnl')
            
            # Expected: (51000 - 50000) * (1000 / 50000) = 1000 * 0.02 = 20.0
            expected_pnl = (51000.0 - 50000.0) * (1000.0 / 50000.0)
            assert abs(pnl - expected_pnl) < 0.01, (
                f"PnL should be ~{expected_pnl}, got {pnl}"
            )
            assert pnl > 0, f"PnL should be positive for profitable trade, got {pnl}"
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_pnl_calculation_short_position_profit(execution_module):
    """Test PnL calculation for profitable short position."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Set up short position: $1000 position at $50k entry
        context_manager.update_context({
            "portfolio": {"value": 10000.0, "balance": 10000.0},
            "position": {
                "symbol": "BTCUSD",
                "side": "SELL",  # Short position
                "quantity": 1000.0,
                "entry_price": 50000.0,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
        # Exit at $49k (profit for short)
        exec_module.delta_client.get_ticker = AsyncMock(return_value={
            "result": {"close": 49000.0}
        })
        
        exit_event = DecisionReadyEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "signal": "BUY",  # Close short
                "exit_reason": "take_profit",
                "current_price": 49000.0,
                "timestamp": datetime.utcnow()
            }
        )
        
        published_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            if isinstance(event, PositionClosedEvent):
                published_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_exit_decision(exit_event)
            
            assert len(published_events) > 0, "PositionClosedEvent should be published"
            pnl = published_events[0].payload.get('pnl')
            
            # Expected: (50000 - 49000) * (1000 / 50000) = 1000 * 0.02 = 20.0
            expected_pnl = (50000.0 - 49000.0) * (1000.0 / 50000.0)
            assert abs(pnl - expected_pnl) < 0.01, (
                f"PnL should be ~{expected_pnl}, got {pnl}"
            )
            assert pnl > 0, f"PnL should be positive for profitable short, got {pnl}"
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_stop_loss_trigger_long_position(risk_manager):
    """Test that stop loss triggers correctly for long positions."""
    await risk_manager.initialize()
    
    # Set up long position with stop loss
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": {
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1000.0,
            "entry_price": 50000.0,
            "stop_loss": 49000.0,  # 2% stop loss
            "take_profit": 52500.0,
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Market tick below stop loss
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "BTCUSD",
            "price": 48900.0,  # Below stop loss
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        assert len(exit_decisions) > 0, "Exit decision should be emitted when stop loss hit"
        exit_reason = exit_decisions[0].payload.get('exit_reason')
        assert exit_reason == "stop_loss", (
            f"Exit reason should be 'stop_loss', got '{exit_reason}'"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_take_profit_trigger_long_position(risk_manager):
    """Test that take profit triggers correctly for long positions."""
    await risk_manager.initialize()
    
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": {
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1000.0,
            "entry_price": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 52500.0,  # 5% take profit
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Market tick at take profit
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "BTCUSD",
            "price": 52500.0,  # At take profit
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        assert len(exit_decisions) > 0, "Exit decision should be emitted when take profit hit"
        exit_reason = exit_decisions[0].payload.get('exit_reason')
        assert exit_reason == "take_profit", (
            f"Exit reason should be 'take_profit', got '{exit_reason}'"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_stop_loss_trigger_short_position(risk_manager):
    """Test that stop loss triggers correctly for short positions."""
    await risk_manager.initialize()
    
    # Set up short position (stop loss is ABOVE entry for shorts)
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": {
            "symbol": "BTCUSD",
            "side": "SELL",  # Short position
            "quantity": 1000.0,
            "entry_price": 50000.0,
            "stop_loss": 51000.0,  # For short: stop loss is above entry
            "take_profit": 47500.0,
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Market tick above stop loss (bad for short)
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "BTCUSD",
            "price": 51100.0,  # Above stop loss
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        assert len(exit_decisions) > 0, "Exit decision should be emitted when stop loss hit"
        exit_reason = exit_decisions[0].payload.get('exit_reason')
        assert exit_reason == "stop_loss", (
            f"Exit reason should be 'stop_loss', got '{exit_reason}'"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_take_profit_trigger_short_position(risk_manager):
    """Test that take profit triggers correctly for short positions."""
    await risk_manager.initialize()
    
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": {
            "symbol": "BTCUSD",
            "side": "SELL",  # Short position
            "quantity": 1000.0,
            "entry_price": 50000.0,
            "stop_loss": 51000.0,
            "take_profit": 47500.0,  # For short: take profit is below entry
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Market tick at take profit (below entry for short)
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "BTCUSD",
            "price": 47500.0,  # At take profit
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        assert len(exit_decisions) > 0, "Exit decision should be emitted when take profit hit"
        exit_reason = exit_decisions[0].payload.get('exit_reason')
        assert exit_reason == "take_profit", (
            f"Exit reason should be 'take_profit', got '{exit_reason}'"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_portfolio_value_updates_on_position_close(exec_module, risk_manager):
    """Test that portfolio value is updated when position closes via PositionClosedEvent."""
    await risk_manager.initialize()
    
    initial_value = 10000.0
    context_manager.update_context({
        "portfolio": {"value": initial_value, "balance": initial_value}
    })
    
    # Simulate position close with profit
    position_closed_event = PositionClosedEvent(
        source="execution_module",
        payload={
            "position_id": "test_pos_1",
            "symbol": "BTCUSD",
            "entry_price": 50000.0,
            "exit_price": 51000.0,
            "pnl": 20.0,  # $20 profit
            "duration_seconds": 3600.0,
            "exit_reason": "take_profit",
            "timestamp": datetime.utcnow()
        }
    )
    
    # Process position closed event
    await risk_manager._handle_position_closed(position_closed_event)
    
    # Verify portfolio value was updated
    context = context_manager.get_current_context()
    expected_value = initial_value + 20.0
    assert abs(context.portfolio_value - expected_value) < 0.01, (
        f"Portfolio value should be {expected_value}, got {context.portfolio_value}"
    )


@pytest.mark.asyncio
async def test_portfolio_tracking_full_trade_cycle(exec_module, risk_manager):
    """Test portfolio tracking through complete trade cycle: entry -> monitoring -> exit."""
    await risk_manager.initialize()
    
    initial_value = 10000.0
    context_manager.update_context({
        "portfolio": {"value": initial_value, "balance": initial_value}
    })
    
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Step 1: Entry trade
        exec_module.delta_client.get_ticker = AsyncMock(return_value={
            "result": {"close": 50000.0}
        })
        
        risk_approved = RiskApprovedEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 1000.0,  # $1000 position
                "price": 50000.0,
                "risk_score": 0.8,
                "timestamp": datetime.utcnow()
            }
        )
        
        await execution_module._handle_risk_approved(risk_approved)
        
        # Verify position opened
        context = context_manager.get_current_context()
        assert context.position is not None, "Position should be opened"
        assert context.position_opened is True, "position_opened should be True"
        
        # Step 2: Monitor position (price moves up)
        tick_event = MarketTickEvent(
            source="market_data_service",
            payload={
                "symbol": "BTCUSD",
                "price": 51000.0,  # Price moved up
                "volume": 1000.0,
                "timestamp": datetime.utcnow()
            }
        )
        
        # Position should still be open (not at take profit yet)
        await risk_manager._handle_market_tick(tick_event)
        context = context_manager.get_current_context()
        assert context.position is not None, "Position should still be open"
        
        # Step 3: Exit at take profit
        exec_module.delta_client.get_ticker = AsyncMock(return_value={
            "result": {"close": 52500.0}  # At take profit
        })
        
        exit_event = DecisionReadyEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "signal": "SELL",
                "exit_reason": "take_profit",
                "current_price": 52500.0,
                "timestamp": datetime.utcnow()
            }
        )
        
        position_closed_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            if isinstance(event, PositionClosedEvent):
                position_closed_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_exit_decision(exit_event)
            
            # Verify position closed event
            assert len(position_closed_events) > 0, "PositionClosedEvent should be published"
            pnl = position_closed_events[0].payload.get('pnl')
            assert pnl > 0, f"PnL should be positive, got {pnl}"
            
            # Verify position is cleared
            context = context_manager.get_current_context()
            assert context.position is None, "Position should be cleared"
            assert context.position_opened is False, "position_opened should be False"
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_exit_reason_detection_for_short_positions(execution_module):
    """Test that exit reason is correctly detected for short positions."""
    with patch('agent.core.execution.settings.paper_trading_mode', True):
        # Set up short position
        context_manager.update_context({
            "portfolio": {"value": 10000.0, "balance": 10000.0},
            "position": {
                "symbol": "BTCUSD",
                "side": "SELL",  # Short
                "quantity": 1000.0,
                "entry_price": 50000.0,
                "stop_loss": 51000.0,  # Above entry for short
                "take_profit": 47500.0,  # Below entry for short
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
        # Exit at take profit (price below entry)
        exec_module.delta_client.get_ticker = AsyncMock(return_value={
            "result": {"close": 47500.0}
        })
        
        exit_event = DecisionReadyEvent(
            source="risk_manager",
            payload={
                "symbol": "BTCUSD",
                "signal": "BUY",  # Close short
                "exit_reason": None,  # Should be auto-detected
                "current_price": 47500.0,
                "timestamp": datetime.utcnow()
            }
        )
        
        position_closed_events = []
        original_publish = event_bus.publish
        
        async def capture_publish(event):
            if isinstance(event, PositionClosedEvent):
                position_closed_events.append(event)
            return await original_publish(event)
        
        event_bus.publish = capture_publish
        
        try:
            await exec_module._handle_exit_decision(exit_event)
            
            assert len(position_closed_events) > 0, "PositionClosedEvent should be published"
            exit_reason = position_closed_events[0].payload.get('exit_reason')
            assert exit_reason == "take_profit", (
                f"Exit reason should be auto-detected as 'take_profit', got '{exit_reason}'"
            )
        finally:
            event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_position_monitoring_ignores_wrong_symbol(risk_manager):
    """Test that position monitoring ignores market ticks for different symbols."""
    await risk_manager.initialize()
    
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": {
            "symbol": "BTCUSD",
            "side": "BUY",
            "quantity": 1000.0,
            "entry_price": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 52500.0,
            "timestamp": datetime.utcnow().isoformat()
        }
    })
    
    # Market tick for different symbol
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "ETHUSD",  # Different symbol
            "price": 3000.0,
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        # No exit decision should be emitted for wrong symbol
        assert len(exit_decisions) == 0, (
            "Exit decision should not be emitted for different symbol"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_position_monitoring_handles_no_position(risk_manager):
    """Test that position monitoring handles case when no position exists."""
    await risk_manager.initialize()
    
    # Ensure no position
    context_manager.update_context({
        "portfolio": {"value": 10000.0, "balance": 10000.0},
        "position": None
    })
    
    tick_event = MarketTickEvent(
        source="market_data_service",
        payload={
            "symbol": "BTCUSD",
            "price": 50000.0,
            "volume": 1000.0,
            "timestamp": datetime.utcnow()
        }
    )
    
    exit_decisions = []
    original_publish = event_bus.publish
    
    async def capture_publish(event):
        if isinstance(event, DecisionReadyEvent) and event.payload.get('exit_reason'):
            exit_decisions.append(event)
        return await original_publish(event)
    
    event_bus.publish = capture_publish
    
    try:
        await risk_manager._handle_market_tick(tick_event)
        
        # No exit decision should be emitted when no position
        assert len(exit_decisions) == 0, (
            "Exit decision should not be emitted when no position exists"
        )
    finally:
        event_bus.publish = original_publish


@pytest.mark.asyncio
async def test_consecutive_losses_tracking(risk_manager):
    """Test that consecutive losses are tracked correctly."""
    await risk_manager.initialize()
    
    initial_value = 10000.0
    context_manager.update_context({
        "portfolio": {"value": initial_value, "balance": initial_value}
    })
    
    # Simulate two losing trades
    for i in range(2):
        position_closed_event = PositionClosedEvent(
            source="execution_module",
            payload={
                "position_id": f"test_pos_{i}",
                "symbol": "BTCUSD",
                "entry_price": 50000.0,
                "exit_price": 49000.0,  # Loss
                "pnl": -20.0,  # $20 loss
                "duration_seconds": 3600.0,
                "exit_reason": "stop_loss",
                "timestamp": datetime.utcnow()
            }
        )
        
        await risk_manager._handle_position_closed(position_closed_event)
    
    # Verify consecutive losses tracked
    context = context_manager.get_current_context()
    assert context.consecutive_losses == 2, (
        f"Consecutive losses should be 2, got {context.consecutive_losses}"
    )


@pytest.mark.asyncio
async def test_consecutive_losses_reset_on_win(risk_manager):
    """Test that consecutive losses reset when a winning trade occurs."""
    await risk_manager.initialize()
    
    # First, record a loss
    position_closed_loss = PositionClosedEvent(
        source="execution_module",
        payload={
            "position_id": "test_pos_loss",
            "symbol": "BTCUSD",
            "entry_price": 50000.0,
            "exit_price": 49000.0,
            "pnl": -20.0,
            "duration_seconds": 3600.0,
            "exit_reason": "stop_loss",
            "timestamp": datetime.utcnow()
        }
    )
    
    await risk_manager._handle_position_closed(position_closed_loss)
    
    # Then record a win
    position_closed_win = PositionClosedEvent(
        source="execution_module",
        payload={
            "position_id": "test_pos_win",
            "symbol": "BTCUSD",
            "entry_price": 50000.0,
            "exit_price": 51000.0,
            "pnl": 20.0,  # Profit
            "duration_seconds": 3600.0,
            "exit_reason": "take_profit",
            "timestamp": datetime.utcnow()
        }
    )
    
    await risk_manager._handle_position_closed(position_closed_win)
    
    # Verify consecutive losses reset
    context = context_manager.get_current_context()
    assert context.consecutive_losses == 0, (
        f"Consecutive losses should reset to 0 after win, got {context.consecutive_losses}"
    )
