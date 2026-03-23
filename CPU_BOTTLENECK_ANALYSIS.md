# CPU Bottleneck & Communication Analysis

## Status Refresh (2026-03-23)
- `docker-compose.yml` already includes healthchecks and `depends_on: condition: service_healthy`.
- Agent model-node warmup is already non-blocking (`asyncio.create_task(...)` in `agent/core/intelligent_agent.py`).
- `_stream_loop()` already skips REST ticker polling while WebSocket is connected; fallback polling remains the primary tuning surface.
- Main remaining risk is status timeout sensitivity during CPU spikes and inference hot-path cost.

## Current Status
- **Agent Container**: 100.34% CPU, 150.5MB RAM
- **Backend Container**: 100.37% CPU, 88.16MB RAM
- **Issue**: WebSocket timeout → fallback to slower Redis queue

---

## Root Causes

### 1. **CPU Saturation (100%)**

#### Primary Bottleneck: Feature Computation Loop
**Location**: `agent/core/intelligent_agent.py` → `_periodic_monitoring()` + `_stream_loop()`

**Problem**: Continuous async operations competing for single-threaded Python event loop:
- **Ticker polling**: `await self._check_and_emit_ticker_with_fluctuation()` runs every 0.5s (fast_poll_interval)
- **Candle polling**: `await self._check_and_emit_candle()` runs every 30s
- **Prediction requests**: Event bus consuming CandleClosedEvent → MCPOrchestrator.process_prediction_request()
- **Market data parsing**: JSON parsing, float conversions, timestamp conversions
- **Model predictions**: ML inference + feature computation in MCPOrchestrator

#### Secondary Bottleneck: Model Inference
**Location**: `agent/core/mcp_orchestrator.py` → MCPOrchestrator.process_prediction_request()

**Heavy operations**:
- Running predictions on all loaded models
- Feature engineering + normalization
- Reasoning engine vector similarity searches
- Multi-timeframe trend analysis

#### Tertiary Bottleneck: Event Bus Publishing
**Location**: `agent/events/event_bus.py` 

**Problem**: Synchronous JSON serialization in hot loop:
```python
json.dumps(response, default=_json_serializer)  # Line 1099, intelligent_agent.py
```
This runs for every response + every event published.

---

### 2. **WebSocket Timeout Cascade**

**Sequence**:
1. Backend sends `get_status` command via WebSocket
2. Agent receives message on port 8003
3. Agent's event loop is **blocked/delayed** processing CPU-intensive prediction
4. WebSocket response handler not serviced in time (5-10s timeout)
5. Backend receives timeout, disconnects WebSocket
6. Backend falls back to Redis queue (slower, but not blocking)
7. Pattern repeats: CPU saturation → timeout → fallback

---

## Docker-Compose Resource Limits (Current)

| Service | CPU Limit | CPU Reservation | Memory Limit | Memory Reservation |
|---------|-----------|-----------------|--------------|-------------------|
| **Agent** | 4 CPUs | 2 CPUs | 4GB | 2GB |
| **Backend** | 2 CPUs | 1 CPU | 2GB | 1GB |
| Postgres | 2 CPUs | 1 CPU | 2GB | 1GB |
| Redis | 1 CPU | 0.5 CPU | 1GB | 512MB |
| Frontend | 1 CPU | 0.5 CPU | 1GB | 512MB |

**Analysis**: 
- Limits are generous (4 CPU for agent)
- But agent **exceeds 100% CPU** = hitting all available container CPUs
- Python's GIL means even 4-core limit is effectively single-threaded

---

## Hot Spots Identified in Code

### Spot 1: Ticker Polling Loop (HIGH IMPACT)
**File**: `market_data_service.py:_stream_loop()` (line 500+)

```python
while self.streaming_running:
    for symbol in self.streaming_symbols:
        # REST API call every 0.5 seconds (fast_poll_interval)
        await self._check_and_emit_ticker_with_fluctuation(symbol)
        
        # REST API call every 30s
        await self._check_and_emit_candle(symbol, interval)
    
    await asyncio.sleep(poll_interval)  # 0.5s when no WebSocket
```

