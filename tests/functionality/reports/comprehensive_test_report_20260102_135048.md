# Comprehensive Functionality Test Report

**Generated**: 2026-01-02 13:50:48 UTC

## Executive Summary

- **Total Tests**: 84
- **Passed**: 68 (81.0%)
- **Failed**: 0
- **Warnings**: 16
- **Degraded**: 0
- **Health Score**: 80.95%
- **Total Duration**: 64.66s
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

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 29987.79ms
- **Tests**: 10 (Passed: 8, Failed: 0)

**Issues**:
- Database URL not configured
- Vector memory store not available

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 3919.39ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 8.11ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Model inference test requires feature data

#### ✅ websocket communication

- **Status**: PASS
- **Duration**: 4236.85ms
- **Tests**: 6 (Passed: 6, Failed: 0)

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 2.00ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 3.01ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ✅ signal generation

- **Status**: PASS
- **Duration**: 8512.93ms
- **Tests**: 6 (Passed: 6, Failed: 0)

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 5326.67ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Prediction request returned status 401 (authentication required)
- Only 1/3 command types tested successfully
- Failed: predict (status 401 - authentication required), get_status (status 401 - authentication required)
- Reconnection method not found

#### ✅ data freshness

- **Status**: PASS
- **Duration**: 265.47ms
- **Tests**: 6 (Passed: 6, Failed: 0)

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 4159.51ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Portfolio endpoint returned status 401
- Positions endpoint returned status 401
- Performance endpoint returned status 401

#### ⚠️ learning system

- **Status**: WARNING
- **Duration**: 0.99ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Performance tracking methods not found
- Adaptation methods not found
- Memory store not available
- Performance aggregation methods not found

#### ✅ frontend functionality

- **Status**: PASS
- **Duration**: 8235.59ms
- **Tests**: 7 (Passed: 7, Failed: 0)

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

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

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
- Review 16 warnings to identify potential issues

