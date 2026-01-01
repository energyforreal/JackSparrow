#!/usr/bin/env python3
"""Test paper trade entry logging for HOLD signals."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
script_path = Path(__file__).resolve()
project_root = script_path.parent
sys.path.insert(0, str(project_root))

from agent.events.schemas import DecisionReadyEvent
from agent.risk.risk_manager import RiskManager
from agent.core.config import settings

async def test_paper_trade_logging():
    """Test paper trade entry logging."""

    # Ensure paper trading mode
    settings.paper_trading_mode = True

    # Create risk manager
    risk_manager = RiskManager()

    # Create a HOLD decision event
    hold_event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "HOLD",
            "confidence": 0.45,
            "position_size": 0.0
        }
    )

    print("Testing paper trade entry logging for HOLD signal...")
    print(f"Paper trading mode: {settings.paper_trading_mode}")
    print(f"Event payload: {hold_event.payload}")

    # Process the decision
    await risk_manager._handle_decision_ready(hold_event)

    print("Test completed. Check logs above for paper_trade_entry_hold_signal")

if __name__ == "__main__":
    asyncio.run(test_paper_trade_logging())
