# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 11:44:12 UTC

## Executive Summary

- **Total Tests**: 100
- **Passed**: 79 (79.0%)
- **Failed**: 1
- **Warnings**: 20
- **Degraded**: 0
- **Health Score**: 79.0%
- **Total Duration**: 66.66s
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

#### ❌ delta exchange connection

- **Status**: FAIL
- **Duration**: 12230.43ms
- **Tests**: 4 (Passed: 3, Failed: 1)

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 16157.88ms
- **Tests**: 10 (Passed: 8, Failed: 0)

**Issues**:
- Database URL not configured
- Vector memory store not available

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 2710.65ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8004 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 6.07ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Model inference test requires feature data

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 5229.72ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Unexpected message type: subscribed

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 2.02ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 2.02ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ✅ signal generation

- **Status**: PASS
- **Duration**: 4332.23ms
- **Tests**: 6 (Passed: 6, Failed: 0)

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 8730.49ms
- **Tests**: 12 (Passed: 11, Failed: 0)

**Issues**:
- Agent reports as unavailable

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 3161.13ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Prediction request returned status 401 (authentication required)
- Only 1/3 command types tested successfully
- Failed: predict (status 401 - authentication required), get_status (status 401 - authentication required)
- Reconnection method not found

#### ⚠️ data freshness

- **Status**: WARNING
- **Duration**: 212.74ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Message reception test failed: cannot call recv while another coroutine is already running recv or recv_streaming

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 2029.30ms
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

#### ⚠️ frontend functionality

- **Status**: WARNING
- **Duration**: 11854.79ms
- **Tests**: 7 (Passed: 6, Failed: 0)

**Issues**:
- Failed to subscribe to market_tick channel
- No market tick data received within timeout period

## Issues Found

### database_connection (database operations)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8004 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### message_format (websocket communication)

**Issue**: Unexpected message type: subscribed

**Solution**: Review logs and documentation for troubleshooting steps

### agent_health_status (agent functionality)

**Issue**: Agent reports as unavailable

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

### websocket_message_freshness (data freshness)

**Issue**: Message reception test failed: cannot call recv while another coroutine is already running recv or recv_streaming

**Solution**: Review logs and documentation for troubleshooting steps

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

### frontend_realtime_price_data (frontend functionality)

**Issue**: Failed to subscribe to market_tick channel

**Solution**: Review logs and documentation for troubleshooting steps

### frontend_realtime_price_data (frontend functionality)

**Issue**: No market tick data received within timeout period

**Solution**: Increase timeout or check network connectivity

## Recommendations

- Some services failed to start or are not ready. Check service logs and configuration
- Address 1 failing tests to improve system reliability
- Review 20 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

