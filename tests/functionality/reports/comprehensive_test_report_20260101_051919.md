# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 05:19:19 UTC

## Executive Summary

- **Total Tests**: 96
- **Passed**: 58 (60.4%)
- **Failed**: 2
- **Warnings**: 36
- **Degraded**: 0
- **Health Score**: 60.42%
- **Total Duration**: 60.88s
- **Groups Tested**: 4

## System Startup Status

**Overall Status**: ❌ Some services not ready

### Service Health

- ✅ **Backend**: Ready
- ✅ **Feature Server**: Ready
- ✅ **Frontend**: Ready
- ✅ **Database**: Ready
- ✅ **Redis**: Ready
- ❌ **WebSocket**: Not Ready

## Test Results by Category

### Infrastructure

#### ⚠️ database operations

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 2, Failed: 0)

**Issues**:
- Database URL not configured

#### ⚠️ delta exchange connection

- **Status**: WARNING
- **Duration**: 4668.02ms
- **Tests**: 7 (Passed: 4, Failed: 0)

**Issues**:
- Rate limiting test requires special setup
- Error handling test requires failure simulation

#### ❌ agent loading

- **Status**: FAIL
- **Duration**: 26804.87ms
- **Tests**: 10 (Passed: 5, Failed: 1)

**Issues**:
- Agent initialization failed: Failed to initialize agent: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8001): [winerror 10048] only one usage of each socket address (protocol/network address/port) is normally permitted
- No models discovered
- Database URL not configured
- Redis URL not configured
- Vector memory store not available

### Core-Services

#### ❌ feature computation

- **Status**: FAIL
- **Duration**: 298.40ms
- **Tests**: 6 (Passed: 3, Failed: 1)

**Issues**:
- MCP feature protocol test failed: cannot access local variable 'mcp_orchestrator' where it is not associated with a value
- Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]
- Feature caching not detected

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 3.01ms
- **Tests**: 6 (Passed: 3, Failed: 0)

**Issues**:
- Model inference test requires feature data
- Expected at least 6 model(s) but found 0

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 5219.77ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Unexpected message type: subscribed

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ⚠️ risk management

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Risk assessment call failed: RiskManager.assess_risk() missing 3 required positional arguments: 'portfolio_value', 'available_balance', and 'current_positions'
- calculate_position_size method not found
- check_risk_limits method not found
- Portfolio risk calculation methods not found

#### ⚠️ signal generation

- **Status**: WARNING
- **Duration**: 8033.53ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- WebSocket client not available

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 10422.91ms
- **Tests**: 12 (Passed: 10, Failed: 0)

**Issues**:
- No models registered
- Agent reports as unavailable

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 3179.85ms
- **Tests**: 11 (Passed: 4, Failed: 0)

**Issues**:
- WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)
- Message send failed: received 1011 (internal error); then sent 1011 (internal error)
- Prediction request returned status 401
- Only 1/3 command types tested successfully
- Failed: predict (status 401), get_status (status 401)
- Agent WebSocket client not initialized
- WebSocket client not initialized
- Only Redis available, WebSocket not connected
- WebSocket client not available

#### ⚠️ data freshness

- **Status**: WARNING
- **Duration**: 216.44ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Message missing timestamp

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 2037.62ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Portfolio endpoint returned status 404
- Positions endpoint returned status 404
- Performance endpoint returned status 404

#### ⚠️ learning system

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Performance tracking methods not found
- Adaptation methods not found
- Memory store not available
- Performance aggregation methods not found

## Issues Found

### database_connection (database operations)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### rate_limiting (delta exchange connection)

**Issue**: Rate limiting test requires special setup

**Solution**: Review logs and documentation for troubleshooting steps

### error_handling (delta exchange connection)

**Issue**: Error handling test requires failure simulation

**Solution**: Review logs and documentation for troubleshooting steps

### agent_initialization (agent loading)

**Issue**: Agent initialization failed: Failed to initialize agent: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8001): [winerror 10048] only one usage of each socket address (protocol/network address/port) is normally permitted

**Solution**: Review logs and documentation for troubleshooting steps

### model_discovery (agent loading)

**Issue**: No models discovered

**Solution**: Check model files exist and are valid

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### redis_connection (agent loading)

