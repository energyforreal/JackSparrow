# Docker Hot Reload Testing Guide

## Overview

This guide provides step-by-step procedures for testing and validating the Docker hot reload functionality. Use this guide to ensure hot reload works correctly for all services (backend, agent, frontend) before deploying to production.

## Prerequisites

Before testing, ensure:

- [ ] Docker Engine 20.10+ and Docker Compose 2.0+ installed
- [ ] `.env` file configured in project root
- [ ] Source code in `backend/`, `agent/`, and `frontend/` directories
- [ ] Validation script passes: `./scripts/docker/validate-hot-reload.sh` (or `.ps1` on Windows)

## Pre-Testing Validation

### Step 1: Validate Configuration

Run the validation script to ensure all components are properly configured:

```bash
# Unix/Linux/macOS
./scripts/docker/validate-hot-reload.sh

# Windows PowerShell
.\scripts\docker\validate-hot-reload.ps1

# Or using Makefile
make docker-validate
```

**Expected Output:**
- ✅ All Docker Compose files found
- ✅ All Dockerfile.dev files found
- ✅ Agent file watcher script found
- ✅ Watchdog installation verified
- ✅ Volume mounts verified
- ✅ Backend reload configuration verified
- ✅ Frontend dev server configuration verified

If any checks fail, fix the issues before proceeding.

## Testing Procedures

### Test 1: Backend Hot Reload

**Objective:** Verify that backend automatically restarts when Python files are modified.

#### Steps:

1. **Start Development Environment:**
   ```bash
   ./scripts/docker/dev-start.sh --build
   # or
   make docker-dev
   ```

2. **Monitor Backend Logs:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
   ```

3. **Make a Test Change:**
   ```bash
   # Edit any Python file in backend/
   # For example, add a comment to backend/api/main.py
   echo "# Test comment for hot reload" >> backend/api/main.py
   ```

4. **Verify Reload:**
   - Watch the logs for reload messages
   - Expected log output:
     ```
     INFO:     Detected file change in 'backend/api/main.py'. Reloading...
     INFO:     Application startup complete.
     ```

5. **Verify Service Still Works:**
   ```bash
   curl http://localhost:8000/api/v1/health
   ```
   Should return `{"status":"ok"}` or similar.

#### Success Criteria:
- [ ] Backend detects file change within 1-2 seconds
- [ ] Uvicorn reloads automatically
- [ ] Service remains healthy after reload
- [ ] No errors in logs

#### Troubleshooting:
- **No reload detected:** Check volume mount: `docker-compose config | grep volumes`
- **Service crashes:** Check logs for errors: `docker-compose logs backend`
- **Changes not visible:** Verify you're using dev compose file

---

### Test 2: Agent Hot Reload

**Objective:** Verify that agent automatically restarts when Python files are modified.

#### Steps:

1. **Start Development Environment** (if not already running):
   ```bash
   ./scripts/docker/dev-start.sh --build
   ```

2. **Monitor Agent Logs:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f agent
   ```

3. **Verify Watcher Started:**
   - Look for initial log messages:
     ```
     INFO: agent_watcher_starting watch_path=/app/agent message="Starting file watcher for hot-reload"
     INFO: agent_watcher_ready message="File watcher is ready. Agent will auto-reload on Python file changes."
     ```

4. **Make a Test Change:**
   ```bash
   # Edit any Python file in agent/
   # For example, add a comment to agent/core/intelligent_agent.py
   echo "# Test comment for hot reload" >> agent/core/intelligent_agent.py
   ```

5. **Verify Restart:**
   - Watch the logs for restart messages
   - Expected log output:
     ```
     INFO: agent_file_changed file=agent/core/intelligent_agent.py message="Python file changed, restarting agent..."
     INFO: agent_stopping message="Stopping existing agent process for restart"
     INFO: agent_starting message="Starting agent process"
     ```

