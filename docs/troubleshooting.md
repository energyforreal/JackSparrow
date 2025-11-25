# Troubleshooting Guide

Common issues and solutions for the JackSparrow Trading Agent system.

## Unicode Encoding Issues

### Problem: UnicodeEncodeError on Windows

**Symptoms:**
- `UnicodeEncodeError: 'charmap' codec can't encode character`
- Scripts fail with encoding errors
- Unicode characters don't display correctly

**Solution:**
1. Ensure scripts use UTF-8 encoding:
   ```python
   sys.stdout.reconfigure(encoding='utf-8')
   ```

2. Use ASCII-safe symbols on Windows:
   - Scripts automatically detect Windows and use `[OK]`, `[WARN]`, `[FAIL]` instead of Unicode symbols

3. Verify encoding configuration:
   ```bash
   python tools/commands/test-encoding.py
   ```

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

## Service Startup Issues

### Problem: Services Won't Start

**Symptoms:**
- Port already in use
- Import errors
- Configuration errors

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

