#!/usr/bin/env python3
"""
Quick Performance Test for MCP Prediction Pipeline
"""

import asyncio
import time
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.core.mcp_orchestrator import MCPOrchestrator


async def main():
    """Run quick performance test."""
    print("🚀 Quick Performance Test")
    print("=" * 40)

    # Initialize
    print("Initializing MCP Orchestrator...")
    start_time = time.time()
    orchestrator = MCPOrchestrator()
    await orchestrator.initialize()
    init_time = time.time() - start_time
    print(".2f")
    # Test single prediction
    print("Running single prediction test...")
    pred_start = time.time()
    result = await orchestrator.process_prediction_request(
        symbol="BTCUSD",
        context={"current_price": 50000, "market_regime": "bull"}
    )
    pred_time = time.time() - pred_start
    print(".3f"
    # Test concurrent predictions
    print("Testing concurrent predictions...")
    concurrent_start = time.time()

    async def single_pred(i):
        return await orchestrator.process_prediction_request(
            symbol=f"BTCUSD_{i}",
            context={"current_price": 50000 + i*100, "task_id": i}
        )

    tasks = [single_pred(i) for i in range(3)]
    results = await asyncio.gather(*tasks)
    concurrent_time = time.time() - concurrent_start

    print(".3f"    print(".1f"
    # Results summary
    print("\n📊 Results Summary:")
    print(f"  Signal: {result['decision']['signal']}")
    print(f"  Confidence: {result['decision']['confidence']:.3f}")
    print(f"  Models Used: {result['models']['total_models']}")
    print(f"  Features Computed: {result['features']['count']}")
    print(f"  Reasoning Steps: {len(result['reasoning']['steps'])}")

    # Performance assessment
    print("\n🎯 Performance Assessment:")
    if pred_time < 2.0:
        status = "🟢 EXCELLENT"
    elif pred_time < 5.0:
        status = "🟡 GOOD"
    else:
        status = "🔴 NEEDS OPTIMIZATION"

    print(f"  Single Prediction: {status} ({pred_time:.3f}s)")
    print(f"  Concurrent Throughput: {'🟢 GOOD' if concurrent_time < 5.0 else '🟡 OK'}")

    # Cleanup
    await orchestrator.shutdown()
    print("\n✅ Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
