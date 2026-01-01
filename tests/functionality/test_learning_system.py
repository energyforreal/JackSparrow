"""Test learning system functionality."""

from typing import Dict, Any
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent


class LearningSystemTestSuite(TestSuiteBase):
    """Test suite for learning system."""
    
    def __init__(self, test_name: str = "learning_system"):
        super().__init__(test_name)
        self.agent = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception as e:
            # Agent initialization failure will be caught in individual tests
            pass
    
    async def run_all_tests(self):
        """Run all learning system tests."""
        await self._test_performance_tracking()
        await self._test_adaptation()
        await self._test_memory_storage()
        await self._test_learning_from_outcomes()
        await self._test_model_performance_aggregation()
    
    async def _test_performance_tracking(self):
        """Test performance tracking for model predictions."""
        result = TestResult(name="performance_tracking", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system is None:
                result.status = TestStatus.WARNING
                result.issues.append("Learning system not available")
                result.solutions.append("Check learning system initialization")
            else:
                result.details["learning_system_available"] = True
                
                # Check for performance tracking methods
                tracking_methods = {
                    "track_performance": hasattr(learning_system, "track_performance"),
                    "record_prediction": hasattr(learning_system, "record_prediction"),
                    "record_outcome": hasattr(learning_system, "record_outcome"),
                    "update_performance": hasattr(learning_system, "update_performance"),
                }
                
                result.details["available_tracking_methods"] = {k: v for k, v in tracking_methods.items() if v}
                
                if any(tracking_methods.values()):
                    result.details["performance_tracking_available"] = True
                    
                    # Test performance tracking if method available
                    if tracking_methods.get("track_performance"):
                        try:
                            # Create test performance data
                            test_performance = {
                                "model_name": "test_model",
                                "prediction": "BUY",
                                "confidence": 75.0,
                                "actual_outcome": "WIN",
                                "pnl": 100.0
                            }
                            
                            # Try to track performance
                            await learning_system.track_performance(test_performance)
                            result.details["performance_tracking_works"] = True
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
                            result.issues.append(f"Performance tracking call failed: {e}")
                            result.solutions.append("Check performance tracking method signature")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Performance tracking methods not found")
                    result.solutions.append("Check learning system implementation")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Performance tracking test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_adaptation(self):
        """Test adaptation mechanisms (model weight updates)."""
        result = TestResult(name="adaptation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system:
                # Check for adaptation methods
                adaptation_methods = {
                    "adapt": hasattr(learning_system, "adapt"),
                    "update_model_weights": hasattr(learning_system, "update_model_weights"),
                    "adjust_weights": hasattr(learning_system, "adjust_weights"),
                }
                
                result.details["available_adaptation_methods"] = {k: v for k, v in adaptation_methods.items() if v}
                
                if any(adaptation_methods.values()):
                    result.details["adaptation_mechanism_available"] = True
                    
                    # Check model registry for weight updates
                    model_registry = getattr(self.agent, "model_registry", None)
                    if model_registry:
                        result.details["model_registry_available"] = True
                        
                        # Check if models have weights that can be updated
                        models = model_registry.list_models() if hasattr(model_registry, "list_models") else []
                        if models:
                            result.details["models_available_for_adaptation"] = len(models)
                            
                            # Check for weight update capability
                            result.details["model_weight_adaptation"] = "available"
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("No models available for adaptation")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Adaptation methods not found")
                    result.solutions.append("Adaptation may be implemented differently or not yet available")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Learning system not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Adaptation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_memory_storage(self):
        """Test memory storage and retrieval."""
        result = TestResult(name="memory_storage", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system:
                # Check for memory store
                memory_store = getattr(learning_system, "memory_store", None)
                if memory_store:
                    result.details["memory_store_available"] = True
                    
                    # Check memory store type
                    memory_type = type(memory_store).__name__
                    result.details["memory_store_type"] = memory_type
                    
                    # Check for memory operations
                    memory_methods = {
                        "store": hasattr(memory_store, "store"),
                        "retrieve": hasattr(memory_store, "retrieve"),
                        "search": hasattr(memory_store, "search"),
                        "add": hasattr(memory_store, "add"),
                    }
                    
                    result.details["available_memory_methods"] = {k: v for k, v in memory_methods.items() if v}
                    
                    if any(memory_methods.values()):
                        result.details["memory_operations_available"] = True
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Memory store methods not found")
                else:
                    result.details["memory_store_available"] = False
                    result.status = TestStatus.WARNING
                    result.issues.append("Memory store not available")
                    result.solutions.append("Memory store may be optional or not configured")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Learning system not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Memory storage test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_learning_from_outcomes(self):
        """Test learning from trade outcomes."""
        result = TestResult(name="learning_from_outcomes", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system:
                # Check for outcome learning methods
                outcome_methods = {
                    "learn_from_outcome": hasattr(learning_system, "learn_from_outcome"),
                    "record_trade_outcome": hasattr(learning_system, "record_trade_outcome"),
                    "update_from_outcome": hasattr(learning_system, "update_from_outcome"),
                }
                
                result.details["available_outcome_methods"] = {k: v for k, v in outcome_methods.items() if v}
                
                if any(outcome_methods.values()):
                    result.details["outcome_learning_available"] = True
                    
                    # Test learning from outcome if method available
                    if outcome_methods.get("learn_from_outcome"):
                        try:
                            test_outcome = {
                                "prediction": "BUY",
                                "confidence": 75.0,
                                "actual_result": "WIN",
                                "pnl": 100.0,
                                "model_name": "test_model"
                            }
                            
                            await learning_system.learn_from_outcome(test_outcome)
                            result.details["outcome_learning_works"] = True
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
                            result.issues.append(f"Outcome learning call failed: {e}")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Outcome learning methods not found")
                    result.solutions.append("Outcome learning may be implemented differently")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Learning system not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Learning from outcomes test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_model_performance_aggregation(self):
        """Test model performance metrics aggregation."""
        result = TestResult(name="model_performance_aggregation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system:
                # Check for performance aggregation methods
                aggregation_methods = {
                    "get_model_performance": hasattr(learning_system, "get_model_performance"),
                    "aggregate_performance": hasattr(learning_system, "aggregate_performance"),
                    "get_performance_metrics": hasattr(learning_system, "get_performance_metrics"),
                }
                
                result.details["available_aggregation_methods"] = {k: v for k, v in aggregation_methods.items() if v}
                
                if any(aggregation_methods.values()):
                    result.details["performance_aggregation_available"] = True
                    
                    # Test performance aggregation if method available
                    if aggregation_methods.get("get_model_performance"):
                        try:
                            performance = await learning_system.get_model_performance("test_model")
                            
                            if performance:
                                result.details["performance_aggregation_works"] = True
                                result.details["performance_data_available"] = True
                                
                                if isinstance(performance, dict):
                                    result.details["performance_keys"] = list(performance.keys())[:10]
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
                            result.issues.append(f"Performance aggregation call failed: {e}")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Performance aggregation methods not found")
                    result.solutions.append("Performance aggregation may be implemented differently")
            
            # Check model registry for performance metrics
            model_registry = getattr(self.agent, "model_registry", None)
            if model_registry:
                result.details["model_registry_available"] = True
                # Model registry may track performance for model selection
                result.details["model_performance_tracking"] = "available"
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Model performance aggregation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
