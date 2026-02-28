# Troubleshooting Guide

Common issues and solutions for the JackSparrow Trading Agent system.

> **Note**: All log paths in this guide (for example `logs/backend.log` or `logs/agent.log`) refer to **runtime log files** under the `logs/` directory. These files are generated and rotated per run and are intentionally ignored by git—they will not appear in the repository.

## Unicode Encoding Issues

### Problem: UnicodeEncodeError on Windows

**Symptoms:**
- `UnicodeEncodeError: 'charmap' codec can't encode character`
- Scripts fail with encoding errors when displaying Unicode symbols (⚠, ✓, ✗, etc.)
- Unicode characters don't display correctly

**Solution:**
The startup scripts now use a robust Unicode-safe approach:

1. **Automatic Symbol Fallback**: All scripts use the `get_safe_symbol()` function which:
   - Detects the actual stdout encoding (often `cp1252` on Windows)
   - Tests if Unicode symbols can be encoded
   - Automatically falls back to ASCII equivalents (`!` instead of `⚠`, `OK` instead of `✓`, `X` instead of `✗`)
   - Works transparently without user intervention

2. **Enhanced Print Function**: The `_flushed_print()` function handles encoding errors gracefully:
   - Catches `UnicodeEncodeError` exceptions
   - Automatically retries with error handling (`errors='replace'`)
   - Falls back to ASCII-only output if needed

3. **Implementation Details**:
   ```python
   # Example usage in scripts:
   warning_symbol = get_safe_symbol("⚠", "!")
   print(f"{Colors.YELLOW}{warning_symbol} Warning message{Colors.RESET}")
   ```

4. **Verify encoding configuration**:
   ```bash
   python tools/commands/test-encoding.py
   ```

**Fixed Scripts:**
- `tools/commands/start_parallel.py` - Main startup script with comprehensive Unicode handling
- `tools/commands/validate-prerequisites.py` - Prerequisite validation with safe symbols
- `tools/commands/utils.py` - Shared utilities with Unicode-safe functions

**Note**: On Windows, you may see ASCII symbols (`OK`, `!`, `X`) instead of Unicode symbols (`✓`, `⚠`, `✗`). This is intentional and ensures scripts work reliably across all Windows configurations.

### Problem: Unicode in Log Files

**Symptoms:**
- Log files contain garbled characters
- Unicode characters are replaced with `?`

**Solution:**
- Ensure log files are opened with UTF-8 encoding:
  ```python
  open(log_file, 'w', encoding='utf-8', errors='replace')
  ```

## Event Deserialization Issues

### Problem: Events Appear Empty

**Symptoms:**
- `event_json_preview={}` in logs
- Events not being processed
- Empty event dictionaries

**Solution:**
1. Check Redis Stream message format
2. Verify event serialization before publishing
3. Check event deserialization logic handles different key formats

**Debug:**
```python
# Enable debug logging
logger.debug("event_message_received", ...)
```

### Problem: Event Processing Fails

**Symptoms:**
- Events not acknowledged
- Events stuck in Redis Stream
- Handler errors

**Solution:**
1. Check handler registration
2. Verify event type matches handler
3. Review error logs for handler exceptions

## Model Loading Issues

### Problem: Models Not Loading

**Symptoms:**
- `model_discovery_no_models` warning
- Models not discovered
- `detected_type=unknown`

**Solution:**
1. Check model file naming convention
2. Verify model files are in correct directory
3. Check MODEL_DIR and MODEL_PATH environment variables

**Debug:**
```bash
# Check model discovery logs
grep "model_discovery" logs/agent.log
```

### Problem: Corrupted Model Files

**Symptoms:**
- `invalid load key` errors
- `UnpicklingError` exceptions
- Model loading fails

**Solution:**
1. Remove corrupted model files
2. Regenerate models if possible
3. Check model file integrity

**Prevention:**
- Validate models before saving
- Use version control for model files
- Regular backups

### Problem: XGBoost Compatibility Warnings

**Symptoms:**
- Warnings about older XGBoost version
- Models load but with warnings

**Solution:**
1. Re-export models using current XGBoost version:
   ```python
   from xgboost import Booster
   booster = Booster()
   booster.load_model('old_model.json')
   booster.save_model('new_model.json')
   ```

2. Warnings are non-blocking - models still work

## Prerequisite Validation Issues

### Problem: Node.js Version Format Warning

**Symptoms:**
- Warning: "Node.js version format unexpected: 22.17.0"
- Version parsing fails for valid Node.js versions
- Prerequisite check shows warnings for correctly installed Node.js

**Solution:**
The `validate-prerequisites.py` script now includes improved version parsing:
- Handles all standard Node.js version formats (e.g., `22.17.0`, `v22.17.0`, `22.17`)
- Extracts major version number correctly
- Only warns if version format is truly unexpected
- Validates that Node.js 18+ is installed

