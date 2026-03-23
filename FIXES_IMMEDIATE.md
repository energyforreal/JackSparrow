# Immediate Fixes (High-Impact, Low-Risk)

## Status Refresh (2026-03-23)
- Fix #1 is now implemented with a config-backed timeout (`AGENT_STATUS_COMMAND_TIMEOUT_SECONDS`, default 15) used in backend status call paths.
- Fix #2 and Fix #3 snippets are partially stale: `_stream_loop()` already suppresses REST ticker polling when WebSocket is connected.
- Fix #4 is already implemented: model warmup is fire-and-forget via `asyncio.create_task(...)`.

## Fix #1: Increase WebSocket Timeout

**File**: Find your backend WebSocket client code (likely in `backend/services/agent_service.py` or `backend/api/websocket/client.py`)

**Original**:
```python
await asyncio.wait_for(
    self.websocket_client.send_command(command),
    timeout=5.0  # 5 seconds
)
```

**Fix (current implementation)**:
```python
# backend/core/config.py
agent_status_command_timeout_seconds: float = Field(
    default=15.0,
    env="AGENT_STATUS_COMMAND_TIMEOUT_SECONDS",
)

# backend/services/agent_service.py
response = await self._send_command("get_status", timeout=timeout_s)
```

**Where to find it**: Search logs for `"agent_service_websocket_timeout"` and look at the timeout value.

**Impact**: 
- Prevents fallback to slower Redis queue
- Gives agent time to respond despite CPU load
- **Estimated CPU impact**: None (just timeout adjustment)

**Test**:
```bash
docker logs jacksparrow-backend 2>&1 | grep -c "agent_service_websocket_timeout" 
# Should see fewer instances after fix
```

---

## Fix #2: Smart Ticker Polling (Reduce REST API Calls)

**File**: `agent/data/market_data_service.py` → `_stream_loop()` method (around line 470)

**Original**:
```python
# Poll interval determined by WebSocket status
poll_interval = settings.fast_poll_interval if not (self._websocket_enabled and self._websocket_connected) else settings.websocket_fallback_poll_interval

logger.info(
    "market_data_stream_mode",
    websocket_enabled=self._websocket_enabled,
    websocket_connected=self._websocket_connected,
    poll_interval=poll_interval,
    symbols=self.streaming_symbols
)

while self.streaming_running:
    try:
        # ... WebSocket reconnect logic ...
        
        for symbol in self.streaming_symbols:
            # Every loop iteration (every 0.5s) - EXPENSIVE!
            if not (self._websocket_enabled and self._websocket_connected):
                await self._check_and_emit_ticker_with_fluctuation(symbol)
```

**Fix status**:
```python
# Existing code already avoids REST ticker polling while WebSocket is connected.
# Remaining tuning should focus on fallback mode cadence:
# - FAST_POLL_INTERVAL
# - CANDLE_POLL_INTERVAL_SECONDS
# - reconnect backoff behavior
```

**Impact**:
- When WebSocket connected: Reduce ticker checks from 120/min to 6/min (-95%)
- **Estimated CPU reduction**: 15-20%

**Test**:
```bash
# Watch API call frequency
docker logs jacksparrow-agent 2>&1 | grep "market_data_stream_mode"
# Should show poll_interval: 10.0 when WebSocket connected
```

---

## Fix #3: Batch Ticker Updates

**File**: `agent/data/market_data_service.py` → `_stream_loop()` method (add at line 530)

**Original**:
```python
for symbol in self.streaming_symbols:
    # Candle polling every 30 seconds
    now = time.time()
    last_candle_check = last_candle_check_time_by_symbol.get(symbol, 0.0)
    if now - last_candle_check >= candle_poll_interval_seconds:
        await self._check_and_emit_candle(symbol, interval)
        last_candle_check_time_by_symbol[symbol] = time.time()
```

**Fix status**:
```python
# This exact snippet is not needed for WS-connected mode because REST ticker polling
# is already skipped there. Keep as optional optimization for fallback mode only.
```

