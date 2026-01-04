# Comprehensive Functionality Test Report

**Generated**: 2026-01-02 14:11:35 UTC

## Executive Summary

- **Total Tests**: 35
- **Passed**: 27 (77.1%)
- **Failed**: 1
- **Warnings**: 7
- **Degraded**: 0
- **Health Score**: 77.14%
- **Total Duration**: 46.16s
- **Groups Tested**: 2

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

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 20385.12ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 16.93ms
- **Tests**: 6 (Passed: 3, Failed: 0)

**Issues**:
- Model inference test requires feature data
- Expected at least 6 model(s) but found 0

#### ✅ websocket communication

- **Status**: PASS
- **Duration**: 8651.45ms
- **Tests**: 6 (Passed: 6, Failed: 0)

### Infrastructure

#### ⚠️ database operations

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 3 (Passed: 2, Failed: 0)

**Issues**:
- Database URL not configured

#### ❌ delta exchange connection

- **Status**: FAIL
- **Duration**: 10488.18ms
- **Tests**: 4 (Passed: 3, Failed: 1)

**Issues**:
- Setup/run/teardown failed: cannot access local variable 'datetime' where it is not associated with a value

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 6621.57ms
- **Tests**: 10 (Passed: 8, Failed: 0)

**Issues**:
- Database URL not configured
- Vector memory store not available

## Issues Found

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### model_loading_sources (ml model communication)

**Issue**: Expected at least 6 model(s) but found 0

**Solution**: Check model files exist and are valid

### database_connection (database operations)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### setup_error (delta exchange connection)

**Issue**: Setup/run/teardown failed: cannot access local variable 'datetime' where it is not associated with a value

**Solution**: Review logs and documentation for troubleshooting steps

### database_connection (agent loading)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

### vector_memory_store (agent loading)

**Issue**: Vector memory store not available

**Solution**: Review logs and documentation for troubleshooting steps

## Recommendations

- Some services failed to start or are not ready. Check service logs and configuration
- Address 1 failing tests to improve system reliability
- Review 7 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

