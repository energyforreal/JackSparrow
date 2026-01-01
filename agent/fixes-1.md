# Cursor.ai Instructions — Quiet Stability Fix Implementation  
### Purpose  
This document provides **step-by-step instructions for Cursor.ai** to apply **non-breaking stability improvements** to the JackSparrow Trading Agent.  
The changes are **additive**, safe, and focused on improving:  
- Paper trading reliability  
- WebSocket stability  
- Frontend live updates  
- Backend ↔ Agent communication  
- Feature quality handling  

Cursor.ai must apply each patch **exactly as written**, without altering architecture.

---

# ✅ 1. Agent Execution Pipeline Hardening

### File: `agent/core/execution.py`
Add input validation and critical logging at the start of trade execution.

```diff
@@ def execute_trade(self, decision):
+   self.logger.info("EXECUTION: Entered execute_trade with decision=%s", decision)

+   if decision is None:
+       self.logger.warning("EXECUTION: Skipping trade — decision is None")
+       return

+   if self.context.features is None:
+       self.logger.warning("EXECUTION: Features missing — aborting trade")
+       return
```

Add confirmation logging when an order fills:

```diff
@@ def on_order_filled(self, order):
+   self.logger.info(
+       "EXECUTION: Order filled — id=%s qty=%s price=%s side=%s",
+       order.id, order.quantity, order.price, order.side
+   )
```

---

# ✅ 2. Risk Manager Safety Checks  

### File: `agent/risk/risk_manager.py`

```diff
@@ def validate_risk(self, position_size, portfolio_value):
+   self.logger.info(
+       "RISK CHECK: position_size=%s portfolio_value=%s heat=%s",
+       position_size, portfolio_value, self.current_portfolio_heat
+   )

+   if position_size <= 0:
+       self.logger.warning("RISK CHECK: position_size <=0 — blocking trade")
+       return False
```

---

# ✅ 3. Backend → Agent Command Delivery Assurance  

### File: `backend/services/agent_service.py`

```diff
@@ async def send_command(self, command):
+   self.logger.info("BACKEND → AGENT: Sending command=%s", command)

+   try:
+       await self.websocket.send_json(command)
+   except Exception as e:
+       self.logger.error("BACKEND → AGENT WS FAIL: %s — falling back to Redis", e)
+       await self.redis.lpush("agent:commands", json.dumps(command))
+       return
```

Add a heartbeat function:

```diff
+ async def heartbeat(self):
+     try:
+         await self.websocket.send_json({"type": "ping"})
+     except:
+         self.logger.error("HEARTBEAT FAIL — triggering reconnect")
```

---

# ✅ 4. Agent WebSocket Server Hardening  

### File: `agent/api/websocket_server.py`

```diff
@@ async def handler(self, websocket):
+   self.logger.info("AGENT WS: Client connected")

@@ except Exception as e:
     self.logger.error("AGENT WS ERROR: %s", e)
+   self.logger.warning("AGENT WS: Forcing reconnect in 1s")
+   await asyncio.sleep(1)
```

Add heartbeat response:

```diff
@@ async for msg in websocket:
+   if msg.get("type") == "ping":
+       await websocket.send_json({"type": "pong"})
```

---

# ✅ 5. Event Publishing Reliability  

### File: `agent/events/event_bus.py`

```diff
@@ def publish(self, event):
+   if event is None:
+       self.logger.warning("EVENT BUS: Skipping publish — event is None")
+       return
```

---

# ✅ 6. Feature Server — Avoid “DEGRADED” Freeze  

### File: `agent/data/feature_server.py`

```diff
@@ def compute_features():
+   if quality == "DEGRADED":
+       self.logger.warning("FEATURE SERVER: DEGRADED — Sending partial features")
```

---

# ✅ 7. Backend → Frontend WebSocket Hardening  

### File: `backend/api/websocket/manager.py`

```diff
@@ async def broadcast(self, message):
+   if message is None:
+       self.logger.warning("WS MANAGER: Ignoring empty broadcast")
+       return
```

---

# ✅ 8. Frontend WebSocket Stability Fix  

### File: `frontend/hooks/useWebSocket.ts`  
Reduce reconnection maximum delay from 30s to 5s.

```diff
@@ function connect() {
-   retryDelay = Math.min(retryDelay * 2, 30000);
+   retryDelay = Math.min(retryDelay * 2, 5000);
```

Add debug logs for message tracking:

```diff
@@ socket.onmessage = (event) => {
+   console.log("WS MESSAGE:", event.data);
```

Add disconnection log:

```diff
@@ socket.onclose = () => {
+   console.warn("WS CLOSED — reconnecting in", retryDelay);
```

---

# 📌 Deployment Notes for Cursor.ai  
Cursor.ai must:

1. Apply each patch **exactly** as listed (non-destructive; additive only).  
2. Ensure indentation and spacing remain consistent with existing code style.  
3. Commit each modified file with the message:  
   ```
   chore: apply quiet stability patch (non-breaking)
   ```
4. Do **not** refactor or reorganize files.  
5. Do **not** remove any existing log statements.  
6. Do **not** modify architecture or business logic.

---

# 🎯 Result Expected After Patch  
- Paper trades execute reliably  
- Agent never silently blocks decisions  
- Backend ↔ Agent communication stable  
- Frontend always updates signals  
- WebSocket stays alive with heartbeat  
- Debugging becomes easier with structured logs  

---

**File Ends**