6. **Verify Agent Restarted:**
   - Check that agent process is running:
     ```bash
     docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps agent
     ```
   - Should show status as "Up"

#### Success Criteria:
- [ ] File watcher starts successfully
- [ ] Agent detects file change within 1-2 seconds
- [ ] Agent process restarts gracefully
- [ ] Agent remains running after restart
- [ ] No errors in logs

#### Troubleshooting:
- **Watcher not starting:** Check watchdog installation: `docker-compose exec agent pip list | grep watchdog`
- **No restart detected:** Verify file watcher script exists: `docker-compose exec agent ls -la /app/agent/scripts/dev_watcher.py`
- **Agent crashes:** Check logs for errors: `docker-compose logs agent`

---

### Test 3: Frontend Hot Reload

**Objective:** Verify that frontend automatically updates when React/TypeScript files are modified.

#### Steps:

1. **Start Development Environment** (if not already running):
   ```bash
   ./scripts/docker/dev-start.sh --build
   ```

2. **Open Browser:**
   - Navigate to `http://localhost:3000`
   - Open browser developer console (F12)
   - Look for HMR connection message: `[HMR] connected`

3. **Monitor Frontend Logs:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f frontend
   ```

4. **Make a Test Change:**
   ```bash
   # Edit any React/TypeScript file in frontend/
   # For example, modify frontend/app/page.tsx or any component
   # Add a visible change like changing text or adding a comment
   ```

5. **Verify HMR Update:**
   - Browser should update automatically without full page reload
   - Check browser console for HMR messages
   - Expected console output:
     ```
     [HMR] connected
     [HMR] bundle rebuilding
     [HMR] bundle rebuilt in XXXms
     ```

6. **Verify Changes Visible:**
   - Changes should appear in browser immediately
   - No page refresh needed
   - Component state should be preserved (if applicable)

#### Success Criteria:
- [ ] HMR connection established
- [ ] Browser updates automatically on file change
- [ ] No full page reload required
- [ ] Changes visible within 1-2 seconds
- [ ] No errors in browser console

#### Troubleshooting:
- **HMR not connecting:** Check Next.js dev server is running: `docker-compose logs frontend | grep ready`
- **Changes not visible:** Hard refresh browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS)
- **Compilation errors:** Check frontend logs: `docker-compose logs -f frontend`

---

### Test 4: Multiple Simultaneous Changes

**Objective:** Verify hot reload handles multiple file changes correctly.

#### Steps:

1. **Start Development Environment:**
   ```bash
   ./scripts/docker/dev-start.sh --build
   ```

2. **Monitor All Logs:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f
   ```

3. **Make Changes to Multiple Services:**
   ```bash
   # Change backend file
   echo "# Backend test" >> backend/api/main.py
   
   # Wait 2 seconds
   sleep 2
   
   # Change agent file
   echo "# Agent test" >> agent/core/intelligent_agent.py
   
   # Wait 2 seconds
   sleep 2
   
   # Change frontend file (modify a component)
   ```

4. **Verify All Services Reload:**
   - Backend should reload
   - Agent should restart
   - Frontend should update in browser

#### Success Criteria:
- [ ] All services handle changes independently
- [ ] No conflicts between reloads
- [ ] All services remain healthy
- [ ] No errors in logs

---

### Test 5: Rapid File Changes (Debounce Test)

**Objective:** Verify debouncing prevents excessive restarts.

#### Steps:

1. **Start Development Environment:**
   ```bash
   ./scripts/docker/dev-start.sh --build
   ```

