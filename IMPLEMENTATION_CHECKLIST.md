# Quick Implementation Checklist

## 🔍 Pre-Fix Diagnostics (Do This First)

Run these commands and save output for comparison:

```bash
# 1. Baseline metrics (run for 2 minutes)
docker stats jacksparrow-agent jacksparrow-backend --no-stream > baseline_stats.txt

# 2. WebSocket timeout rate
docker logs jacksparrow-backend 2>&1 | grep -c "agent_service_websocket_timeout" > baseline_timeouts.txt

# 3. API call rate (count over 1 minute)
docker logs jacksparrow-agent --tail 1000 2>&1 | grep -c "get_ticker\|market_data" > baseline_api_calls.txt

# 4. Current poll interval
docker logs jacksparrow-agent --tail 100 2>&1 | grep "market_data_stream_mode" | head -1
```

**Save these outputs** for comparison after fixes.

---

## ✅ PHASE 1: Configuration Fix (5 Minutes, No Rebuild)

### Step 1.1: Edit `.env` File

**Location**: `D:\ATTRAL\Projects\Trading Agent 2\.env`

**Find and modify these lines** (add if not present):

```bash
# Reduce polling frequency to be WebSocket-aware
FAST_POLL_INTERVAL=2.0
WEBSOCKET_FALLBACK_POLL_INTERVAL=10.0
CANDLE_POLL_INTERVAL_SECONDS=30

# Increase WebSocket timeouts to accommodate CPU saturation
WEBSOCKET_RECONNECT_ATTEMPTS=7
WEBSOCKET_RECONNECT_DELAY=2.0
```

### Step 1.2: Restart Containers

```bash
cd "D:\ATTRAL\Projects\Trading Agent 2"
docker-compose restart agent backend
```

### Step 1.3: Verify Changes

```bash
# Wait 30 seconds, then check logs
docker logs jacksparrow-agent --tail 20
```

Look for: `"market_data_stream_mode"` with new interval values

**Expected result**: CPU drops from 100% to ~85% (not huge yet, code changes needed for bigger gains)

---

## ✅ PHASE 2: Code Fix (30 Minutes + Build Time)

### Step 2.1: Edit `market_data_service.py`

**File**: `D:\ATTRAL\Projects\Trading Agent 2\agent\data\market_data_service.py`

**Find this code** (around line 470):
```python
        logger.info(
            "market_data_stream_mode",
            websocket_enabled=self._websocket_enabled,
            websocket_connected=self._websocket_connected,
            poll_interval=poll_interval,
            symbols=self.streaming_symbols
        )

        while self.streaming_running:
```

**Replace with**:
```python
        logger.info(
            "market_data_stream_mode",
            websocket_enabled=self._websocket_enabled,
            websocket_connected=self._websocket_connected,
            poll_interval=poll_interval,
            symbols=self.streaming_symbols,
            message="WebSocket-driven mode: reduced ticker polling" if (self._websocket_enabled and self._websocket_connected) else "REST API fallback mode"
        )

        # Track last manual ticker check per symbol for smart throttling
        last_manual_ticker_check: Dict[str, float] = {}
        manual_ticker_interval = 10.0

        while self.streaming_running:
```

### Step 2.2: Update Ticker Polling Logic

**Find this code** (around line 520):
```python
                for symbol in self.streaming_symbols:
                    # Only poll tickers via REST API if WebSocket is not available or enabled
                    if not (self._websocket_enabled and self._websocket_connected):
                        # Continuously monitor tickers for price fluctuations (REST fallback)
                        await self._check_and_emit_ticker_with_fluctuation(symbol)
```

**Replace with**:
```python
                for symbol in self.streaming_symbols:
                    # Only poll tickers via REST API if WebSocket is not available
                    if not (self._websocket_enabled and self._websocket_connected):
                        # REST API fallback when WebSocket unavailable
                        await self._check_and_emit_ticker_with_fluctuation(symbol)
                    else:
                        # Even with WebSocket, do occasional checks for redundancy/verification
                        now = time.time()
                        last_check = last_manual_ticker_check.get(symbol, 0)
                        if now - last_check >= manual_ticker_interval:
                            await self._check_and_emit_ticker_with_fluctuation(symbol)
                            last_manual_ticker_check[symbol] = now
```

### Step 2.3: Rebuild Docker Image

```bash
cd "D:\ATTRAL\Projects\Trading Agent 2"

# Stop containers
docker-compose down

# Rebuild agent image
docker-compose build --no-cache agent

# Start containers
docker-compose up -d
```

**Wait for containers to start** (~2 minutes):
```bash
docker ps | grep jacksparrow
# All 5 containers should show "Up"
```

### Step 2.4: Verify Build

```bash
# Check for errors
docker logs jacksparrow-agent | head -50

# Should see: "agent_initialized_successfully"
docker logs jacksparrow-agent | grep "agent_initialized_successfully"
```

---

## ✅ PHASE 3: Increase WebSocket Timeout

This is likely in your backend code. Find your backend WebSocket client.

**Likely locations**:
- `backend/services/agent_service.py`
- `backend/api/websocket/client.py`
- `backend/api/services/agent_communication.py`

**Search for**: `asyncio.wait_for` with timeout around 5 seconds

**Current**:
```python
response = await asyncio.wait_for(
    self.ws.send_json({"command": cmd}),
    timeout=5.0
)
```

**Change to**:
```python
response = await asyncio.wait_for(
    self.ws.send_json({"command": cmd}),
    timeout=15.0
)
```

**If you can't find it**: Search for `"agent_service_websocket_timeout"` in logs—that's where the timeout occurs.

---

## 📊 PHASE 4: Measure Improvements

### Step 4.1: Post-Fix Metrics (Wait 5-10 Minutes After Restart)

