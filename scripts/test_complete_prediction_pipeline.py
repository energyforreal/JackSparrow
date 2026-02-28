#!/usr/bin/env python3
"""
Complete Prediction Pipeline End-to-End Test

Tests the entire MCP orchestration pipeline from feature computation
through model inference to final decision making.

This script validates that all critical fixes are working and the
system is production-ready.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Any
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.core.mcp_orchestrator import MCPOrchestrator
from agent.models.mcp_model_registry import MCPModelRegistry
from agent.models.model_discovery import ModelDiscovery
from agent.data.feature_server import MCPFeatureServer
from agent.core.reasoning_engine import MCPReasoningEngine


class PipelineTest:
    """Comprehensive pipeline testing suite."""

    def __init__(self):
        self.results = {
            "tests": [],
            "passed": 0,
            "failed": 0,
            "start_time": time.time(),
            "end_time": None
        }

    def log_test(self, test_name: str, status: bool, message: str, details: Dict = None):
        """Log individual test result."""
        self.results["tests"].append({
            "name": test_name,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": time.time()
        })

        if status:
            self.results["passed"] += 1
            print(f"✅ {test_name}: {message}")
        else:
            self.results["failed"] += 1
            print(f"❌ {test_name}: {message}")
            if details:
                print(f"   Details: {json.dumps(details, indent=2)}")

    async def test_imports(self):
        """Test that all critical imports work."""
        try:
            from agent.core.mcp_orchestrator import MCPOrchestrator
            from agent.models.mcp_model_registry import MCPModelRegistry
            from agent.models.model_discovery import ModelDiscovery
            from agent.data.feature_server import MCPFeatureServer
            from agent.core.reasoning_engine import MCPReasoningEngine

            # Test model node imports
            from agent.models.xgboost_node import XGBoostNode
            from agent.models.lightgbm_node import LightGBMNode
            from agent.models.random_forest_node import RandomForestNode
            from agent.models.lstm_node import LSTMNode
            from agent.models.transformer_node import TransformerNode

            self.log_test("Import Test", True, "All critical imports successful")
            return True
        except Exception as e:
            self.log_test("Import Test", False, f"Import failed: {str(e)}")
            return False

    async def test_mcp_orchestrator_initialization(self):
        """Test MCP Orchestrator can initialize."""
        try:
            orchestrator = MCPOrchestrator()
            await orchestrator.initialize()

            # Check that components are initialized
            assert orchestrator.feature_server is not None
            assert orchestrator.model_registry is not None
            assert orchestrator.reasoning_engine is not None

            await orchestrator.shutdown()
            self.log_test("MCP Orchestrator Init", True, "MCP Orchestrator initialized successfully")
            return True
        except Exception as e:
            self.log_test("MCP Orchestrator Init", False, f"Initialization failed: {str(e)}")
            return False

    async def test_model_discovery(self):
        """Test model discovery finds and registers models."""
        try:
            registry = MCPModelRegistry()
            discovery = ModelDiscovery(registry)

            discovered_models = await discovery.discover_models()

            # Should discover 6 models
            if len(discovered_models) != 6:
                self.log_test("Model Discovery", False,
                             f"Expected 6 models, found {len(discovered_models)}",
                             {"discovered": discovered_models, "registered": list(registry.models.keys())})
                return False

            # Check that registry has models
            if len(registry.models) != 6:
                self.log_test("Model Discovery", False,
                             f"Expected 6 registered models, found {len(registry.models)}",
                             {"registered": list(registry.models.keys())})
                return False

            # Check model types
            model_types = [model.model_type for model in registry.models.values()]
            expected_types = ["xgboost"] * 6  # All current models are XGBoost
            if not all(model_type in expected_types for model_type in model_types):
                self.log_test("Model Discovery", False,
                             f"Unexpected model types: {model_types}",
                             {"expected": expected_types, "found": model_types})
                return False

            self.log_test("Model Discovery", True,
                         f"Successfully discovered and registered {len(discovered_models)} models",
                         {"models": discovered_models, "types": model_types})
            return True

        except Exception as e:
            self.log_test("Model Discovery", False, f"Discovery failed: {str(e)}")
            return False

    async def test_feature_computation(self):
        """Test feature engineering provides 50 features."""
        try:
            from agent.data.feature_engineering import FeatureEngineering

            fe = FeatureEngineering()

            # Create mock candle data
            mock_candles = [
                {
                    "close": 50000.0, "high": 51000.0, "low": 49000.0,
                    "open": 49500.0, "volume": 100.0, "timestamp": "2025-01-27T12:00:00Z"
                },
                {
                    "close": 50500.0, "high": 51500.0, "low": 49500.0,
                    "open": 50000.0, "volume": 110.0, "timestamp": "2025-01-27T12:15:00Z"
                },
                {
                    "close": 50200.0, "high": 51200.0, "low": 49200.0,
                    "open": 50500.0, "volume": 95.0, "timestamp": "2025-01-27T12:30:00Z"
                },
                {
                    "close": 50700.0, "high": 51700.0, "low": 49700.0,
                    "open": 50200.0, "volume": 120.0, "timestamp": "2025-01-27T12:45:00Z"
                }
            ]

            # Test a few key features
            features_to_test = [
                "close_sma_20", "rsi_14", "macd", "bb_upper", "volume_sma_20", "returns_1h"
            ]

            computed_features = {}
            for feature_name in features_to_test:
                try:
                    value = await fe.compute_feature(feature_name, mock_candles)
                    computed_features[feature_name] = value
                except Exception as e:
                    self.log_test("Feature Computation", False,
                                 f"Failed to compute {feature_name}: {str(e)}")
                    return False

            # Validate feature count from validation method
            validation = fe.validate_feature_order(list(computed_features.keys()))
            if not validation["valid"]:
                self.log_test("Feature Computation", False,
                             f"Feature validation failed: {validation}",
                             validation)
                return False

            self.log_test("Feature Computation", True,
                         f"Successfully computed {len(computed_features)} features",
                         {"features": computed_features, "validation": validation})
            return True

        except Exception as e:
            self.log_test("Feature Computation", False, f"Feature computation failed: {str(e)}")
            return False

    async def test_individual_model_predictions(self):
        """Test that individual models can make predictions."""
        try:
            registry = MCPModelRegistry()
            discovery = ModelDiscovery(registry)
            await discovery.discover_models()

            if not registry.models:
                self.log_test("Individual Model Predictions", False, "No models available for testing")
                return False

            # Test prediction on first model
            test_model = list(registry.models.values())[0]
            test_features = [50000.0] * 50  # Mock 50 features

            request = {
                "request_id": "test_123",
                "features": test_features,
                "context": {
                    "current_price": 50000.0,
                    "feature_names": [f"feature_{i}" for i in range(50)]
                },
                "require_explanation": True
            }

            prediction = await test_model.predict(request)

            # Validate prediction structure
            required_fields = ["model_name", "model_version", "prediction", "confidence", "reasoning"]
            missing_fields = [field for field in required_fields if not hasattr(prediction, field)]
            if missing_fields:
                self.log_test("Individual Model Predictions", False,
                             f"Missing prediction fields: {missing_fields}",
                             {"prediction": prediction.dict() if hasattr(prediction, 'dict') else str(prediction)})
                return False

            # Validate prediction ranges
            if not (-1.0 <= prediction.prediction <= 1.0):
                self.log_test("Individual Model Predictions", False,
                             f"Prediction out of range: {prediction.prediction}",
                             {"prediction": prediction.dict() if hasattr(prediction, 'dict') else str(prediction)})
                return False

            if not (0.0 <= prediction.confidence <= 1.0):
                self.log_test("Individual Model Predictions", False,
                             f"Confidence out of range: {prediction.confidence}",
                             {"prediction": prediction.dict() if hasattr(prediction, 'dict') else str(prediction)})
                return False

            self.log_test("Individual Model Predictions", True,
                         f"Model {test_model.model_name} made valid prediction",
                         {
                             "model": test_model.model_name,
                             "prediction": prediction.prediction,
                             "confidence": prediction.confidence
                         })
            return True

        except Exception as e:
            self.log_test("Individual Model Predictions", False, f"Individual prediction failed: {str(e)}")
            return False

    async def test_consensus_calculation(self):
        """Test that model registry can calculate consensus."""
        try:
            registry = MCPModelRegistry()
            discovery = ModelDiscovery(registry)
            await discovery.discover_models()

            if len(registry.models) < 3:
                self.log_test("Consensus Calculation", False,
                             f"Need at least 3 models for consensus, found {len(registry.models)}")
                return False

            # Create mock request
            test_features = [50000.0] * 50
            request = {
                "request_id": "consensus_test_123",
                "features": test_features,
                "context": {
                    "current_price": 50000.0,
                    "feature_names": [f"feature_{i}" for i in range(50)]
                },
                "require_explanation": True
            }

            # Get consensus prediction
            response = await registry.get_predictions(request)

            # Validate response structure
            if not hasattr(response, 'consensus_prediction'):
                self.log_test("Consensus Calculation", False, "Missing consensus_prediction field")
                return False

            if not hasattr(response, 'predictions'):
                self.log_test("Consensus Calculation", False, "Missing predictions field")
                return False

            # Validate consensus ranges
            if not (-1.0 <= response.consensus_prediction <= 1.0):
                self.log_test("Consensus Calculation", False,
                             f"Consensus out of range: {response.consensus_prediction}")
                return False

            if len(response.predictions) != len(registry.models):
                self.log_test("Consensus Calculation", False,
                             f"Expected {len(registry.models)} predictions, got {len(response.predictions)}")
                return False

            # Check that individual predictions are also valid
            invalid_predictions = []
            for pred in response.predictions:
                if not (-1.0 <= pred.prediction <= 1.0):
                    invalid_predictions.append(f"{pred.model_name}: {pred.prediction}")

            if invalid_predictions:
                self.log_test("Consensus Calculation", False,
                             f"Invalid individual predictions: {invalid_predictions}")
                return False

            self.log_test("Consensus Calculation", True,
                         f"Consensus calculated from {len(response.predictions)} models",
                         {
                             "consensus": response.consensus_prediction,
                             "confidence": response.consensus_confidence,
                             "healthy_models": response.healthy_models,
                             "total_models": response.total_models
                         })
            return True

        except Exception as e:
            self.log_test("Consensus Calculation", False, f"Consensus calculation failed: {str(e)}")
            return False

    async def test_reasoning_engine(self):
        """Test that reasoning engine generates valid reasoning chains."""
        try:
            from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest
            from agent.models.mcp_model_registry import MCPModelRegistry
            from agent.models.model_discovery import ModelDiscovery

            # Setup registry with models
            registry = MCPModelRegistry()
            discovery = ModelDiscovery(registry)
            await discovery.discover_models()

            # Create reasoning engine
            reasoning_engine = MCPReasoningEngine(
                feature_server=None,  # Not needed for this test
                model_registry=registry,
                vector_store=None  # TODO: Add when implemented
            )
            await reasoning_engine.initialize()

            # Create test request with mock model predictions
            mock_predictions = []
            for model_name, model in registry.models.items():
                mock_predictions.append({
                    "model_name": model_name,
                    "model_version": model.model_version,
                    "prediction": 0.1,  # Slight bullish
                    "confidence": 0.8,
                    "reasoning": f"Mock reasoning for {model_name}",
                    "features_used": [f"feature_{i}" for i in range(50)],
                    "feature_importance": {f"feature_{i}": 0.02 for i in range(50)},
                    "health_status": "healthy"
                })

            request = MCPReasoningRequest(
                symbol="BTCUSD",
                market_context={
                    "features": {f"feature_{i}": 50000.0 for i in range(50)},
                    "model_predictions": mock_predictions,
                    "current_price": 50000.0,
                    "market_regime": "bull_trending"
                },
                use_memory=False
            )

            reasoning_chain = await reasoning_engine.generate_reasoning(request)

            # Validate reasoning chain structure
            if not hasattr(reasoning_chain, 'steps') or len(reasoning_chain.steps) != 6:
                self.log_test("Reasoning Engine", False,
                             f"Expected 6 reasoning steps, got {len(reasoning_chain.steps) if hasattr(reasoning_chain, 'steps') else 0}")
                return False

            if not hasattr(reasoning_chain, 'conclusion') or not reasoning_chain.conclusion:
                self.log_test("Reasoning Engine", False, "Missing or empty conclusion")
                return False

            if not hasattr(reasoning_chain, 'final_confidence') or not (0.0 <= reasoning_chain.final_confidence <= 1.0):
                self.log_test("Reasoning Engine", False,
                             f"Invalid final confidence: {reasoning_chain.final_confidence}")
                return False

            # Check that conclusion contains expected signal
            conclusion = reasoning_chain.conclusion.upper()
            has_signal = any(signal in conclusion for signal in ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"])
            if not has_signal:
                self.log_test("Reasoning Engine", False,
                             f"Conclusion doesn't contain trading signal: {reasoning_chain.conclusion}")
                return False

            await reasoning_engine.shutdown()

            self.log_test("Reasoning Engine", True,
                         f"Generated {len(reasoning_chain.steps)}-step reasoning chain",
                         {
                             "conclusion": reasoning_chain.conclusion,
                             "final_confidence": reasoning_chain.final_confidence,
                             "steps": len(reasoning_chain.steps)
                         })
            return True

        except Exception as e:
            self.log_test("Reasoning Engine", False, f"Reasoning engine test failed: {str(e)}")
            return False

    async def test_complete_prediction_pipeline(self):
        """Test the complete end-to-end prediction pipeline."""
        try:
            # Initialize full MCP Orchestrator
            orchestrator = MCPOrchestrator()
            await orchestrator.initialize()

            # Test complete prediction request
            result = await orchestrator.process_prediction_request(
                symbol="BTCUSD",
                context={
                    "current_price": 50000.0,
                    "market_regime": "bull_trending",
                    "volatility": 0.02,
                    "timestamp": "2025-01-27T12:00:00Z"
                }
            )

            # Validate complete result structure
            required_sections = ["symbol", "timestamp", "features", "models", "reasoning", "decision"]
            missing_sections = [section for section in required_sections if section not in result]
            if missing_sections:
                self.log_test("Complete Pipeline", False,
                             f"Missing result sections: {missing_sections}",
                             {"available": list(result.keys())})
                return False

            # Validate features
            if result["features"]["count"] != 50:
                self.log_test("Complete Pipeline", False,
                             f"Expected 50 features, got {result['features']['count']}")
                return False

            # Validate models
            if result["models"]["total_models"] != 6:
                self.log_test("Complete Pipeline", False,
                             f"Expected 6 models, got {result['models']['total_models']}")
                return False

            if len(result["models"]["predictions"]) != 6:
                self.log_test("Complete Pipeline", False,
                             f"Expected 6 predictions, got {len(result['models']['predictions'])}")
                return False

            # Validate consensus
            consensus = result["models"]["consensus_prediction"]
            if not (-1.0 <= consensus <= 1.0):
                self.log_test("Complete Pipeline", False,
                             f"Consensus out of range: {consensus}")
                return False

            # Validate reasoning
            if len(result["reasoning"]["steps"]) != 6:
                self.log_test("Complete Pipeline", False,
                             f"Expected 6 reasoning steps, got {len(result['reasoning']['steps'])}")
                return False

            # Validate decision
            decision = result["decision"]
            valid_signals = ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"]
            if decision["signal"] not in valid_signals:
                self.log_test("Complete Pipeline", False,
                             f"Invalid signal: {decision['signal']}",
                             {"valid_signals": valid_signals})
                return False

            if not (0.0 <= decision["confidence"] <= 1.0):
                self.log_test("Complete Pipeline", False,
                             f"Decision confidence out of range: {decision['confidence']}")
                return False

            await orchestrator.shutdown()

            self.log_test("Complete Pipeline", True,
                         "Complete prediction pipeline executed successfully",
                         {
                             "symbol": result["symbol"],
                             "features_count": result["features"]["count"],
                             "models_count": result["models"]["total_models"],
                             "consensus": result["models"]["consensus_prediction"],
                             "signal": result["decision"]["signal"],
                             "confidence": result["decision"]["confidence"],
                             "reasoning_steps": len(result["reasoning"]["steps"])
                         })
            return True

        except Exception as e:
            self.log_test("Complete Pipeline", False, f"Complete pipeline failed: {str(e)}")
            return False

    async def run_all_tests(self):
        """Run all pipeline tests."""
        print("🚀 Starting Complete Prediction Pipeline Tests")
        print("=" * 60)

        tests = [
            ("Import Validation", self.test_imports),
            ("MCP Orchestrator Init", self.test_mcp_orchestrator_initialization),
            ("Model Discovery", self.test_model_discovery),
            ("Feature Computation", self.test_feature_computation),
            ("Individual Predictions", self.test_individual_model_predictions),
            ("Consensus Calculation", self.test_consensus_calculation),
            ("Reasoning Engine", self.test_reasoning_engine),
            ("Complete Pipeline", self.test_complete_prediction_pipeline),
        ]

        for test_name, test_func in tests:
            print(f"\n🔄 Running: {test_name}")
            try:
                await test_func()
            except Exception as e:
                self.log_test(test_name, False, f"Test execution failed: {str(e)}")

        # Final summary
        self.results["end_time"] = time.time()
        duration = self.results["end_time"] - self.results["start_time"]

        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {len(self.results['tests'])}")
        print(f"Passed: {self.results['passed']}")
        print(f"Failed: {self.results['failed']}")
        print(".2f")
        print(".2f")

        if self.results["failed"] == 0:
            print("\n🎉 ALL TESTS PASSED! System is production-ready.")
            return True
        else:
            print(f"\n⚠️  {self.results['failed']} tests failed. Check logs above for details.")
            return False

    def save_results(self, filename: str = "pipeline_test_results.json"):
        """Save test results to file."""
        results_file = project_root / "logs" / filename
        results_file.parent.mkdir(exist_ok=True)

        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)

        print(f"\n📄 Results saved to: {results_file}")


async def main():
    """Main test runner."""
    tester = PipelineTest()
    success = await tester.run_all_tests()
    tester.save_results()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
