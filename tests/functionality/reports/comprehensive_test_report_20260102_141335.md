# Comprehensive Functionality Test Report

**Generated**: 2026-01-02 14:13:35 UTC

## Executive Summary

- **Total Tests**: 32
- **Passed**: 28 (87.5%)
- **Failed**: 0
- **Warnings**: 4
- **Degraded**: 0
- **Health Score**: 87.5%
- **Total Duration**: 41.94s
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

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 10999.10ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 2.44ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ⚠️ signal generation

- **Status**: WARNING
- **Duration**: 13128.99ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- WebSocket client not connected
- Backend WebSocket connection not available

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 17808.45ms
- **Tests**: 13 (Passed: 10, Failed: 0)

**Issues**:
- Backend service may not be available
- Backend communication test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Agent reports as unavailable

## Issues Found

### signal_broadcasting (signal generation)

**Issue**: WebSocket client not connected

**Solution**: Verify WebSocket server is running and port is correct

### signal_broadcasting (signal generation)

**Issue**: Backend WebSocket connection not available

**Solution**: Check service is running and URL is correct

### service_health_check (agent functionality)

**Issue**: Backend service may not be available

**Solution**: Review logs and documentation for troubleshooting steps

### agent_backend_communication (agent functionality)

**Issue**: Backend communication test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### agent_health_status (agent functionality)

**Issue**: Agent reports as unavailable

**Solution**: Review logs and documentation for troubleshooting steps

## Recommendations

- Review 4 warnings to identify potential issues

