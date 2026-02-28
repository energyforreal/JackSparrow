#!/usr/bin/env python3
"""Simple Performance Test"""

import asyncio
import time
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.core.mcp_orchestrator import MCPOrchestrator

async def main():
    print("🚀 Performance Test Starting...")

    # Initialize
    start_time = time.time()
    orchestrator = MCPOrchestrator()
    await orchestrator.initialize()
    init_time = time.time() - start_time
    print(f"✅ Initialization: {init_time:.2f}s")

    # Single prediction
    pred_start = time.time()
    result = await orchestrator.process_prediction_request(
        symbol="BTCUSD",
        context={"current_price": 50000, "market_regime": "bull"}
    )
    pred_time = time.time() - pred_start
    print(f"✅ Single prediction: {pred_time:.3f}s")
    print(f"   Signal: {result['decision']['signal']}")
    print(f"   Confidence: {result['decision']['confidence']:.3f}")

    # Cleanup
    await orchestrator.shutdown()
    print("✅ Test completed!")

if __name__ == "__main__":
    asyncio.run(main())
