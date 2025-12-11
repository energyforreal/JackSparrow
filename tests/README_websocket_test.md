# WebSocket Realtime Data Test

This test script verifies that realtime data is being sent to the frontend via WebSocket and that messages are fresh (recent timestamps).

## Purpose

The test validates:
1. ✅ All expected WebSocket message types are being received
2. ✅ Messages have valid structure and required fields
3. ✅ Messages are fresh (timestamps are recent)
4. ✅ New message types from our implementation are working:
   - `reasoning_chain_update`
   - `model_prediction_update`
   - `market_tick` (with improved frequency)

## Prerequisites

1. **Backend must be running** on `http://localhost:8000`
2. **Agent must be running** and actively processing (to generate events)
3. **Redis must be running** (for event bus)

### Install Dependencies

```bash
npm install ws
```

## Usage

```bash
# Default: test for 60 seconds, connect to ws://localhost:8000/ws
node tests/websocket_realtime_test.js

# Custom WebSocket URL
WS_URL=ws://localhost:8000/ws node tests/websocket_realtime_test.js

# Custom test duration (in milliseconds)
TEST_DURATION_MS=30000 node tests/websocket_realtime_test.js
```

## Test Output

The test will:
1. Connect to the WebSocket endpoint
2. Listen for messages for 60 seconds (default)
3. Track all received message types
4. Validate message structure
5. Calculate freshness scores based on timestamps
6. Print a comprehensive report

### Sample Output

```
🚀 Starting WebSocket Realtime Data Test
📡 Connecting to: ws://localhost:8000/ws
⏱️  Test duration: 60 seconds
🎯 Freshness threshold: 5000ms

✅ WebSocket connected successfully

📥 Listening for messages...

✅ [market_tick] Message #1 received (234ms old)
✅ [agent_state] Message #1 received (156ms old)
✅ [market_tick] Message #2 received (189ms old)
✅ [signal_update] Message #1 received (312ms old)
✅ [reasoning_chain_update] Message #1 received (445ms old)
✅ [model_prediction_update] Message #1 received (521ms old)
...

================================================================================
📊 TEST RESULTS SUMMARY
================================================================================

✅ agent_state:
   Messages received: 5
   Last received: 2025-01-27T12:30:45.123Z
   Average latency: 234ms
   Freshness score: 🟢 95.2/100

✅ market_tick:
   Messages received: 12
   Last received: 2025-01-27T12:30:45.456Z
   Average latency: 189ms
   Freshness score: 🟢 98.5/100

✅ signal_update:
   Messages received: 2
   Last received: 2025-01-27T12:30:44.789Z
   Average latency: 312ms
   Freshness score: 🟢 92.1/100

✅ reasoning_chain_update:
   Messages received: 2
   Last received: 2025-01-27T12:30:44.234Z
   Average latency: 445ms
   Freshness score: 🟢 88.7/100

✅ model_prediction_update:
   Messages received: 2
   Last received: 2025-01-27T12:30:44.567Z
   Average latency: 521ms
   Freshness score: 🟢 85.3/100

--------------------------------------------------------------------------------
📈 OVERALL STATISTICS
--------------------------------------------------------------------------------
Total message types: 9
Message types received: 7/9
Total messages received: 28
Total errors: 0
Test duration: 60s
Messages per second: 0.47
Average freshness score: 92.0/100

================================================================================
🎯 VERIFICATION CHECKLIST
================================================================================
✅ PASS market_tick: 12 messages, freshness 98.5%
✅ PASS agent_state: 5 messages, freshness 95.2%
✅ PASS signal_update: 2 messages, freshness 92.1%

New message types (from implementation):
✅ reasoning_chain_update: 2 messages received
✅ model_prediction_update: 2 messages received

================================================================================
✅ TEST PASSED: Realtime data flow is working correctly!
================================================================================
```

## Interpreting Results

### Freshness Score

- 🟢 **70-100**: Excellent - Messages are very fresh
- 🟡 **40-69**: Good - Messages are reasonably fresh
- 🔴 **0-39**: Poor - Messages are stale or missing timestamps

### Critical Message Types

The test checks these critical types:
- `market_tick` - Should be received frequently (every few seconds)
- `agent_state` - Should be received when agent state changes
- `signal_update` - Should be received when trading decisions are made

### New Implementation Types

These are the new message types from our implementation:
- `reasoning_chain_update` - May not be received if agent is not actively reasoning
- `model_prediction_update` - May not be received if agent is not making predictions

## Troubleshooting

### No Messages Received

1. **Check backend is running**: `curl http://localhost:8000/api/v1/health`
2. **Check WebSocket endpoint**: Try connecting with a WebSocket client
3. **Check agent is running**: Agent must be active to generate events
4. **Check Redis**: Events flow through Redis Streams

### Messages Not Fresh

1. **Check system time**: Ensure server and client clocks are synchronized
2. **Check network latency**: High latency can affect freshness scores
3. **Check agent activity**: Agent must be actively processing to generate fresh events

### Missing Message Types

Some message types may not be received if:
- Agent is not actively trading (`trade_executed`)
- Agent is not making predictions (`signal_update`, `reasoning_chain_update`)
- No positions are open (`portfolio_update`)

This is normal behavior - the test will indicate which types are expected but not received.

## Integration with CI/CD

You can integrate this test into your CI/CD pipeline:

```bash
# Run test and check exit code
node tests/websocket_realtime_test.js
if [ $? -eq 0 ]; then
  echo "✅ WebSocket test passed"
else
  echo "❌ WebSocket test failed"
  exit 1
fi
```

## Customization

You can modify the test by editing these constants:

```javascript
const WS_URL = process.env.WS_URL || 'ws://localhost:8000/ws';
const TEST_DURATION_MS = 60000; // Test duration in milliseconds
const FRESHNESS_THRESHOLD_MS = 5000; // Consider messages fresh if within 5 seconds
```

## Related Documentation

- [Backend WebSocket Documentation](../docs/06-backend.md#websocket-protocol)
- [Frontend WebSocket Documentation](../docs/07-frontend.md#websocket-integration)
- [Architecture Documentation](../docs/01-architecture.md#communication-protocols)