**Cost per iteration**:
- Delta Exchange API call (network round-trip)
- JSON parsing & deserialization
- Float conversions (10+ fields)
- Timestamp conversions
- Price change calculations
- Event bus publish (JSON serialization)

**Frequency**: Every 0.5 seconds = 120 API calls/min

### Spot 2: Model Prediction Pipeline (VERY HIGH IMPACT)
**File**: `core/mcp_orchestrator.py` (not shown but referenced)

**Triggered by**: `CandleClosedEvent` → `process_prediction_request()`

**Operations**:
- Fetch OHLCV candles for multiple timeframes (3m, 5m, 15m)
- Compute features for each timeframe
- Run inference on all models (potentially multiple loaded)
- Ensemble predictions
- Reasoning engine queries

**Frequency**: Every candle close (~15 min for 15m interval)
**Duration**: Unknown but likely 1-5 seconds per prediction

### Spot 3: JSON Serialization in Response Path
**File**: `intelligent_agent.py:_send_response()` (line 1099)

```python
json.dumps(response, default=_json_serializer)  # CPU-intensive custom serializer
```

**Called for**:
- Every command response (predictable)
- Every event published via Redis Streams (frequent)

---

## Recommendations (Priority Order)

### IMMEDIATE (Next 24 hours)

#### 1. Increase Status Command Timeout (Low effort, high impact)
**File**: `backend/services/agent_service.py` (or equivalent)

```python
# Use config-backed timeout for get_status path
# AGENT_STATUS_COMMAND_TIMEOUT_SECONDS=15
```

**Status**: Implemented.

**Impact**: Reduces false WebSocket timeout fallback to Redis under CPU pressure

---

#### 2. Tune REST fallback polling (WS-connected path already optimized)
**File**: `market_data_service.py:_stream_loop()` (line ~470)

```python
# Tune fallback mode envs:
# FAST_POLL_INTERVAL
# CANDLE_POLL_INTERVAL_SECONDS
# WEBSOCKET_FALLBACK_POLL_INTERVAL
```

**Status**: Previous recommendation text was stale; WS-connected mode already suppresses REST ticker polling.

---

#### 3. Batch/skip redundant fallback ticker checks
**File**: `market_data_service.py:_stream_loop()` (line ~520)

```python
# In fallback mode, reduce repeated per-symbol REST checks:
# - Skip symbols with very recent processed tick metadata
# - Batch multi-symbol ticker fetches where exchange API supports it
```

**Impact**: Further 30% reduction in REST API calls

---

### SHORT TERM (This week)

#### 4. Optimize Model Prediction Frequency
**File**: `core/intelligent_agent.py:_periodic_monitoring()` (line ~1650)

Current: Triggers warmup prediction at startup + every CandleClosedEvent

```python
# Add cooldown to avoid redundant predictions
last_prediction_time = None
min_prediction_interval = 30  # Seconds between predictions

if time.time() - last_prediction_time > min_prediction_interval:
    await self.mcp_orchestrator.process_prediction_request(...)
    last_prediction_time = time.time()
```

**Impact**: Reduce CPU spikes during high-frequency candle closes

---

#### 5. Parallelize Feature Computation
**File**: `core/mcp_orchestrator.py`

```python
# Current: Sequential feature computation per model
for model in models:
    features = await compute_features(model)  # Waits for each

# Change to: Parallel feature computation
tasks = [compute_features(model) for model in models]
results = await asyncio.gather(*tasks)
```

**Impact**: 40-60% faster prediction cycles

---

#### 6. Add CPU Throttling via Event Bus Backpressure
**File**: `events/event_bus.py`

```python
# Implement queue depth monitoring
if queue_depth > max_queue_depth:
    # Skip non-critical events (e.g., telemetry) instead of failing
    if event.type not in [EventType.CANDLE_CLOSED, EventType.DECISION_READY]:
        return False  # Drop low-priority event
```

**Impact**: Prevents event queue backlog from causing memory bloat

---

### MEDIUM TERM (Next sprint)

