# Comprehensive Functionality Test Report

**Generated**: 2026-01-02 14:04:07 UTC

## Executive Summary

- **Total Tests**: 18
- **Passed**: 8 (44.4%)
- **Failed**: 0
- **Warnings**: 10
- **Degraded**: 0
- **Health Score**: 44.44%
- **Total Duration**: 19.76s
- **Groups Tested**: 1

## System Startup Status

**Overall Status**: ✅ All services ready

### Service Health

- ✅ **Backend**: Ready
- ✅ **Feature Server**: Ready
- ✅ **Frontend**: Ready
- ✅ **Database**: Ready
- ✅ **Redis**: Ready
- ✅ **WebSocket**: Ready

## Test Results by Category

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 13074.62ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 6 (Passed: 3, Failed: 0)

**Issues**:
- Model inference test requires feature data
- Expected at least 6 model(s) but found 0

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 6684.82ms
- **Tests**: 6 (Passed: 0, Failed: 0)

**Issues**:
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available

## Issues Found

### feature_server (feature computation)

**Issue**: Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

**Solution**: Review logs and documentation for troubleshooting steps

### model_inference (ml model communication)

**Issue**: Model inference test requires feature data

**Solution**: Check model files exist and are valid

### model_loading_sources (ml model communication)

**Issue**: Expected at least 6 model(s) but found 0

**Solution**: Check model files exist and are valid

### connection_management (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### message_types (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### message_format (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### message_subscription (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### broadcast_to_multiple_clients (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### connection_cleanup (websocket communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

## Recommendations

- Review 10 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