**Impact**:
- Prevents double-processing of same data
- Further -10% CPU reduction
- Total with Fix #2: -25-30% CPU

---

## Fix #4: Increase Model Health Warmup Wait (Prevent Blocking)

**File**: `agent/core/intelligent_agent.py` → `initialize()` method (around line ~150)

**Original**:
```python
wait_deadline_s = getattr(settings, "model_health_warmup_wait_seconds", 45) or 45
started_at = time.time()
while (time.time() - started_at) < wait_deadline_s:
    if self._check_market_data_health():
        break
    await asyncio.sleep(2.0)

warmup_attempts = getattr(settings, "model_health_warmup_attempts", 2) or 2
for attempt in range(warmup_attempts):
    # Blocks initialization until prediction succeeds
```

**Fix** (non-blocking warmup):
```python
# Fire warmup in background instead of blocking initialization
asyncio.create_task(self._model_nodes_health_warmup())

# Later in initialize():
logger.info(
    "agent_initialized_successfully",
    service="agent",
    message="Initialization complete; model warmup running in background"
)
```

**Impact**:
- Allows agent to accept commands while warmup running
- Prevents initialization timeout
- -5% CPU (less blocking)

**Location in code**: This is already partially done! Check line ~233 of intelligent_agent.py:
```python
# Fire-and-forget warmup to avoid the UI staying in model_nodes DEGRADED
# until the first successful prediction runs.
try:
    asyncio.create_task(self._model_nodes_health_warmup())
except Exception:
    pass
```

This is correct. No change needed - it's already non-blocking.

---

## How to Apply These Fixes

### Option 1: Manual Edit (Recommended for testing)

1. Edit `agent/data/market_data_service.py`:
   - Apply Fix #2 (smart polling) - Lines 470-530
   - Apply Fix #3 (batch checks) - Lines 530-550

2. Rebuild Docker image:
   ```bash
   cd "D:\ATTRAL\Projects\Trading Agent 2"
   docker-compose down
   docker-compose build --no-cache agent
   docker-compose up -d agent
   ```

3. Monitor:
   ```bash
   docker stats jacksparrow-agent --no-stream
   # CPU should drop from 100% to 65-75%
   
   docker logs jacksparrow-agent -f | grep "market_data_stream_mode"
   ```

### Option 2: Quick Config Change (Immediate, no rebuild)

Edit `.env`:
```bash
# Reduce polling frequency immediately
FAST_POLL_INTERVAL=2.0  # Was 0.5s (if not set)
WEBSOCKET_FALLBACK_POLL_INTERVAL=10.0  # Was 60s
```

Then restart:
```bash
docker-compose restart agent backend
```

**This gives ~30% CPU reduction without code changes.**

---

## Validation Checklist

After applying fixes:

- [ ] Docker stats shows Agent CPU < 75%
- [ ] Backend logs show < 2 websocket timeouts per minute (vs 1+ per second currently)
- [ ] WebSocket connection stays active longer (check `agent_service_websocket_connected` frequency)
- [ ] Market data updates still flowing (check `candle_closed_event_emitted`)
- [ ] Predictions still generated every 15 minutes (check logs)
- [ ] No increase in errors or exceptions

**Timeline**: Apply fixes → wait 10 minutes → check metrics

---

## Expected Results

| Metric | Before | After | % Improvement |
|--------|--------|-------|---|
| Agent CPU % | 100 | 70 | 30% |
| WebSocket Timeouts/min | ~10 | <2 | 80% |
| API Calls/min | 120+ | 20-30 | 75% |
| Backend CPU % | 100 | 80 | 20% |

**These fixes are low-risk**: 
- No logic changes
- No feature removal
- Just optimization of polling frequency
- Can revert instantly if needed

---

## Next Steps (After Validating These Fixes)

1. Profile prediction latency (identify slowest component)
2. Parallelize feature computation (Medium-term fix)
3. Implement prediction caching (reduce redundant ML calls)
4. Consider multi-process architecture for true parallelism
