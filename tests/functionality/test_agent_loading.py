"""Test agent loading and initialization functionality."""

import asyncio
from typing import Dict, Any
from datetime import datetime

from tests.functionality.utils import (
    TestSuiteBase, TestResult, TestStatus, measure_time
)
from tests.functionality.fixtures import get_shared_agent, check_services_health


class AgentLoadingTestSuite(TestSuiteBase):
    """Test suite for agent loading and initialization."""
    
    def __init__(self, test_name: str = "agent_loading"):
        super().__init__(test_name)
        self.agent = None
    
    async def setup(self):
        """Setup shared resources."""
        # Check service health first
        health = await check_services_health()
        if health.get("backend", {}).get("status") != "up":
            self.add_result(TestResult(
                name="service_health_check",
                status=TestStatus.WARNING,
                duration_ms=0.0,
                issues=["Backend service may not be available"],
                solutions=["Ensure backend is running on http://localhost:8000"]
            ))
    
    async def run_all_tests(self):
        """Run all agent loading tests."""
        # Test 1: Agent initialization
        await self._test_agent_initialization()
        
        # Test 2: Model discovery
        await self._test_model_discovery()
        
        # Test 3: MCP Orchestrator initialization
        await self._test_mcp_orchestrator()
        
        # Test 4: Feature Server startup
        await self._test_feature_server()
        
        # Test 5: Model Registry initialization
        await self._test_model_registry()
        
        # Test 6: State machine initialization
        await self._test_state_machine()
        
        # Test 7: Database connections
        await self._test_database_connection()
        
        # Test 8: Redis connections
        await self._test_redis_connection()
        
        # Test 9: Delta Exchange client initialization
        await self._test_delta_client()
        
        # Test 10: Vector memory store initialization
        await self._test_vector_memory_store()
    
    async def _test_agent_initialization(self):
        """Test agent initialization sequence."""
        result = TestResult(name="agent_initialization", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            self.agent = await get_shared_agent()
            
            # Verify agent instance
            if self.agent is None:
                result.status = TestStatus.FAIL
                result.issues.append("Agent instance is None")
                result.solutions.append("Check agent initialization code")
            else:
                result.details["agent_initialized"] = True
                result.details["session_id"] = getattr(self.agent, "session_id", None)
                result.details["default_symbol"] = getattr(self.agent, "default_symbol", None)
                result.details["trading_mode"] = getattr(self.agent, "trading_mode", None)
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Agent initialization failed: {e}")
            result.solutions.append("Check agent dependencies and configuration")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_model_discovery(self):
        """Test model discovery and registration."""
        result = TestResult(name="model_discovery", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check model discovery
            model_discovery = getattr(self.agent, "model_discovery", None)
            if model_discovery is None:
                result.status = TestStatus.FAIL
                result.issues.append("Model discovery not initialized")
                result.solutions.append("Check agent initialization sequence")
            else:
                result.details["model_discovery_initialized"] = True
                
                # Check model registry
                model_registry = getattr(self.agent, "model_registry", None)
                if model_registry:
                    # Get models from registry (includes both MODEL_PATH and MODEL_DIR)
                    models = model_registry.list_models() if hasattr(model_registry, "list_models") else []
                    
                    # Also check if MODEL_PATH is set and model exists
                    from agent.core.config import settings
                    from pathlib import Path
                    model_path_configured = bool(settings.model_path)
                    model_path_exists = False
                    if settings.model_path:
                        model_file = Path(settings.model_path)
                        model_path_exists = model_file.exists()
                    
                    result.details["models_discovered"] = len(models)
                    result.details["model_names"] = models
                    result.details["model_path_configured"] = model_path_configured
                    result.details["model_path_exists"] = model_path_exists
                    result.details["model_dir"] = str(model_discovery.model_dir)
                    
                    # Check total models (from both sources)
                    total_models = len(models)
                    if model_path_configured and model_path_exists:
                        # MODEL_PATH model should be in the list, but if not, count it separately
                        if total_models == 0:
                            result.status = TestStatus.WARNING
                            result.issues.append("No models discovered from MODEL_DIR, but MODEL_PATH is configured")
                            result.solutions.append("Check if MODEL_PATH model is loaded correctly")
                        else:
                            # Models found - check if MODEL_PATH model is included
                            result.details["models_from_model_path"] = model_path_exists
                            result.details["models_from_model_dir"] = total_models
                    elif total_models == 0:
                        result.status = TestStatus.WARNING
                        result.issues.append("No models discovered")
                        result.solutions.append("Check model_storage directory and MODEL_DIR configuration, or set MODEL_PATH")
                else:
                    result.status = TestStatus.FAIL
                    result.issues.append("Model registry not initialized")
                    result.solutions.append("Check model registry initialization")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Model discovery test failed: {e}")
            result.solutions.append("Check model discovery implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_mcp_orchestrator(self):
        """Test MCP Orchestrator initialization."""
        result = TestResult(name="mcp_orchestrator", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP Orchestrator not initialized")
                result.solutions.append("Check MCP orchestrator initialization")
            else:
                result.details["mcp_orchestrator_initialized"] = True
                
                # Check components
                feature_server = getattr(mcp_orchestrator, "feature_server", None)
                model_registry = getattr(mcp_orchestrator, "model_registry", None)
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                
                result.details["feature_server"] = feature_server is not None
                result.details["model_registry"] = model_registry is not None
                result.details["reasoning_engine"] = reasoning_engine is not None
                
                if not all([feature_server, model_registry, reasoning_engine]):
                    result.status = TestStatus.WARNING
                    result.issues.append("Some MCP components not initialized")
                    result.solutions.append("Check MCP orchestrator component initialization")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"MCP orchestrator test failed: {e}")
            result.solutions.append("Check MCP orchestrator implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_feature_server(self):
        """Test Feature Server startup."""
        result = TestResult(name="feature_server", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            feature_server_api = getattr(self.agent, "feature_server_api", None)
            if feature_server_api is None:
                result.status = TestStatus.FAIL
                result.issues.append("Feature Server API not initialized")
                result.solutions.append("Check feature server API initialization")
            else:
                result.details["feature_server_api_initialized"] = True
                
                # Check if feature server is accessible
                feature_server = getattr(feature_server_api, "feature_server", None)
                if feature_server:
                    result.details["feature_server_available"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Feature server not accessible")
                    result.solutions.append("Check feature server configuration")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Feature server test failed: {e}")
            result.solutions.append("Check feature server implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_model_registry(self):
        """Test Model Registry initialization."""
        result = TestResult(name="model_registry", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            model_registry = getattr(self.agent, "model_registry", None)
            if model_registry is None:
                result.status = TestStatus.FAIL
                result.issues.append("Model Registry not initialized")
                result.solutions.append("Check model registry initialization")
            else:
                result.details["model_registry_initialized"] = True
                
                # Check if registry has models
                if hasattr(model_registry, "list_models"):
                    models = model_registry.list_models()
                    result.details["registered_models"] = len(models)
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Model registry test failed: {e}")
            result.solutions.append("Check model registry implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_state_machine(self):
        """Test State Machine initialization."""
        result = TestResult(name="state_machine", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            state_machine = getattr(self.agent, "state_machine", None)
            if state_machine is None:
                result.status = TestStatus.FAIL
                result.issues.append("State Machine not initialized")
                result.solutions.append("Check state machine initialization")
            else:
                result.details["state_machine_initialized"] = True
                
                # Check current state
                current_state = getattr(state_machine, "current_state", None)
                if current_state:
                    result.details["current_state"] = str(current_state)
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"State machine test failed: {e}")
            result.solutions.append("Check state machine implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_database_connection(self):
        """Test database connection."""
        result = TestResult(name="database_connection", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            from tests.functionality.utils import ServiceHealthChecker
            from tests.functionality.config import config
            
            if config.database_url:
                db_health = await ServiceHealthChecker.check_database(config.database_url)
                result.details["database_health"] = db_health
                
                if db_health.get("status") != "up":
                    result.status = TestStatus.FAIL
                    result.issues.append(f"Database connection failed: {db_health.get('error')}")
                    result.solutions.append("Check database URL and ensure database is running")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Database URL not configured")
                result.solutions.append("Set DATABASE_URL in environment or config")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Database connection test failed: {e}")
            result.solutions.append("Check database configuration and connectivity")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_redis_connection(self):
        """Test Redis connection."""
        result = TestResult(name="redis_connection", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            from tests.functionality.utils import ServiceHealthChecker
            from tests.functionality.config import config
            
            if config.redis_url:
                redis_health = await ServiceHealthChecker.check_redis(config.redis_url)
                result.details["redis_health"] = redis_health
                
                if redis_health.get("status") != "up":
                    result.status = TestStatus.FAIL
                    result.issues.append(f"Redis connection failed: {redis_health.get('error')}")
                    result.solutions.append("Check Redis URL and ensure Redis is running")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Redis URL not configured")
                result.solutions.append("Set REDIS_URL in environment or config")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Redis connection test failed: {e}")
            result.solutions.append("Check Redis configuration and connectivity")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_delta_client(self):
        """Test Delta Exchange client initialization."""
        result = TestResult(name="delta_client", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            delta_client = getattr(self.agent, "delta_client", None)
            if delta_client is None:
                result.status = TestStatus.FAIL
                result.issues.append("Delta Exchange client not initialized")
                result.solutions.append("Check Delta Exchange client initialization")
            else:
                result.details["delta_client_initialized"] = True
                
                # Check if client has API credentials
                has_api_key = hasattr(delta_client, "api_key") and delta_client.api_key
                result.details["has_api_key"] = has_api_key
                
                if not has_api_key:
                    result.status = TestStatus.WARNING
                    result.issues.append("Delta Exchange API key not configured")
                    result.solutions.append("Set DELTA_EXCHANGE_API_KEY in environment")
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Delta client test failed: {e}")
            result.solutions.append("Check Delta Exchange client implementation")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_vector_memory_store(self):
        """Test Vector Memory Store initialization."""
        result = TestResult(name="vector_memory_store", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            # Check if learning system has memory store
            learning_system = getattr(self.agent, "learning_system", None)
            if learning_system:
                result.details["learning_system_initialized"] = True
                
                # Check for memory store (may be optional)
                memory_store = getattr(learning_system, "memory_store", None)
                if memory_store:
                    result.details["memory_store_available"] = True
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Vector memory store not available")
                    result.solutions.append("Vector memory store may be optional or not configured")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("Learning system not initialized")
                result.solutions.append("Check learning system initialization")
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Vector memory store test failed: {e}")
            result.solutions.append("Vector memory store may be optional")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup after tests."""
        # Agent cleanup is handled by shared resources
        pass

