# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 10:11:20 UTC

## Executive Summary

- **Total Tests**: 103
- **Passed**: 80 (77.7%)
- **Failed**: 0
- **Warnings**: 23
- **Degraded**: 0
- **Health Score**: 77.67%
- **Total Duration**: 46.22s
- **Groups Tested**: 4

## System Startup Status

**Overall Status**: ❌ Some services not ready

### Service Health

- ❌ **Backend**: Not Ready
- ❌ **Feature Server**: Not Ready
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
- **Duration**: 2701.56ms
- **Tests**: 7 (Passed: 5, Failed: 0)

**Issues**:
- Rate limiting test requires special setup
- Error handling test requires failure simulation

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 16697.74ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Backend service may not be available
- Database URL not configured
- Vector memory store not available

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 4278.43ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Model inference test requires feature data

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 4369.06ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Agent WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 2.01ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ✅ signal generation

- **Status**: PASS
- **Duration**: 827.74ms
- **Tests**: 6 (Passed: 6, Failed: 0)

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 9772.26ms
- **Tests**: 12 (Passed: 10, Failed: 0)

**Issues**:
- Agent shows as down in backend health check
- Agent reports as unavailable

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 3176.80ms
- **Tests**: 11 (Passed: 7, Failed: 0)

**Issues**:
- WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)
- Message send failed: received 1011 (internal error); then sent 1011 (internal error)
- Prediction request returned status 401 (authentication required)
- Only 1/3 command types tested successfully
- Failed: predict (status 401 - authentication required), get_status (status 401 - authentication required)
- Reconnection method not found

#### ✅ data freshness

- **Status**: PASS
- **Duration**: 204.17ms
- **Tests**: 6 (Passed: 6, Failed: 0)

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 2047.92ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Portfolio endpoint returned status 401
- Positions endpoint returned status 401
- Performance endpoint returned status 401

#### ⚠️ learning system

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Performance tracking methods not found
- Adaptation methods not found
- Memory store not available
- Performance aggregation methods not found

#### ✅ frontend functionality

- **Status**: PASS
- **Duration**: 2143.91ms
- **Tests**: 6 (Passed: 6, Failed: 0)

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

### service_health_check (agent loading)

**Issue**: Backend service may not be available

**Solution**: Review logs and documentation for troubleshooting steps

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### connection_management (websocket communication)

**Issue**: Agent WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Verify WebSocket server is running and port is correct

### agent_backend_communication (agent functionality)

**Issue**: Agent shows as down in backend health check

**Solution**: Review logs and documentation for troubleshooting steps

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

**Issue**: Prediction request returned status 401 (authentication required)

**Solution**: Verify API keys and credentials are correct

### command_types (agent communication)

**Issue**: Only 1/3 command types tested successfully

**Solution**: Review logs and documentation for troubleshooting steps

### command_types (agent communication)

**Issue**: Failed: predict (status 401 - authentication required), get_status (status 401 - authentication required)

**Solution**: Verify API keys and credentials are correct

### reconnection_logic (agent communication)

**Issue**: Reconnection method not found

**Solution**: Check service is running and URL is correct

### portfolio_state (portfolio management)

**Issue**: Portfolio endpoint returned status 401

**Solution**: Review logs and documentation for troubleshooting steps

### position_tracking (portfolio management)

**Issue**: Positions endpoint returned status 401

**Solution**: Review logs and documentation for troubleshooting steps

### performance_metrics (portfolio management)

**Issue**: Performance endpoint returned status 401

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
- Review 23 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