2. **Monitor Agent Logs:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f agent
   ```

3. **Make Rapid Changes:**
   ```bash
   # Make multiple rapid changes to agent file
   for i in {1..5}; do
     echo "# Change $i" >> agent/core/intelligent_agent.py
     sleep 0.3
   done
   ```

4. **Verify Debouncing:**
   - Agent should restart only once or twice (not 5 times)
   - Debounce delay should prevent excessive restarts

#### Success Criteria:
- [ ] Debouncing works correctly
- [ ] Not more than 2-3 restarts for 5 rapid changes
- [ ] Agent remains stable

---

## Comprehensive Test Checklist

Use this checklist to verify all hot reload functionality:

### Configuration
- [ ] Validation script passes all checks
- [ ] Docker Compose dev file is used
- [ ] Volume mounts are correct
- [ ] All services start successfully

### Backend Hot Reload
- [ ] Backend detects Python file changes
- [ ] Uvicorn reloads automatically
- [ ] Service remains healthy after reload
- [ ] API endpoints still work after reload

### Agent Hot Reload
- [ ] File watcher starts successfully
- [ ] Agent detects Python file changes
- [ ] Agent restarts gracefully
- [ ] Agent remains running after restart
- [ ] Debouncing works for rapid changes

### Frontend Hot Reload
- [ ] HMR connection established
- [ ] Browser updates on file changes
- [ ] No full page reload required
- [ ] Component state preserved (when applicable)
- [ ] Compilation errors shown in browser

### Integration
- [ ] Multiple services can reload simultaneously
- [ ] No conflicts between services
- [ ] All services remain healthy
- [ ] Logs are accessible and readable

### Performance
- [ ] Reload happens within 1-2 seconds
- [ ] No significant performance degradation
- [ ] Memory usage remains stable
- [ ] CPU usage is reasonable

## Troubleshooting During Testing

### Common Issues

**Issue: Changes not detected**
- Verify using dev compose: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps`
- Check volume mounts: `docker-compose config | grep volumes`
- Verify file permissions

**Issue: Service crashes on reload**
- Check logs: `docker-compose logs -f [service]`
- Verify code changes are valid (no syntax errors)
- Check for import errors

**Issue: Agent not restarting**
- Verify watchdog installed: `docker-compose exec agent pip list | grep watchdog`
- Check watcher script: `docker-compose exec agent ls -la /app/agent/scripts/dev_watcher.py`
- Restart manually: `docker-compose restart agent`

**Issue: Frontend not updating**
- Check HMR connection in browser console
- Verify Next.js dev server running: `docker-compose logs frontend`
- Hard refresh browser
- Check for compilation errors

### Debug Commands

```bash
# Check service status
docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps

# View all logs
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

# Check volume mounts
docker-compose -f docker-compose.yml -f docker-compose.dev.yml config | grep -A 5 volumes

# Verify file watcher (agent)
docker-compose exec agent ps aux | grep dev_watcher

# Check watchdog installation
docker-compose exec agent pip list | grep watchdog

# Test backend health
curl http://localhost:8000/api/v1/health

# Check frontend
curl http://localhost:3000
```

## Automated Testing

For automated testing, use the test scripts:

```bash
# Unix/Linux/macOS
./scripts/docker/test-hot-reload.sh

# Windows PowerShell
.\scripts\docker\test-hot-reload.ps1
```

See the test scripts for automated validation procedures.

## Success Criteria Summary

Hot reload is working correctly if:

1. ✅ All validation checks pass
2. ✅ Backend reloads on Python file changes
3. ✅ Agent restarts on Python file changes
4. ✅ Frontend updates on React/TypeScript changes
5. ✅ All services remain healthy after reload
6. ✅ No errors in logs
7. ✅ Performance is acceptable

## Next Steps

After successful testing:

1. Document any issues found
2. Update configuration if needed
3. Proceed with development using hot reload
4. Monitor logs during development
5. Report any bugs or improvements

## Related Documentation

- [Docker Hot Reload Guide](docker-hot-reload.md) - Complete hot reload documentation
- [Docker Hot Reload Quick Reference](docker-hot-reload-quick-reference.md) - Command cheat sheet
- [Docker Hot Reload Implementation Summary](docker-hot-reload-implementation-summary.md) - Implementation details
- [Deployment Documentation](10-deployment.md) - Docker deployment guide