**Issue**: Redis URL not configured

**Solution**: Check Redis is running and accessible

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

### mcp_feature_protocol (feature computation)

**Issue**: MCP feature protocol test failed: cannot access local variable 'mcp_orchestrator' where it is not associated with a value

**Solution**: Review logs and documentation for troubleshooting steps

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### feature_caching (feature computation)

**Issue**: Feature caching not detected

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### model_loading_sources (ml model communication)

**Issue**: Expected at least 6 model(s) but found 0

**Solution**: Check model files exist and are valid

### message_format (websocket communication)

**Issue**: Unexpected message type: subscribed

**Solution**: Review logs and documentation for troubleshooting steps

### risk_assessment (risk management)

**Issue**: Risk assessment call failed: RiskManager.assess_risk() missing 3 required positional arguments: 'portfolio_value', 'available_balance', and 'current_positions'

**Solution**: Review logs and documentation for troubleshooting steps

### position_size_calculation (risk management)

**Issue**: calculate_position_size method not found

**Solution**: Review logs and documentation for troubleshooting steps

### risk_limit_enforcement (risk management)

**Issue**: check_risk_limits method not found

**Solution**: Review logs and documentation for troubleshooting steps

### portfolio_risk_metrics (risk management)

**Issue**: Portfolio risk calculation methods not found

**Solution**: Review logs and documentation for troubleshooting steps

### signal_broadcasting (signal generation)

**Issue**: WebSocket client not available

**Solution**: Verify WebSocket server is running and port is correct

### agent_model_integration (agent functionality)

**Issue**: No models registered

**Solution**: Check model files exist and are valid

### agent_health_status (agent functionality)

**Issue**: Agent reports as unavailable

**Solution**: Review logs and documentation for troubleshooting steps

### backend_agent_websocket (agent communication)

**Issue**: WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Verify WebSocket server is running and port is correct

### backend_agent_websocket (agent communication)

**Issue**: Message send failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Review logs and documentation for troubleshooting steps

### command_response_roundtrip (agent communication)

**Issue**: Prediction request returned status 401

**Solution**: Review logs and documentation for troubleshooting steps

### command_types (agent communication)

**Issue**: Only 1/3 command types tested successfully

**Solution**: Review logs and documentation for troubleshooting steps

### command_types (agent communication)

**Issue**: Failed: predict (status 401), get_status (status 401)

**Solution**: Review logs and documentation for troubleshooting steps

### agent_backend_websocket (agent communication)

**Issue**: Agent WebSocket client not initialized

**Solution**: Verify WebSocket server is running and port is correct

### agent_event_publishing (agent communication)

**Issue**: WebSocket client not initialized

**Solution**: Verify WebSocket server is running and port is correct

### dual_publishing (agent communication)

**Issue**: Only Redis available, WebSocket not connected

**Solution**: Check Redis is running and accessible

### reconnection_logic (agent communication)

**Issue**: WebSocket client not available

**Solution**: Verify WebSocket server is running and port is correct

### websocket_message_freshness (data freshness)

**Issue**: Message missing timestamp

**Solution**: Review logs and documentation for troubleshooting steps

### portfolio_state (portfolio management)

**Issue**: Portfolio endpoint returned status 404

**Solution**: Review logs and documentation for troubleshooting steps

### position_tracking (portfolio management)

**Issue**: Positions endpoint returned status 404

**Solution**: Review logs and documentation for troubleshooting steps

### performance_metrics (portfolio management)

**Issue**: Performance endpoint returned status 404

**Solution**: Review logs and documentation for troubleshooting steps

### performance_tracking (learning system)

**Issue**: Performance tracking methods not found

**Solution**: Review logs and documentation for troubleshooting steps

### adaptation (learning system)

**Issue**: Adaptation methods not found

**Solution**: Review logs and documentation for troubleshooting steps

### memory_storage (learning system)

**Issue**: Memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

### model_performance_aggregation (learning system)

**Issue**: Performance aggregation methods not found

**Solution**: Review logs and documentation for troubleshooting steps

## Recommendations

- Some services failed to start or are not ready. Check service logs and configuration
- Address 2 failing tests to improve system reliability
- Review 36 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

