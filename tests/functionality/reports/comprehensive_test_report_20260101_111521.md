# Comprehensive Functionality Test Report

**Generated**: 2026-01-01 11:15:21 UTC

## Executive Summary

- **Total Tests**: 102
- **Passed**: 63 (61.8%)
- **Failed**: 2
- **Warnings**: 37
- **Degraded**: 0
- **Health Score**: 61.76%
- **Total Duration**: 128.60s
- **Groups Tested**: 4

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

### Infrastructure

#### ⚠️ database operations

- **Status**: WARNING
- **Duration**: 1.02ms
- **Tests**: 3 (Passed: 2, Failed: 0)

**Issues**:
- Database URL not configured

#### ❌ delta exchange connection

- **Status**: FAIL
- **Duration**: 17193.85ms
- **Tests**: 4 (Passed: 3, Failed: 1)

#### ⚠️ agent loading

- **Status**: WARNING
- **Duration**: 23543.49ms
- **Tests**: 11 (Passed: 8, Failed: 0)

**Issues**:
- Backend service may not be available
- Database URL not configured
- Vector memory store not available

### Core-Services

#### ⚠️ feature computation

- **Status**: WARNING
- **Duration**: 2711.18ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- Feature server health check failed: Cannot connect to host 0.0.0.0:8001 ssl:default [The format of the specified network name is invalid]

#### ⚠️ ml model communication

- **Status**: WARNING
- **Duration**: 6.02ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Model inference test requires feature data

#### ⚠️ websocket communication

- **Status**: WARNING
- **Duration**: 6164.78ms
- **Tests**: 6 (Passed: 0, Failed: 0)

**Issues**:
- Backend WebSocket not available
- Agent WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available
- Backend WebSocket not available

### Agent-Logic

#### ✅ agent decision

- **Status**: PASS
- **Duration**: 2.99ms
- **Tests**: 8 (Passed: 8, Failed: 0)

#### ✅ risk management

- **Status**: PASS
- **Duration**: 4.52ms
- **Tests**: 5 (Passed: 5, Failed: 0)

#### ⚠️ signal generation

- **Status**: WARNING
- **Duration**: 6323.99ms
- **Tests**: 6 (Passed: 5, Failed: 0)

**Issues**:
- WebSocket client not connected
- Backend WebSocket connection not available

#### ⚠️ agent functionality

- **Status**: WARNING
- **Duration**: 13744.18ms
- **Tests**: 13 (Passed: 10, Failed: 0)

**Issues**:
- Backend service may not be available
- Backend communication test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Agent reports as unavailable

### Integration

#### ⚠️ agent communication

- **Status**: WARNING
- **Duration**: 21373.47ms
- **Tests**: 11 (Passed: 2, Failed: 0)

**Issues**:
- WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)
- Message send failed: received 1011 (internal error); then sent 1011 (internal error)
- Command round-trip test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Only 0/3 command types tested successfully
- Failed: predict (error: Cannot connect to host localhost:8000 ssl:default ), get_status (error: Cannot connect to host localhost:8000 ssl:default ), health (error: Cannot connect to host localhost:8000 ssl:default )
- Backend WebSocket not available
- WebSocket client not connected
- Only Redis available, WebSocket not connected
- Backend WebSocket not available
- Backend WebSocket not available
- Reconnection method not found

#### ⚠️ data freshness

- **Status**: WARNING
- **Duration**: 8347.64ms
- **Tests**: 6 (Passed: 4, Failed: 0)

**Issues**:
- Health status check failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Backend WebSocket not available

#### ⚠️ portfolio management

- **Status**: WARNING
- **Duration**: 12217.15ms
- **Tests**: 5 (Passed: 2, Failed: 0)

**Issues**:
- Portfolio state test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Position tracking test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Performance metrics test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

#### ⚠️ learning system

- **Status**: WARNING
- **Duration**: 0.00ms
- **Tests**: 5 (Passed: 1, Failed: 0)

**Issues**:
- Performance tracking methods not found
- Adaptation methods not found
- Memory store not available
- Performance aggregation methods not found

#### ❌ frontend functionality

- **Status**: FAIL
- **Duration**: 16970.39ms
- **Tests**: 7 (Passed: 4, Failed: 1)

**Issues**:
- Frontend API integration test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]
- Frontend WebSocket test failed: Failed to connect to backend WebSocket: [WinError 1225] The remote computer refused the network connection
- Frontend real-time price data test failed: Failed to connect to backend WebSocket: [WinError 1225] The remote computer refused the network connection

## Issues Found

### database_connection (database operations)

**Issue**: Database URL not configured

**Solution**: Verify database is running and connection string is correct

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

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### connection_management (websocket communication)

**Issue**: Agent WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)

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

### backend_agent_websocket (agent communication)

**Issue**: WebSocket ping failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Verify WebSocket server is running and port is correct

### backend_agent_websocket (agent communication)

**Issue**: Message send failed: received 1011 (internal error); then sent 1011 (internal error)

**Solution**: Review logs and documentation for troubleshooting steps

### command_response_roundtrip (agent communication)

**Issue**: Command round-trip test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### command_types (agent communication)

**Issue**: Only 0/3 command types tested successfully

**Solution**: Review logs and documentation for troubleshooting steps

### command_types (agent communication)

**Issue**: Failed: predict (error: Cannot connect to host localhost:8000 ssl:default ), get_status (error: Cannot connect to host localhost:8000 ssl:default ), health (error: Cannot connect to host localhost:8000 ssl:default )

**Solution**: Review logs and documentation for troubleshooting steps

### agent_backend_websocket (agent communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### agent_event_publishing (agent communication)

**Issue**: WebSocket client not connected

**Solution**: Verify WebSocket server is running and port is correct

### dual_publishing (agent communication)

**Issue**: Only Redis available, WebSocket not connected

**Solution**: Check Redis is running and accessible

### frontend_backend_websocket (agent communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### message_subscription (agent communication)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### reconnection_logic (agent communication)

**Issue**: Reconnection method not found

**Solution**: Check service is running and URL is correct

### health_status_updates (data freshness)

**Issue**: Health status check failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### websocket_message_freshness (data freshness)

**Issue**: Backend WebSocket not available

**Solution**: Verify WebSocket server is running and port is correct

### portfolio_state (portfolio management)

**Issue**: Portfolio state test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### position_tracking (portfolio management)

**Issue**: Position tracking test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### performance_metrics (portfolio management)

**Issue**: Performance metrics test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

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

### frontend_api_integration (frontend functionality)

**Issue**: Frontend API integration test failed: Cannot connect to host localhost:8000 ssl:default [The remote computer refused the network connection]

**Solution**: Check service is running and URL is correct

### frontend_websocket_connection (frontend functionality)

**Issue**: Frontend WebSocket test failed: Failed to connect to backend WebSocket: [WinError 1225] The remote computer refused the network connection

**Solution**: Check service is running and URL is correct

### frontend_realtime_price_data (frontend functionality)

**Issue**: Frontend real-time price data test failed: Failed to connect to backend WebSocket: [WinError 1225] The remote computer refused the network connection

**Solution**: Check service is running and URL is correct

## Recommendations

- Address 2 failing tests to improve system reliability
- Review 37 warnings to identify potential issues
- System health score is below 80%. Review failing tests and warnings