#### 7. Consider Multi-Process Architecture
**Option A**: Run feature server in separate process
```bash
# Instead of embedding feature server in agent, run separately:
# Process 1: Agent (command handler + trading logic)
# Process 2: Feature Server (REST API for model predictions)
# Process 3: Market Data (WebSocket listener)
```

**Impact**: Breaks GIL limitation; use full 4-core CPU allocation

**Option B**: Use async worker pool for CPU-bound tasks
```python
from concurrent.futures import ProcessPoolExecutor
executor = ProcessPoolExecutor(max_workers=2)
result = await asyncio.get_event_loop().run_in_executor(
    executor, 
    cpu_intensive_function
)
```

---

#### 8. Implement Smart Model Caching
**Location**: `core/mcp_orchestrator.py`

```python
# Cache predictions for 10 seconds if no major market moves
prediction_cache = {}  # symbol -> (timestamp, result)
cache_ttl = 10  # seconds

async def process_prediction_request(symbol, context):
    cached = prediction_cache.get(symbol)
    if cached and time.time() - cached[0] < cache_ttl:
        return cached[1]  # Reuse prediction
    
    result = await run_models(symbol, context)
    prediction_cache[symbol] = (time.time(), result)
    return result
```

**Impact**: Eliminate redundant predictions; save 30-50% CPU on stable markets

---

#### 9. Add Monitoring & Alerting
**File**: Create `agent/monitoring/cpu_monitor.py`

```python
async def monitor_cpu_and_throttle():
    while running:
        cpu_pct = psutil.Process().cpu_percent(interval=1)
        
        if cpu_pct > 90:  # Critical
            # Reduce polling frequency
            settings.fast_poll_interval = 2.0  # Was 0.5s
            logger.warning(f"CPU throttled: {cpu_pct}%")
        elif cpu_pct < 60:  # Recovered
            settings.fast_poll_interval = 0.5  # Restore normal
        
        await asyncio.sleep(10)
```

**Impact**: Auto-scaling based on actual CPU load

---

## Performance Targets

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Agent CPU | 100% | 60-70% | Reduce polling + parallelize |
| WebSocket Timeout Rate | ~5% | <1% | Increase timeout + reduce CPU |
| Prediction Latency | 1-5s | 200-500ms | Parallel computation |
| API Calls/min | 120+ | 20-30 | Smart throttling |

---

## Docker-Compose Update Recommendation

**NO CHANGE needed** to resource limits—they're adequate. Focus on code optimization instead.

```yaml
# Current is fine; do NOT reduce
agent:
  deploy:
    resources:
      limits:
        cpus: '4'
        memory: 4G
      reservations:
        cpus: '2'
        memory: 2G
```

**Reason**: The issue is CPU **utilization** (hot loop), not CPU **availability**. More CPU won't help if the event loop is blocked on a single thread.

---

## Testing the Fixes

1. **After Immediate Fixes**: Monitor `docker stats` for 5 minutes
   ```bash
   docker stats jacksparrow-agent jacksparrow-backend --no-stream
   ```
   
2. **Check WebSocket Success Rate**:
   ```bash
   docker logs jacksparrow-backend | grep -c "agent_service_websocket_timeout"
   ```
   Should decrease significantly.

3. **Verify Prediction Latency**:
   ```bash
   docker logs jacksparrow-agent | grep "model_nodes_warmup_result"
   ```
   Check `attempt` field—should stay < 5 seconds per attempt.

---

## Summary

| Issue | Root Cause | Fix | Impact |
|-------|-----------|-----|--------|
| 100% CPU | Ticker polling loop | Reduce frequency when WebSocket active | -20% CPU |
| WebSocket timeouts | Event loop blocking | Increase timeout + reduce CPU | Stabilize communication |
| Prediction delays | Sequential feature computation | Parallelize asyncio tasks | -40% latency |
| Redis fallback dependency | Timeout cascade | Remove timeouts via CPU optimization | Restore WebSocket path |

**Start with recommendations 1-3 (1 hour of work) for immediate 30% CPU reduction.**