```bash
# Capture new metrics
docker stats jacksparrow-agent jacksparrow-backend --no-stream > after_stats.txt

# Check WebSocket timeout rate
docker logs jacksparrow-backend 2>&1 | grep -c "agent_service_websocket_timeout" > after_timeouts.txt

# Check market data stream mode
docker logs jacksparrow-agent --tail 50 2>&1 | grep "market_data_stream_mode"
```

### Step 4.2: Compare Results

| Metric | Before | After | Target | Status |
|--------|--------|-------|--------|--------|
| Agent CPU % | `___` | `___` | <75% | ☐ |
| Backend CPU % | `___` | `___` | <85% | ☐ |
| WS Timeouts/min | `___` | `___` | <2 | ☐ |
| Poll Interval | 0.5s | 10.0s | ✓ | ☐ |

### Step 4.3: Validate Communication

```bash
# Check WebSocket connection stability
docker logs jacksparrow-backend 2>&1 | grep -E "websocket_connected|websocket_timeout|websocket_disconnected" | tail -20
```

**Expected**:
- More `websocket_connected` messages
- Fewer `websocket_timeout` messages
- Connections staying active longer

### Step 4.4: Verify Data Flow

```bash
# Check candle closed events (should still occur)
docker logs jacksparrow-agent 2>&1 | grep "candle_closed_event_emitted" | tail -5

# Check model predictions (should still run every ~15 minutes)
docker logs jacksparrow-agent 2>&1 | grep -E "model_nodes_warmup|process_prediction" | tail -5
```

---

## 🔧 Troubleshooting If Things Break

### Issue: Agent won't start after rebuild

**Solution**:
```bash
# Check logs for specific error
docker logs jacksparrow-agent

# Rebuild without cache (sometimes fixes compilation issues)
docker-compose build --no-cache agent

# If still failing, revert the code change
git checkout agent/data/market_data_service.py

# Rebuild again
docker-compose build agent
docker-compose up -d
```

### Issue: WebSocket still timing out frequently

**Solution**:
1. Verify timeout was increased in backend code
2. Check if Agent CPU is STILL 100%
3. Look for other CPU hogs in agent logs

```bash
docker logs jacksparrow-agent 2>&1 | grep -i error | head -20
```

### Issue: Ticker data stops updating

**Solution**:
```bash
# Check if WebSocket is connected
docker logs jacksparrow-agent 2>&1 | grep -i websocket | tail -10

# If WebSocket failing, check Delta Exchange API status
# Look for circuit breaker errors
docker logs jacksparrow-agent 2>&1 | grep -i circuit | tail -5
```

---

## ✨ Optional: Advanced Fixes (Recommended Later)

### Add CPU Monitoring Alert

**File**: Create `agent/monitoring/cpu_alert.py`

```python
import psutil
import structlog

logger = structlog.get_logger()

async def monitor_cpu():
    while True:
        cpu_pct = psutil.cpu_percent(interval=1)
        
        if cpu_pct > 90:
            logger.warning("high_cpu_usage", cpu_percent=cpu_pct)
        
        await asyncio.sleep(30)
```

### Implement Prediction Caching

**File**: Modify `core/mcp_orchestrator.py`

```python
# Add at class level
self.prediction_cache = {}
self.cache_ttl = 10  # seconds

# Modify process_prediction_request():
async def process_prediction_request(self, symbol, context):
    cache_key = f"{symbol}:{context.get('interval', '15m')}"
    cached = self.prediction_cache.get(cache_key)
    
    if cached and time.time() - cached['time'] < self.cache_ttl:
        return cached['result']
    
    result = await self._run_predictions(symbol, context)
    self.prediction_cache[cache_key] = {'result': result, 'time': time.time()}
    return result
```

---

## 📋 Final Checklist

Before considering this complete:

- [ ] Phase 1 applied (config changes)
- [ ] Phase 2 applied (code changes)
- [ ] Phase 3 applied (WebSocket timeout)
- [ ] All containers restarted successfully
- [ ] Agent CPU dropped from 100% to <80%
- [ ] WebSocket timeouts reduced by >50%
- [ ] Candle events still generating (check logs)
- [ ] Model predictions still running (check logs)
- [ ] No new errors in container logs
- [ ] Baseline metrics saved for documentation

---

## 📞 If Issues Persist

1. **Verify all three phases were applied**:
   ```bash
   grep "manual_ticker_interval" agent/data/market_data_service.py
   # Should return the code change
   
   grep "timeout=15.0" backend/services/agent_service.py
   # Should return the timeout change
   ```

2. **Check for conflicting configurations**:
   ```bash
   docker exec jacksparrow-agent env | grep -i poll
   # Should show new polling intervals
   ```

3. **Rebuild from scratch** if uncertain:
   ```bash
   docker-compose down
   docker system prune -f
   docker-compose up -d
   ```

4. **Review the analysis documents**:
   - `CPU_BOTTLENECK_ANALYSIS.md` - Understanding the issue
   - `COMMUNICATION_ANALYSIS.md` - Deep technical dive
   - `FIXES_IMMEDIATE.md` - Detailed code changes

---

## ✅ Success Criteria

After all fixes, you should see:

✅ **Agent CPU**: 60-75% (down from 100%)
✅ **Backend CPU**: 75-85% (down from 100%)
✅ **WebSocket**: Stable connection, <2 timeouts/min
✅ **Data flow**: All events still processing normally
✅ **Latency**: Response times <1s instead of 5-10s
✅ **Reliability**: Trading signals continuous, no gaps

---

**Estimated Total Time**: 1-2 hours (including testing)
**Risk Level**: LOW (optimization only)
**Rollback Time**: 5 minutes (docker-compose restart)

You've got this! 🚀
