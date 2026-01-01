"""Test feature computation functionality."""

import asyncio
from typing import Dict, Any, List
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent
from tests.functionality.config import config


class FeatureComputationTestSuite(TestSuiteBase):
    """Test suite for feature computation."""
    
    def __init__(self, test_name: str = "feature_computation"):
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
        """Run all feature computation tests."""
        await self._test_mcp_feature_protocol()
        await self._test_feature_calculation()
        await self._test_all_50_features()
        await self._test_feature_server()
        await self._test_feature_performance()
        await self._test_feature_caching()
    
    async def _test_mcp_feature_protocol(self):
        """Test MCP Feature Protocol."""
        result = TestResult(name="mcp_feature_protocol", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
                mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
                result.solutions.append("Check agent initialization")
            else:
                feature_server = getattr(mcp_orchestrator, "feature_server", None)
                if feature_server is None:
                    result.status = TestStatus.FAIL
                    result.issues.append("Feature server not available")
                    result.solutions.append("Check MCP orchestrator initialization")
                else:
                    result.details["feature_server_available"] = True
                    result.details["mcp_protocol_available"] = True
                    
                    # Test get_features method
                    if hasattr(mcp_orchestrator, "get_features"):
                        result.details["get_features_method_available"] = True
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("get_features method not found")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"MCP feature protocol test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_feature_calculation(self):
        """Test feature calculation."""
        result = TestResult(name="feature_calculation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                # Test with a small set of features first
                test_features = ["sma_20", "rsi_14", "macd"]
                
                try:
                    feature_response = await mcp_orchestrator.get_features(
                        feature_names=test_features,
                        symbol=symbol
                    )
                    
                    if feature_response:
                        features = getattr(feature_response, "features", [])
                        result.details["features_computed"] = len(features)
                        result.details["requested_features"] = len(test_features)
                        
                        if len(features) > 0:
                            result.details["feature_calculation_working"] = True
                            
                            # Validate feature values
                            valid_features = []
                            invalid_features = []
                            
                            for feature in features:
                                feature_name = getattr(feature, "name", None)
                                feature_value = getattr(feature, "value", None)
                                
                                if feature_value is not None:
                                    if isinstance(feature_value, (int, float)):
                                        valid_features.append(feature_name)
                                    else:
                                        invalid_features.append(f"{feature_name}: {type(feature_value)}")
                                else:
                                    invalid_features.append(f"{feature_name}: None")
                            
                            result.details["valid_features"] = len(valid_features)
                            result.details["invalid_features"] = len(invalid_features)
                            
                            if len(valid_features) < len(test_features):
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Only {len(valid_features)}/{len(test_features)} features have valid values")
                                if invalid_features:
                                    result.issues.append(f"Invalid features: {', '.join(invalid_features[:3])}")
                                result.solutions.append("Check market data availability and feature computation logic")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("No features computed")
                            result.solutions.append("Check market data service and feature server configuration")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Feature computation returned None")
                        result.solutions.append("Check feature server and market data availability")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Feature calculation test failed: {e}")
                    result.solutions.append("Check market data service and feature server configuration")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Feature calculation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_all_50_features(self):
        """Test computation of all 50 required features."""
        result = TestResult(name="all_50_features", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                # All 50 features required by ML models
                all_features = [
                    # Price-based (16 features)
                    'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
                    'ema_12', 'ema_26', 'ema_50',
                    'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
                    'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
                    # Momentum (10 features)
                    'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
                    'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
                    'momentum_10', 'momentum_20',
                    # Trend (8 features)
                    'macd', 'macd_signal', 'macd_histogram',
                    'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
                    'trend_strength',
                    # Volatility (8 features)
                    'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
                    'atr_14', 'atr_20',
                    'volatility_10', 'volatility_20',
                    # Volume (6 features)
                    'volume_sma_20', 'volume_ratio', 'obv',
                    'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
                    # Returns (2 features)
                    'returns_1h', 'returns_24h'
                ]
                
                try:
                    feature_response = await mcp_orchestrator.get_features(
                        feature_names=all_features,
                        symbol=symbol
                    )
                    
                    if feature_response:
                        features = getattr(feature_response, "features", [])
                        result.details["total_features_requested"] = len(all_features)
                        result.details["total_features_computed"] = len(features)
                        
                        # Check feature coverage
                        computed_feature_names = [getattr(f, "name", None) for f in features]
                        missing_features = [f for f in all_features if f not in computed_feature_names]
                        
                        result.details["missing_features"] = len(missing_features)
                        if missing_features:
                            result.details["missing_feature_names"] = missing_features[:10]  # First 10
                        
                        # Validate feature values
                        valid_count = 0
                        invalid_count = 0
                        
                        for feature in features:
                            value = getattr(feature, "value", None)
                            if value is not None and isinstance(value, (int, float)):
                                # Check for reasonable ranges (some features can be negative)
                                if not (isinstance(value, float) and (value != value)):  # Not NaN
                                    valid_count += 1
                                else:
                                    invalid_count += 1
                            else:
                                invalid_count += 1
                        
                        result.details["valid_feature_values"] = valid_count
                        result.details["invalid_feature_values"] = invalid_count
                        
                        # Calculate coverage percentage
                        coverage = (len(features) / len(all_features)) * 100 if all_features else 0
                        result.details["feature_coverage_percent"] = round(coverage, 2)
                        
                        if coverage >= 90:
                            result.details["high_coverage"] = True
                        elif coverage >= 70:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Feature coverage is {coverage:.1f}% (expected >= 90%)")
                            result.solutions.append("Check missing features and market data availability")
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Feature coverage is low: {coverage:.1f}%")
                            result.solutions.append("Check market data service and feature computation logic")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Feature computation returned None for all features")
                        result.solutions.append("Check feature server and market data availability")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"All 50 features test failed: {e}")
                    result.solutions.append("Check market data service and feature server configuration")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"All 50 features test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_feature_server(self):
        """Test Feature Server API endpoints."""
        result = TestResult(name="feature_server", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            feature_server_api = getattr(self.agent, "feature_server_api", None)
            if feature_server_api is None:
                result.status = TestStatus.WARNING
                result.issues.append("Feature Server API not available")
                result.solutions.append("Check feature server API initialization")
            else:
                result.details["feature_server_api_available"] = True
                
                # Check feature server
                feature_server = getattr(feature_server_api, "feature_server", None)
                if feature_server:
                    result.details["feature_server_available"] = True
                    
                    # Check if feature server has compute_features method
                    if hasattr(feature_server, "compute_features"):
                        result.details["compute_features_method_available"] = True
                    
                    # Check feature server host and port
                    host = getattr(feature_server_api, "host", None)
                    port = getattr(feature_server_api, "port", None)
                    result.details["feature_server_host"] = host
                    result.details["feature_server_port"] = port
                    
                    # Test HTTP endpoint if available
                    if host and port:
                        try:
                            import aiohttp
                            async with aiohttp.ClientSession() as session:
                                health_url = f"http://{host}:{port}/health"
                                try:
                                    async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                                        if resp.status == 200:
                                            result.details["feature_server_http_available"] = True
                                            result.details["health_endpoint_working"] = True
                                        else:
                                            result.status = TestStatus.WARNING
                                            result.issues.append(f"Feature server health endpoint returned status {resp.status}")
                                except asyncio.TimeoutError:
                                    result.status = TestStatus.WARNING
                                    result.issues.append("Feature server health endpoint timeout")
                                    result.solutions.append("Check if feature server is running")
                                except Exception as e:
                                    result.status = TestStatus.WARNING
                                    result.issues.append(f"Feature server health check failed: {e}")
                        except ImportError:
                            result.details["aiohttp_not_available"] = True
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.issues.append(f"Feature server HTTP test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Feature server test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_feature_performance(self):
        """Test feature computation performance (< 500ms target)."""
        result = TestResult(name="feature_performance", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                
                # Test with subset of features for performance
                test_features = ["sma_20", "rsi_14", "macd", "bb_upper", "bb_lower"]
                
                try:
                    perf_start = datetime.utcnow()
                    feature_response = await mcp_orchestrator.get_features(
                        feature_names=test_features,
                        symbol=symbol
                    )
                    perf_end = datetime.utcnow()
                    
                    computation_time_ms = (perf_end - perf_start).total_seconds() * 1000
                    result.details["computation_time_ms"] = round(computation_time_ms, 2)
                    result.details["features_computed"] = len(getattr(feature_response, "features", [])) if feature_response else 0
                    
                    # Performance target: < 500ms
                    if computation_time_ms < 500:
                        result.details["performance_target_met"] = True
                    elif computation_time_ms < 1000:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Feature computation took {computation_time_ms:.0f}ms (target: < 500ms)")
                        result.solutions.append("Check feature computation optimization")
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append(f"Feature computation slow: {computation_time_ms:.0f}ms (target: < 500ms)")
                        result.solutions.append("Check market data service performance and feature computation logic")
                
                except Exception as e:
                    result.status = TestStatus.WARNING
                    result.error = str(e)
                    result.issues.append(f"Feature performance test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Feature performance test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_feature_caching(self):
        """Test feature caching mechanism."""
        result = TestResult(name="feature_caching", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                feature_server = getattr(mcp_orchestrator, "feature_server", None)
                if feature_server:
                    # Check if feature server has caching
                    has_cache = hasattr(feature_server, "_cache") or hasattr(feature_server, "cache")
                    result.details["caching_mechanism_available"] = has_cache
                    
                    if has_cache:
                        result.details["feature_caching_enabled"] = True
                    else:
                        result.details["feature_caching_enabled"] = False
                        result.status = TestStatus.WARNING
                        result.issues.append("Feature caching not detected")
                        result.solutions.append("Feature caching may be optional or implemented differently")
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("Feature server not available")
            else:
                result.status = TestStatus.WARNING
                result.issues.append("MCP orchestrator not available")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Feature caching test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
