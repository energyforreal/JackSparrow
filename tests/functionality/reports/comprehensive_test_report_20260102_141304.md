# Comprehensive Functionality Test Report

**Generated**: 2026-01-02 14:13:04 UTC

## Executive Summary

- **Total Tests**: 18
- **Passed**: 14 (77.8%)
- **Failed**: 0
- **Warnings**: 4
- **Degraded**: 0
- **Health Score**: 77.78%
- **Total Duration**: 22.49s
- **Groups Tested**: 1

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
- **Duration**: 16179.17ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8003 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 6.10ms
- **Tests**: 6 (Passed: 3, Failed: 0)

**Issues**:
- Model inference test requires feature data
- Expected at least 6 model(s) but found 0

#### ✅ websocket communication

- **Status**: PASS
- **Duration**: 6306.87ms
- **Tests**: 6 (Passed: 6, Failed: 0)

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

## Recommendations

- Some services failed to start or are not ready. Check service logs and configuration
- Review 4 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

