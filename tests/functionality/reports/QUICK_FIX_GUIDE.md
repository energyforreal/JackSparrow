# Quick Fix Guide - Test Report Issues

## 🚨 Critical Issues (Fix First)

### 1. Port 8001 Conflict
**Problem**: Agent can't start because port 8001 is in use.

**Quick Fix** (Windows PowerShell):
```powershell
# Find and kill process using port 8001
Get-NetTCPConnection -LocalPort 8001 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
```

**Permanent Fix**: See `FIX_PROPOSALS.md` Section 1.1

---

### 2. Missing Environment Variables
**Problem**: Tests fail because DATABASE_URL, REDIS_URL, DELTA_EXCHANGE_API_KEY not set.

**Quick Fix**:
1. Create `tests/functionality/.env.test`:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/trading_agent_test
REDIS_URL=redis://localhost:6379/15
DELTA_EXCHANGE_API_KEY=your_test_key
DELTA_EXCHANGE_API_SECRET=your_test_secret
FEATURE_SERVER_PORT=8001
```

2. Or set environment variables before running tests:
```powershell
$env:DATABASE_URL="postgresql://user:pass@localhost:5432/trading_agent_test"
$env:REDIS_URL="redis://localhost:6379"
$env:DELTA_EXCHANGE_API_KEY="test_key"
python tests/functionality/run_all_tests.py
```

---

### 3. WebSocket Connection Failure
**Problem**: Agent WebSocket server not running during tests.

**Quick Fix**: Start agent before running tests:
```bash
# Terminal 1: Start agent
python -m agent.main

# Terminal 2: Run tests
python tests/functionality/run_all_tests.py
```

**Better Fix**: Tests should mock WebSocket server (see `FIX_PROPOSALS.md` Section 1.2)

---

### 4. No Models Discovered
**Problem**: `agent/model_storage/` is empty.

**Quick Fix**: Copy production models:
```powershell
# Copy models from root models/ directory
Copy-Item models\xgboost_*.pkl agent\model_storage\xgboost\
```

Or create a dummy test model (see `FIX_PROPOSALS.md` Section 2.2)

---

## ⚠️ Warnings (Can Fix Later)

### Rate Limiting Test
- **Issue**: Test needs multiple rapid requests
- **Fix**: See `FIX_PROPOSALS.md` Section 3.1
- **Priority**: Medium

### Error Handling Test
- **Issue**: Needs failure simulation
- **Fix**: See `FIX_PROPOSALS.md` Section 3.2
- **Priority**: Medium

### Command Types Test
- **Issue**: Only 0/3 command types tested
- **Fix**: See `FIX_PROPOSALS.md` Section 3.3
- **Priority**: Medium

### Timeout Handling
- **Issue**: Needs special setup
- **Fix**: See `FIX_PROPOSALS.md` Section 3.4
- **Priority**: Medium

---

## 📊 Expected Results After Quick Fixes

| Metric | Current | After Quick Fixes | Target |
|--------|---------|-------------------|--------|
| Health Score | 69.23% | ~75-80% | >80% |
| Critical Failures | 2 | 0-1 | 0 |
| Warnings | 18 | 10-12 | <10 |
| Pass Rate | 69.2% | ~80% | >85% |

---

## 🔄 Test Execution Order

1. **Fix port conflict** → Run tests → Should see agent initialization pass
2. **Set environment variables** → Run tests → Should see database/Redis warnings reduce
3. **Add test models** → Run tests → Should see model discovery pass
4. **Start services** → Run tests → Should see WebSocket tests pass

---

## 📝 Next Steps

1. Read `FIX_PROPOSALS.md` for detailed solutions
2. Implement Phase 1 fixes (Critical)
3. Implement Phase 2 fixes (Configuration)
4. Run tests again: `python tests/functionality/run_all_tests.py`
5. Review new report and iterate

---

## 🆘 Still Having Issues?

1. Check service health:
   ```bash
   # Check if services are running
   netstat -ano | findstr :8000  # Backend
   netstat -ano | findstr :8001  # Feature Server
   netstat -ano | findstr :8002  # Agent WebSocket
   netstat -ano | findstr :6379  # Redis
   netstat -ano | findstr :5432  # PostgreSQL
   ```

2. Check logs:
   - `logs/agent/` - Agent logs
   - `logs/backend/` - Backend logs
   - Test output - Test execution logs

3. Verify configuration:
   - `.env` file exists in project root
   - Environment variables are set correctly
   - Services are accessible