**Fixed**: The script now correctly parses Node.js version `22.17.0` and higher without warnings.

## Service Startup Issues

### Problem: Services Won't Start

**Symptoms:**
- Port already in use
- Import errors
- Configuration errors
- Unicode encoding errors during startup

**Solution:**
1. Check port availability:
   ```bash
   netstat -ano | findstr :8000  # Windows
   lsof -i :8000                 # Linux/Mac
   ```

2. Verify environment variables:
   ```bash
   python tools/commands/validate-prerequisites.py
   ```

3. Check logs for specific errors:
   ```bash
   tail -f logs/backend.log
   tail -f logs/agent.log
   ```

### Problem: Health Checks Fail

**Symptoms:**
- Health check script reports failures
- Services appear down but are running

**Solution:**
1. Verify service URLs are correct
2. Check firewall settings
3. Verify services are actually running:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

## Docker-Specific Runbooks

### Problem: A container is repeatedly restarting (crash loop) in Docker

**Symptoms:**
- `docker compose ps` shows a service constantly restarting
- `STATUS` column shows `Restarting (1)` or similar

**Solution:**
1. Inspect the service logs:
   ```bash
   docker compose logs --tail=100 backend   # or agent / frontend / postgres / redis
   ```
2. Look for configuration errors (bad `DATABASE_URL`, invalid API keys, missing environment variables).
3. If the error is configuration-related:
   - Fix the values in the root `.env` file.
   - Re-run `python scripts/docker_diagnostic.py` to confirm the new configuration is valid.
   - Restart the stack:
     ```bash
     docker compose up -d
     ```

### Problem: Agent running in Docker but no signals are visible in the UI

**Symptoms:**
- Frontend loads, but no trading signals or reasoning chains appear.
- Backend `/api/v1/health` shows `model_nodes: UNKNOWN` or `degraded`.

**Solution:**
1. Confirm models exist on the host:
   ```bash
   ls agent/model_storage
   ```
2. Run the model check from the host:
   ```bash
   python scripts/docker_diagnostic.py
   ```
   - Fix any warnings about missing model files or `MODEL_DIR`.
3. Inspect agent logs for model discovery and prediction pipeline:
   ```bash
   docker compose logs --tail=200 agent
   ```
   - Look for `model_discovery` entries and any `model_discovery_failed` or `model_nodes_discovery_result` events.
4. If necessary, copy valid model artefacts into `agent/model_storage/...` and restart only the agent:
   ```bash
   docker compose restart agent
   ```
5. Refresh the frontend and confirm that:
   - Backend `/api/v1/health` reports healthy `model_nodes`.
   - WebSocket data freshness indicators show recent updates.

## Test Failures

### Problem: Import Errors in Tests

**Symptoms:**
- `ModuleNotFoundError: No module named 'tools'`
- Tests fail to import modules

**Solution:**
1. Add project root to Python path:
   ```python
   sys.path.insert(0, str(project_root))
   ```

2. Run tests from project root:
   ```bash
   cd /path/to/project
   pytest tests/
   ```

### Problem: Async Test Failures

**Symptoms:**
- `RuntimeError: no running event loop`
- Async fixtures fail

**Solution:**
1. Ensure `pytest-asyncio` is installed
2. Use `@pytest.mark.asyncio` decorator
3. Use `@pytest_asyncio.fixture` for async fixtures

### Problem: Model Tests Fail

**Symptoms:**
- Model discovery tests fail
- Models not detected in tests

**Solution:**
1. Ensure XGBoost is installed
2. Check test model files are created correctly
3. Verify model registry methods exist

## Performance Issues

### Problem: Slow Startup

**Symptoms:**
- Services take long to start
- Health checks timeout

**Solution:**
1. Check database connection
2. Verify Redis is accessible
3. Review model loading time
4. Check for blocking operations

### Problem: High Memory Usage

**Symptoms:**
- Memory usage increases over time
- System becomes slow

**Solution:**
1. Check for memory leaks
2. Review model loading (unload unused models)
3. Monitor event bus message queue size
4. Restart services periodically

## Getting Help

### Logs

Check logs for detailed error information:
- `logs/backend.log` - Backend service logs
- `logs/agent.log` - Agent service logs
- `logs/frontend.log` - Frontend service logs

### Debug Mode

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Support

- Check project documentation
- Review error messages in logs
- Search for similar issues in codebase
- Create detailed bug report with logs

## Common Commands

### Check System Status
```bash
python tools/commands/health_check.py
```

### Validate Fixes
```bash
python tools/commands/validate-fixes.py
```

### Test Encoding
```bash
python tools/commands/test-encoding.py
```

### Run Tests
```bash
python tools/commands/run-fix-tests.py
```

### Monitor System
```bash
python tools/commands/monitor-system.py
```

