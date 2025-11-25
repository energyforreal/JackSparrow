# Validation Quick Reference

Quick reference guide for validating JackSparrow Trading Agent configuration and prerequisites.

## Quick Commands

```bash
# Validate everything (recommended before starting)
python scripts/validate-env.py && python tools/commands/validate-prerequisites.py

# Validate environment variables only
python scripts/validate-env.py

# Validate prerequisites only
python tools/commands/validate-prerequisites.py

# Check health of running services
python tools/commands/health_check.py
```

## What Gets Validated

### Environment Variables (`scripts/validate-env.py`)

**Required Variables:**
- `DATABASE_URL` - PostgreSQL connection string
- `DELTA_EXCHANGE_API_KEY` - Delta Exchange API key
- `DELTA_EXCHANGE_API_SECRET` - Delta Exchange API secret

**Backend-Specific Required:**
- `JWT_SECRET_KEY` - JWT secret (minimum 32 characters)
- `API_KEY` - API key (minimum 32 characters)

**Validations:**
- ✅ All required variables present
- ✅ DATABASE_URL format correct
- ✅ REDIS_URL format correct
- ✅ URL formats valid
- ✅ Security keys meet minimum length
- ✅ No placeholder/default values
- ✅ Model files exist (if MODEL_PATH specified)

### Prerequisites (`tools/commands/validate-prerequisites.py`)

**System Requirements:**
- ✅ Python 3.11+ installed
- ✅ Node.js 18+ installed
- ✅ PostgreSQL 15+ running and accessible
- ✅ Redis 7.0+ running and accessible
- ✅ Database schema initialized (tables exist)
- ✅ Service ports available (8000, 3000, 8001)

## Common Issues and Quick Fixes

### Issue: Missing Environment Variables

**Fix:**
```bash
# Check .env file exists
ls -la .env  # Linux/macOS
dir .env     # Windows

# Edit .env file
nano .env    # Linux/macOS
notepad .env # Windows
```

### Issue: PostgreSQL Not Running

**Fix:**
```bash
# Linux
sudo systemctl start postgresql

# macOS
brew services start postgresql@15

# Windows
net start postgresql-x64-15
```

### Issue: Redis Not Running

**Fix:**
```bash
# Linux
sudo systemctl start redis

# macOS
brew services start redis

# Windows
redis-server.exe
```

### Issue: Database Tables Missing

**Fix:**
```bash
python scripts/setup_db.py
```

### Issue: Invalid DATABASE_URL Format

**Correct Format:**
```env
DATABASE_URL=postgresql://username:password@localhost:5432/database_name
```

**Common Mistakes:**
- Missing `postgresql://` scheme
- Missing port number
- Missing database name
- Incorrect password encoding

## Validation Workflow

1. **Before First Start:**
   ```bash
   python scripts/validate-env.py && python tools/commands/validate-prerequisites.py
   ```

2. **If Validation Fails:**
   - Read error messages carefully
   - Fix issues in `.env` file
   - Start missing services (PostgreSQL, Redis)
   - Initialize database if needed: `python scripts/setup_db.py`
   - Re-run validation: `python scripts/validate-env.py && python tools/commands/validate-prerequisites.py`

3. **After Configuration Changes:**
   ```bash
   python scripts/validate-env.py && python tools/commands/validate-prerequisites.py
   ```

4. **Before Starting Services:**
   ```bash
   python scripts/validate-env.py && python tools/commands/validate-prerequisites.py
   python tools/commands/start_parallel.py
   ```

## Integration with Startup

The startup script (`python tools/commands/start_parallel.py`) automatically runs validation before starting services and health checks after:

```bash
python tools/commands/start_parallel.py
# Automatically runs:
# 1. python scripts/validate-env.py
# 2. python tools/commands/validate-prerequisites.py
# 3. Starts services only if validation passes
# 4. python tools/commands/health_check.py (after services start)
```

If validation fails during startup, services will not start and you'll see clear error messages.

## Health Checks

After services start, health checks verify:
- Backend health endpoint responds
- Agent is responding (via backend)
- Frontend is accessible
- Individual service status (database, redis, agent)

Run health checks independently:
```bash
python tools/commands/health_check.py
```

## Exit Codes

- `0` - All validations passed
- `1` - Validation failed (errors found)
- Warnings don't cause exit code 1, but should be reviewed

## Getting Help

If validation fails and you need help:

1. **Check Error Messages**: Read the full output for specific issues
2. **Review Documentation**:
   - [Build Guide](11-build-guide.md)
   - [Troubleshooting Guide](troubleshooting-local-startup.md)
   - [Windows Setup Guide](windows-setup-guide.md)
3. **Run Individual Validations**: Run scripts separately to isolate issues
4. **Check Logs**: Review service logs if services fail after validation

## Examples

### Successful Validation

```bash
$ python scripts/validate-env.py && python tools/commands/validate-prerequisites.py

======================================================================
Environment Variable Validation
======================================================================

✅ All environment variables validated successfully!

Checking Prerequisites...

✓ Python 3.12.10
✓ Node.js 22.17.0
✓ PostgreSQL accessible at localhost:5432
✓ Database schema validated (all tables exist)
✓ Redis accessible at localhost:6379

✅ All prerequisites validated successfully!
```

### Failed Validation

```bash
$ python scripts/validate-env.py && python tools/commands/validate-prerequisites.py

======================================================================
Environment Variable Validation
======================================================================

❌ ERRORS FOUND:
  Missing required environment variables:
  - DATABASE_URL: PostgreSQL connection URL (e.g., postgresql://user:pass@host:port/dbname)
  - DELTA_EXCHANGE_API_KEY: Delta Exchange API key

...

❌ PREREQUISITE CHECK FAILED

The following issues were found:
  ✗ PostgreSQL is not accessible at localhost:5432
  ✗ Redis is not accessible at localhost:6379

...
```

## See Also

- [Build Guide](11-build-guide.md) - Complete setup instructions
- [Troubleshooting Guide](troubleshooting-local-startup.md) - Detailed troubleshooting
- [Windows Setup Guide](windows-setup-guide.md) - Windows-specific instructions

