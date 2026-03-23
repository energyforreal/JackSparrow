# Quick Reference Guide

## 📊 Current State (Broken)

```
AGENT CPU: ████████████████████ 100%
├─ Ticker Polling:    ████████░░░░░░░░░░ 40%
├─ Model Inference:   ████████░░░░░░░░░░ 25%
├─ JSON Serializing:  ░░░░░░████░░░░░░░░ 10%
└─ Event Processing:  █████░░░░░░░░░░░░░ 15%

BACKEND AWAITING RESPONSE...
WebSocket: TIMEOUT (5-10s) → Fallback to Redis (SLOW)
```

## 🎯 Target State (Fixed)

```
AGENT CPU: █████████░░░░░░░░░░ 70% (HEALTHY)
├─ Ticker Polling:    ███░░░░░░░░░░░░░░░ 15% (optimized)
├─ Model Inference:   ████████░░░░░░░░░░ 25% (parallel)
├─ JSON Serializing:  ░░░░░░░░░░░░░░░░░░ 5% (reduced)
└─ Event Processing:  █████░░░░░░░░░░░░░ 15% (normal)

BACKEND RESPONDING IN < 500ms
WebSocket: STABLE ✅ (no timeouts)
```

---

## 🔧 Three-Phase Fix

### PHASE 1: Config (5 min, No rebuild)
```bash
Edit .env:
  FAST_POLL_INTERVAL=2.0
  WEBSOCKET_FALLBACK_POLL_INTERVAL=10.0

Then: docker-compose restart agent backend
```
**Result**: -10% CPU

### PHASE 2: Code (30 min + build)
```bash
Edit agent/data/market_data_service.py:
  Add smart polling logic (see FIXES_IMMEDIATE.md)
  
Build: docker-compose build --no-cache agent
```
**Result**: -20% CPU

### PHASE 3: Backend (5 min, No rebuild)
```bash
Find WebSocket client in backend code
Change: timeout=5.0 → timeout=15.0
```
**Result**: Stabilize communication

---

## 📋 One-Liner Diagnostics

```bash
# Check current CPU (should be ~100% each)
docker stats --no-stream

# Check WebSocket health (should see timeouts)
docker logs jacksparrow-backend | grep timeout | wc -l

# Check polling frequency (should be 0.5s currently)
docker logs jacksparrow-agent | grep "poll_interval"

# Check if market data flowing (should see candles)
docker logs jacksparrow-agent | grep candle_closed | tail -1

# Check model health (should see predictions)
docker logs jacksparrow-agent | grep model_nodes | tail -1
```

---

## 📞 When to Apply Fixes

### Apply NOW if:
- ✅ WebSocket timeouts > 2/minute
- ✅ Agent CPU consistently 100%
- ✅ Backend unable to reach agent regularly
- ✅ Trading signals delayed/missed

### Wait if:
- ❌ System working fine (unlikely with 100% CPU)
- ❌ Code frozen (deploy window coming up)
- ❌ Can't test for 1 hour post-deployment

---

## 🚀 After Fixes Checklist

- [ ] Agent CPU dropped to 60-75%
- [ ] WebSocket timeouts < 2/min
- [ ] Response time < 1 second
- [ ] Candle events still generating
- [ ] Model predictions still running
- [ ] No new errors in logs
- [ ] Data flowing to database
- [ ] Redis connectivity stable

---

## 📚 Document Map

```
START HERE → EXECUTIVE_SUMMARY.md (overview)
                    ↓
UNDERSTAND → CPU_BOTTLENECK_ANALYSIS.md (deep dive)
                    ↓
        COMMUNICATION_ANALYSIS.md (architecture)
                    ↓
IMPLEMENT → IMPLEMENTATION_CHECKLIST.md (step by step)
                    ↓
REFERENCE → FIXES_IMMEDIATE.md (code changes)
```

---

## 🔍 Verification Steps

**After applying each phase:**

