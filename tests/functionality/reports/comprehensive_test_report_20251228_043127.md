# Comprehensive Functionality Test Report

**Generated**: 2025-12-28 04:31:27 UTC

## Executive Summary

- **Total Tests**: 66
- **Passed**: 46 (69.7%)
- **Failed**: 2
- **Warnings**: 18
- **Degraded**: 0
- **Health Score**: 69.7%
- **Total Duration**: 29.43s
- **Groups Tested**: 4

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
- **Duration**: 7735.61ms
- **Tests**: 7 (Passed: 4, Failed: 0)

**Issues**:
- Rate limiting test requires special setup
- Error handling test requires failure simulation

#### ❌ agent loading

- **Status**: FAIL
- **Duration**: 11196.63ms
- **Tests**: 10 (Passed: 5, Failed: 1)

**Issues**:
- Agent initialization failed: Failed to initialize agent: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8001): [winerror 10048] only one usage of each socket address (protocol/network address/port) is normally permitted
- No models discovered
- Database URL not configured
- Redis URL not configured
- Vector memory store not available

### Core-Services

#### ✅ feature computation

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 7.14ms
- **Tests**: 6 (Passed: 3, Failed: 0)

**Issues**:
- Model inference test requires feature data
- Expected at least 6 model(s) but found 0

#### ✅ websocket communication

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

#### ✅ signal generation

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

### Integration

#### ❌ agent communication

- **Status**: FAIL
- **Duration**: 10388.50ms
- **Tests**: 11 (Passed: 3, Failed: 1)

**Issues**:
- WebSocket connection failed: received 1011 (internal error); then sent 1011 (internal error)
- Prediction request returned status 401
- Only 0/3 command types tested
- Timeout handling test requires special setup
- Event publishing test requires running agent
- Dual publishing test requires running agent
- Reconnection test requires connection interruption simulation

#### ✅ data freshness

- **Status**: PASS
- **Duration**: 100.09ms
- **Tests**: 3 (Passed: 3, Failed: 0)

#### ✅ portfolio management

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

#### ✅ learning system

- **Status**: PASS
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 3, Failed: 0)

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

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### model_loading_sources (ml model communication)

**Issue**: Expected at least 6 model(s) but found 0

**Solution**: Check model files exist and are valid

### backend_agent_websocket (agent communication)

**Issue**: WebSocket connection failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Check service is running and URL is correct

### command_response_roundtrip (agent communication)

**Issue**: Prediction request returned status 401

**Solution**: Review logs and documentation for troubleshooting steps

### command_types (agent communication)

**Issue**: Only 0/3 command types tested

**Solution**: Review logs and documentation for troubleshooting steps

### timeout_handling (agent communication)

**Issue**: Timeout handling test requires special setup

**Solution**: Increase timeout or check network connectivity

### agent_event_publishing (agent communication)

**Issue**: Event publishing test requires running agent

**Solution**: Review logs and documentation for troubleshooting steps

### dual_publishing (agent communication)

**Issue**: Dual publishing test requires running agent

**Solution**: Review logs and documentation for troubleshooting steps

### reconnection_logic (agent communication)

**Issue**: Reconnection test requires connection interruption simulation

**Solution**: Check service is running and URL is correct

## Recommendations

- Address 2 failing tests to improve system reliability
- Review 18 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

