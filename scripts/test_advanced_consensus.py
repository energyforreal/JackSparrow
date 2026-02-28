#!/usr/bin/env python3
"""
Test Advanced Consensus Algorithms

Demonstrates the enhanced consensus capabilities with real model predictions.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.models.advanced_consensus import AdvancedConsensusEngine, ConsensusConfig, ModelPrediction
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.model_discovery import ModelDiscovery
from datetime import datetime


async def test_advanced_consensus():
    """Test advanced consensus with real models."""
    print("🚀 Testing Advanced Consensus Algorithms")
    print("=" * 50)

    # Initialize registry and discover models
    print("Initializing model registry...")
    registry = MCPModelRegistry()
    discovery = ModelDiscovery(registry)
    discovered_models = await discovery.discover_models()

    print(f"✅ Discovered {len(discovered_models)} models")

    if not registry.models:
        print("❌ No models available for testing")
        return

    # Create test predictions (simulate what models would output)
    print("Creating test predictions...")
    predictions = []
    base_time = datetime.utcnow()

    # Simulate different model types with realistic predictions
    test_scenarios = [
        # Model name, prediction, confidence, model_type
        ("xgboost_classifier_BTCUSD_15m", 0.3, 0.8, "xgboost"),  # Moderate bullish
        ("xgboost_regressor_BTCUSD_15m", 0.1, 0.6, "xgboost"),   # Slight bullish
        ("xgboost_classifier_BTCUSD_1h", -0.2, 0.7, "xgboost"),  # Moderate bearish
        ("xgboost_regressor_BTCUSD_1h", -0.1, 0.5, "xgboost"),   # Slight bearish
        ("xgboost_classifier_BTCUSD_4h", 0.5, 0.9, "xgboost"),   # Strong bullish
        ("xgboost_regressor_BTCUSD_4h", 0.2, 0.4, "xgboost"),    # Weak bullish
    ]

    for i, (model_name, pred, conf, model_type) in enumerate(test_scenarios):
        # Only create predictions for models that actually exist
        if model_name in registry.models:
            prediction = ModelPrediction(
                model_name=model_name,
                prediction=pred,
                confidence=conf,
                timestamp=base_time,
                model_type=model_type,
                metadata={"test_scenario": i}
            )
            predictions.append(prediction)

    print(f"✅ Created {len(predictions)} test predictions")

    # Test different market regimes
    regimes = [
        {
            "name": "bull_trending",
            "context": {
                "volatility": 0.015,  # Low volatility
                "trend_strength": 0.8,  # Strong trend
                "volume_ratio": 1.2,  # Above average volume
                "current_price": 50000.0
            }
        },
        {
            "name": "high_volatility",
            "context": {
                "volatility": 0.045,  # High volatility
                "trend_strength": 0.3,  # Weak trend
                "volume_ratio": 1.8,  # High volume
                "current_price": 50000.0
            }
        },
        {
            "name": "ranging",
            "context": {
                "volatility": 0.008,  # Very low volatility
                "trend_strength": 0.2,  # Very weak trend
                "volume_ratio": 0.9,  # Below average volume
                "current_price": 50000.0
            }
        }
    ]

    # Test consensus engine with different configurations
    configs = [
        ("default", ConsensusConfig()),
        ("correlation_focused", ConsensusConfig(correlation_threshold=0.5, time_decay_factor=0.9)),
        ("regime_adaptive", ConsensusConfig(regime_adaptation_strength=0.5)),
    ]

    all_results = {}

    for config_name, config in configs:
        print(f"\n📊 Testing Configuration: {config_name}")
        print("-" * 30)

        engine = AdvancedConsensusEngine(config)

        for regime in regimes:
            print(f"\n🌍 Regime: {regime['name']}")

            # Calculate consensus
            result = await engine.calculate_consensus(
                predictions=predictions,
                market_context=regime["context"],
                consensus_method="adaptive"
            )

            print(".3f")
            print(".3f")
            print(",.3f")
            print(f"   Reasoning: {result.reasoning}")
            print(f"   Risk Level: {result.risk_assessment['risk_level']}")

            # Store results
            key = f"{config_name}_{regime['name']}"
            all_results[key] = {
                "prediction": result.final_prediction,
                "confidence": result.confidence,
                "weights": result.model_weights,
                "risk_level": result.risk_assessment["risk_level"]
            }

    # Demonstrate learning capability
    print("\n🧠 Testing Learning Capability")
    print("-" * 30)

    # Record some outcomes for learning
    learning_engine = AdvancedConsensusEngine(ConsensusConfig())

    # Simulate learning from outcomes
    outcomes = [
        (0.15, {"volatility": 0.02, "trend_strength": 0.7}),  # Positive outcome
        (-0.08, {"volatility": 0.03, "trend_strength": 0.4}), # Negative outcome
        (0.05, {"volatility": 0.025, "trend_strength": 0.6}), # Positive outcome
    ]

    for actual_outcome, context in outcomes:
        await learning_engine.record_outcome(predictions, actual_outcome, context)
        print(".3f")
    # Compare consensus before and after learning
    pre_learning = await learning_engine.calculate_consensus(
        predictions, {"volatility": 0.02, "trend_strength": 0.7}
    )

    print("\n📈 Consensus Evolution:")
    print(".3f")
    print(",.3f")
    # Show model weights evolution
    print("   Model Weights After Learning:")
    for model, weight in pre_learning.model_weights.items():
        print(".3f")
    print("\n🎉 Advanced Consensus Testing Complete!"    print(f"Tested {len(configs)} configurations × {len(regimes)} regimes = {len(configs) * len(regimes)} scenarios")
    print(f"Demonstrated learning from {len(outcomes)} outcomes")


async def main():
    """Main test function."""
    await test_advanced_consensus()


if __name__ == "__main__":
    asyncio.run(main())