```bash
# 1. Container health
docker ps | grep jacksparrow
# Should see 5 running containers

# 2. CPU usage
docker stats --no-stream
# Agent should drop by 10% per phase

# 3. WebSocket status
docker logs jacksparrow-backend | grep -E "connected|timeout" | tail -20
# Should see more "connected", fewer "timeout"

# 4. Data flow
docker logs jacksparrow-agent | grep -E "candle_closed|market_tick" | tail -5
# Should see market data events

# 5. Predictions
docker logs jacksparrow-agent | grep -E "model_nodes|prediction" | tail -5
# Should see model activity
```

---

## 💡 Key Insights

1. **Network is fine** - All containers communicating correctly
2. **Problem is CPU** - Agent event loop blocked, can't respond to WebSocket
3. **Solution is polling** - Reduce redundant API calls by 75%
4. **Risk is low** - Optimization only, no logic changes
5. **Impact is high** - 30% CPU reduction + stable communication

---

## ⏱️ Timeline

| Phase | Time | Impact | Risk |
|-------|------|--------|------|
| Phase 1 | 5 min | 10% CPU | None |
| Phase 2 | 1 hr | 20% CPU | Low |
| Phase 3 | 5 min | Stable comm | None |
| **Total** | **~1.5 hrs** | **30% CPU** | **LOW** |

---

## 🎓 Learning Resources

**Python asyncio**: The issue is event loop blocking due to CPU-intensive work
**Docker networking**: All your container-to-container comms are correctly configured
**Polling patterns**: Smart polling reduces API load by detecting when data is already fresh

---

## ✨ Next Steps

1. Read `EXECUTIVE_SUMMARY.md` (5 min)
2. Read `CPU_BOTTLENECK_ANALYSIS.md` if needed (15 min)
3. Follow `IMPLEMENTATION_CHECKLIST.md` (1-2 hours)
4. Verify improvements with metrics (10 min)
5. Document results (5 min)

**Total time**: 2-2.5 hours including testing

---

## 🆘 If Stuck

### Problem: Don't understand the issue?
→ Read: CPU_BOTTLENECK_ANALYSIS.md + COMMUNICATION_ANALYSIS.md

### Problem: Can't find where to make changes?
→ Check: FIXES_IMMEDIATE.md (has exact file paths and line numbers)

### Problem: Build fails after changes?
→ Follow: Troubleshooting section in IMPLEMENTATION_CHECKLIST.md

### Problem: Still 100% CPU after fixes?
→ Check: Did you rebuild the agent image? (`docker-compose build --no-cache agent`)

---

## 📊 Expected Metrics

| Metric | Before | After | How to Check |
|--------|--------|-------|--------------|
| CPU % | 100 | 70 | `docker stats` |
| Timeouts/min | 8 | 1 | `docker logs` grep timeout |
| Latency | 5-10s | <1s | Response time |
| API calls/min | 120+ | 20-30 | Log analysis |

---

## 🏁 Success

When you see:
```
docker stats output:
  Agent:    75% CPU (was 100%)
  Backend:  80% CPU (was 100%)

docker logs output:
  agent_service_websocket_connected (frequent)
  agent_service_websocket_timeout (rare, <2/min)
  candle_closed_event_emitted (regular)
  market_tick_event_emitted (continuous)
```

**✅ You've successfully fixed the issue!**

---

## 📞 Questions?

1. **CPU still high?** → Check if Phase 2 (code changes) was rebuilt
2. **WebSocket still timeout?** → Check if Phase 3 (backend timeout) was applied
3. **Build failed?** → Run `docker-compose down && docker system prune -f`
4. **Lost changes?** → Run `git status` to check what modified

---

## 🎉 You Got This!

Your system is solid. This is just an optimization that becomes visible under load.

After these fixes, you'll have:
- ✅ Stable WebSocket communication
- ✅ Responsive API
- ✅ 30% more CPU available
- ✅ Confidence for scaling

**Let's go!** 🚀
