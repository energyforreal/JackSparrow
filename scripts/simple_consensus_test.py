#!/usr/bin/env python3
"""Simple Advanced Consensus Test"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.models.advanced_consensus import AdvancedConsensusEngine, ConsensusConfig, ModelPrediction
from datetime import datetime

async def test_consensus():
    print("Testing Advanced Consensus Engine")

    # Create test predictions
    predictions = [
        ModelPrediction("model_a", 0.3, 0.8, datetime.utcnow(), "xgboost"),
        ModelPrediction("model_b", 0.1, 0.6, datetime.utcnow(), "xgboost"),
        ModelPrediction("model_c", -0.2, 0.7, datetime.utcnow(), "xgboost"),
    ]

    # Test consensus calculation
    engine = AdvancedConsensusEngine(ConsensusConfig())
    result = await engine.calculate_consensus(predictions, {"volatility": 0.02})

    print(f"Consensus Prediction: {result.final_prediction:.3f}")
    print(f"Confidence: {result.confidence:.3f}")
    print(f"Risk Level: {result.risk_assessment['risk_level']}")
    print("Model Weights:", {k: round(v, 3) for k, v in result.model_weights.items()})

    # Test learning
    print("\nTesting Learning...")
    await engine.record_outcome(predictions, 0.15, {"volatility": 0.02})
    print("Learning recorded successfully")

    print("\nAdvanced Consensus Test Complete!")

if __name__ == "__main__":
    asyncio.run(test_consensus())
