# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 07:12:50 UTC

## Executive Summary

- **Total Tests**: 101
- **Passed**: 77 (76.2%)
- **Failed**: 0
- **Warnings**: 24
- **Degraded**: 0
- **Health Score**: 76.24%
- **Total Duration**: 64.31s
- **Groups Tested**: 4

## System Startup Status

**Overall Status**: ❌ Some services not ready

### Service Health


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
- **Duration**: 3952.27ms
- **Tests**: 7 (Passed: 5, Failed: 0)

**Issues**:
- Rate limiting test requires special setup
- Error handling test requires failure simulation

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 13872.11ms
- **Tests**: 10 (Passed: 8, Failed: 0)

**Issues**:
- Database URL not configured
- Vector memory store not available

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 2453.57ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Model inference test requires feature data

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 5195.43ms
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
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ✅ signal generation

- **Status**: PASS
- **Duration**: 1604.20ms
- **Tests**: 6 (Passed: 6, Failed: 0)

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 10711.99ms
- **Tests**: 12 (Passed: 11, Failed: 0)

**Issues**:
- Agent reports as unavailable

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 5174.52ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Prediction request returned status 401 (authentication required)
- Only 1/3 command types tested successfully
- Failed: predict (status 401 - authentication required), get_status (status 401 - authentication required)
- Reconnection method not found

#### ⚠️ data freshness

- **Status**: WARNING
- **Duration**: 2258.24ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Message missing timestamp

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 23.59ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Portfolio endpoint returned status 401
- Positions endpoint returned status 401
- Performance endpoint returned status 401

#### ⚠️ learning system

- **Status**: WARNING
- **Duration**: 0.54ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Performance tracking methods not found
- Adaptation methods not found
- Memory store not available
- Performance aggregation methods not found

#### ⚠️ frontend functionality

- **Status**: WARNING
- **Duration**: 19060.30ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Frontend accessibility test failed: Cannot connect to host localhost:3000 ssl:default [The remote computer refused the network connection]
- Frontend health endpoint test failed: 
- CORS headers test failed: 

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

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

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

**Issue**: Message missing timestamp

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

### frontend_accessible (frontend functionality)

**Issue**: Frontend accessibility test failed: Cannot connect to host localhost:3000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### frontend_health_endpoint (frontend functionality)

**Issue**: Frontend health endpoint test failed: 

**Solution**: Review logs and documentation for troubleshooting steps

### frontend_cors_headers (frontend functionality)

**Issue**: CORS headers test failed: 

**Solution**: Review logs and documentation for troubleshooting steps

## Recommendations

- Some services failed to start or are not ready. Check service logs and configuration
- Review 24 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

