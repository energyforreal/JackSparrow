# Troubleshooting Local Startup Issues

This guide helps diagnose and fix common issues when starting the JackSparrow Trading Agent locally (without Docker).

## Quick Diagnostic Commands

Before troubleshooting, run these validation commands:

```bash
# Validate environment variables
python scripts/validate-env.py

# Validate prerequisites
python tools/commands/validate-prerequisites.py

# Check service logs
python tools/commands/error.sh
# Windows PowerShell: .\tools\commands\error.ps1
```

## Common Issues and Solutions

### 1. Configuration Errors

#### Issue: "Failed to load backend/agent configuration"

**Symptoms:**
- Services fail to start immediately
- Error message about missing environment variables
- Pydantic validation errors

**Diagnosis:**
```bash
python scripts/validate-env.py
```

**Solutions:**

1. **Check .env file exists:**
   ```bash
   ls -la .env  # Linux/macOS
   dir .env     # Windows
   ```

2. **Verify required variables are set:**
   - `DATABASE_URL` - PostgreSQL connection string
   - `DELTA_EXCHANGE_API_KEY` - Delta Exchange API key
   - `DELTA_EXCHANGE_API_SECRET` - Delta Exchange API secret
   - `JWT_SECRET_KEY` - JWT secret (backend only)
   - `API_KEY` - API key (backend only)

3. **Check variable formats:**
   - `DATABASE_URL` should be: `postgresql://user:pass@host:port/dbname`
   - URLs should include scheme (`http://` or `https://`)
   - No trailing spaces or quotes (unless quoted in file)

4. **Common mistakes:**
   - Empty values: `DATABASE_URL=` (should have value)
   - Missing quotes for values with special characters
   - Wrong variable names (typos)
   - Using `localhost` when should use `127.0.0.1` or actual hostname

**Example Fix:**
```env
# Wrong
DATABASE_URL=postgresql://user@localhost/db

# Correct
DATABASE_URL=postgresql://user:password@localhost:5432/trading_agent
```

#### Issue: "JWT_SECRET_KEY is set to default/placeholder value"

**Solution:**
Generate a secure random key:
```bash
# Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# OpenSSL
openssl rand -hex 32

# Then update .env:
JWT_SECRET_KEY=your_generated_key_here
```

### 2. Database Connection Issues

#### Issue: "PostgreSQL is not accessible"

**Symptoms:**
- Prerequisite check fails
- Database connection errors in logs
- `psql` command fails

**Diagnosis:**
```bash
# Check if PostgreSQL is running
pg_isready  # Linux/macOS
# Or
psql -U postgres -c "SELECT 1;"  # Test connection

# Windows
Get-Service postgresql*  # PowerShell
```

**Solutions:**

1. **Start PostgreSQL service:**
   ```bash
   # Linux
   sudo systemctl start postgresql
   
   # macOS
   brew services start postgresql@15
   
   # Windows
   net start postgresql-x64-15
   # Or
   Get-Service postgresql* | Start-Service
   ```

2. **Verify DATABASE_URL:**
   ```bash
   # Test connection
   psql "postgresql://user:pass@localhost:5432/dbname" -c "SELECT 1;"
   ```

3. **Check PostgreSQL is listening:**
   ```bash
   # Linux/macOS
   netstat -an | grep 5432
   lsof -i :5432
   
   # Windows
   netstat -ano | findstr :5432
   ```

4. **Firewall issues:**
   - Ensure PostgreSQL port (5432) is not blocked
   - Check local firewall settings

5. **Authentication issues:**
   - Verify username/password in DATABASE_URL
   - Check `pg_hba.conf` for authentication method
   - For local dev, may need `trust` or `md5` authentication

#### Issue: "Database tables missing"

**Symptoms:**
- Services start but fail on first database operation
- SQL errors about missing tables

**Solution:**
```bash
python scripts/setup_db.py
```

This creates all required tables and enables TimescaleDB extension.

### 3. Redis Connection Issues

#### Issue: "Redis is not accessible"

**Symptoms:**
- Prerequisite check fails
- Redis connection errors
- Agent/backend communication fails

**Diagnosis:**
```bash
redis-cli ping
# Should return: PONG
```

**Solutions:**

1. **Start Redis:**
   ```bash
   # Linux
   sudo systemctl start redis
   
   # macOS
   brew services start redis
   
   # Windows
   redis-server.exe
   # Or if installed as service
   net start redis
   ```

2. **Verify REDIS_URL:**
   ```bash
   # Default: redis://localhost:6379
   # Test connection
   redis-cli -h localhost -p 6379 ping
   ```

3. **Check Redis is listening:**
   ```bash
   # Linux/macOS
   netstat -an | grep 6379
   
   # Windows
   netstat -ano | findstr :6379
   ```

4. **Windows-specific:**
   - Ensure Redis server window is open (if running manually)
   - Or install as Windows service
   - Consider using WSL2 for Redis if Windows port has issues

### 4. Python Environment Issues

#### Issue: "Python version X.X detected. Python 3.11+ is required"

**Solution:**
1. Install Python 3.11+:
   ```bash
   # Check current version
   python --version
   
   # Install Python 3.11+
   # See platform-specific installation guides
   ```

2. Use Python 3.11 explicitly:
   ```bash
   python3.11 --version
   python3.11 -m venv venv
   ```

#### Issue: "Module not found" or Import Errors

**Symptoms:**
- Services crash on import
- Missing module errors

**Solutions:**

1. **Verify virtual environment is activated:**
   ```bash
   # Check which Python is used
   which python  # Linux/macOS
   where python   # Windows
   # Should show venv path
   ```

2. **Reinstall dependencies:**
   ```bash
   cd backend  # or agent
   source venv/bin/activate  # Linux/macOS
   .\venv\Scripts\activate   # Windows
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Check requirements.txt exists:**
   ```bash
   ls requirements.txt
   ```

4. **Windows-specific ML library issues:**
   - Install Visual C++ Redistributable
   - Use CPU-only versions: `pip install tensorflow-cpu`
   - Consider using conda for ML libraries

#### Issue: Virtual Environment Not Created

**Solution:**
```bash
cd backend  # or agent
python -m venv venv
source venv/bin/activate  # Linux/macOS
.\venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 5. Node.js/Frontend Issues

#### Issue: "Node.js/npm not found in PATH"

**Solutions:**

1. **Install Node.js 18+:**
   - Download from https://nodejs.org/
   - Ensure npm is included

2. **Verify installation:**
   ```bash
   node --version
   npm --version
   ```

3. **Add to PATH (if needed):**
   - Windows: Add Node.js installation directory to System PATH
   - Linux/macOS: Usually handled by installer

#### Issue: Frontend Dependencies Not Installed

**Symptoms:**
- Frontend fails to start
- Missing `node_modules` directory

**Solutions:**

1. **Install dependencies:**
   ```bash
   cd frontend
   npm install
   ```

2. **Clear cache and retry:**
   ```bash
   rm -rf node_modules package-lock.json
   npm cache clean --force
   npm install
   ```

3. **Check npm version:**
   ```bash
   npm --version
   # Update if needed
   npm install -g npm@latest
   ```

#### Issue: Frontend Build Errors

**Solutions:**

1. **Clear Next.js cache:**
   ```bash
   cd frontend
   rm -rf .next
   npm run build
   ```

2. **Check Node.js version compatibility:**
   - Ensure Node.js 18+ is used
   - Some packages may require specific Node versions

### 6. Port Conflicts

#### Issue: "Port XXXX already in use"

**Symptoms:**
- Services cannot bind to ports
- Address already in use errors

**Diagnosis:**
```bash
# Linux/macOS
lsof -i :8000
netstat -an | grep 8000

# Windows
netstat -ano | findstr :8000
```

**Solutions:**

1. **Find and kill process:**
   ```bash
   # Linux/macOS
   kill -9 <PID>
   
   # Windows
   taskkill /PID <PID> /F
   ```

2. **Change port in configuration:**
   ```env
   # In .env file
   BACKEND_PORT=8001  # Use different port
   ```

3. **Stop previous instances:**
   ```bash
   # Stop services: Press Ctrl+C in the terminal running services
   # Or manually kill processes
   ```

### 7. Service Startup Failures

#### Issue: Services Start But Immediately Exit

**Symptoms:**
- Services appear to start but exit immediately
- No error messages visible

**Diagnosis:**

1. **Check service logs:**
   ```bash
   # Check log files
   cat logs/backend.log
   cat logs/agent.log
   cat logs/frontend.log
   
   # Or use error diagnostic script
   python tools/commands/error.sh
   # Windows PowerShell:
   .\tools\commands\error.ps1
   ```

2. **Run services manually:**
   ```bash
   # Backend
   cd backend
   source venv/bin/activate
   uvicorn api.main:app --port 8000
   
   # Agent
   cd agent
   source venv/bin/activate
   python -m agent.core.intelligent_agent
   
   # Frontend
   cd frontend
   npm run dev
   ```

**Common Causes:**
- Configuration errors (check .env)
- Missing dependencies
- Database/Redis not accessible
- Port conflicts
- Import errors

#### Issue: Services Start But Don't Communicate

**Symptoms:**
- Services start successfully
- But frontend can't connect to backend
- Agent can't communicate with backend

**Solutions:**

1. **Verify URLs in .env:**
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
   FEATURE_SERVER_URL=http://localhost:8001
   ```

2. **Check CORS settings:**
   - Ensure `CORS_ORIGINS` includes frontend URL
   - Default: `http://localhost:3000`

3. **Verify ports are correct:**
   - Backend: 8000
   - Frontend: 3000
   - Agent Feature Server: 8001

4. **Check firewall:**
   - Ensure localhost connections are allowed
   - Check if antivirus is blocking connections

### 8. Windows-Specific Issues

#### Issue: PowerShell Execution Policy

**Symptoms:**
- Scripts fail to run
- "execution of scripts is disabled" error

**Solution:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

#### Issue: Path Length Limitations

**Symptoms:**
- File path too long errors
- npm install failures

**Solution:**
1. Enable long paths in Windows (requires admin):
   ```powershell
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   ```

2. Or move project to shorter path (e.g., `C:\JS\`)

#### Issue: Virtual Environment Activation Fails

**Solution:**
```powershell
# Use full path
.\venv\Scripts\Activate.ps1

# Or use cmd instead of PowerShell
cmd
venv\Scripts\activate.bat
```

### 9. ML Model Issues

#### Issue: "Model file not found"

**Symptoms:**
- Agent starts but can't find models
- Model discovery fails

**Solutions:**

1. **Check MODEL_DIR (recommended):**
   ```env
   MODEL_DIR=./agent/model_storage
   ```
   
   Or use MODEL_PATH for specific model:
   ```env
   MODEL_PATH=agent/model_storage/xgboost/xgboost_BTCUSD_15m.pkl
   ```

2. **Verify model file exists:**
   ```bash
   ls agent/model_storage/xgboost/*.pkl
   ```

3. **Check MODEL_DIR:**
   ```env
   MODEL_DIR=./agent/model_storage
   ```

4. **Agent can start without models:**
   - Set `AGENT_START_MODE=MONITORING`
   - Models are optional for initial startup

## Diagnostic Workflow

When troubleshooting, follow this systematic approach:

1. **Run Validation Scripts:**
   ```bash
   python scripts/validate-env.py
   python tools/commands/validate-prerequisites.py
   ```

2. **Check Service Logs:**
   ```bash
   python tools/commands/error.sh
   # Windows PowerShell: .\tools\commands\error.ps1
   # Or manually
   tail -f logs/backend.log
   tail -f logs/agent.log
   tail -f logs/frontend.log
   ```

3. **Test Individual Components:**
   - Test database connection: `psql $DATABASE_URL -c "SELECT 1;"`
   - Test Redis: `redis-cli ping`
   - Test backend: `curl http://localhost:8000/api/v1/health`
   - Test frontend: Open http://localhost:3000

4. **Verify Prerequisites:**
   - Python version: `python --version`
   - Node.js version: `node --version`
   - PostgreSQL: `psql --version`
   - Redis: `redis-cli --version`

5. **Check Configuration:**
   - Verify .env file exists and has all required variables
   - Check variable formats are correct
   - Ensure no typos in variable names

6. **Review Error Messages:**
   - Read full error messages (not just first line)
   - Check stack traces for root cause
   - Look for specific variable names or file paths

## Getting Additional Help

If issues persist:

1. **Collect Diagnostic Information:**
   ```bash
   # Run all validations
   python scripts/validate-env.py > env-validation.txt
   python tools/commands/validate-prerequisites.py > prerequisites.txt
   python tools/commands/error.sh
   # Windows PowerShell: .\tools\commands\error.ps1 > errors.txt
   
   # System information
   python --version > system-info.txt
   node --version >> system-info.txt
   ```

2. **Check Documentation:**
   - [Build Guide](11-build-guide.md)
   - [Windows Setup Guide](windows-setup-guide.md)
   - [Deployment Documentation](10-deployment.md)

3. **Review Logs:**
   - Check `logs/` directory for detailed error messages
   - Look for patterns or repeated errors
   - Check timestamps to correlate issues

4. **Community Support:**
   - GitHub Issues: https://github.com/energyforreal/JackSparrow/issues
   - Include diagnostic output and error messages

## Prevention Tips

To avoid common issues:

1. **Always run validation before starting:**
   ```bash
   python scripts/validate-env.py
   python tools/commands/validate-prerequisites.py
   ```

2. **Keep prerequisites updated:**
   - Python 3.11+
   - Node.js 18+
   - PostgreSQL 15+
   - Redis 7.0+

3. **Use virtual environments:**
   - Never install dependencies globally
   - Use separate venvs for backend and agent

4. **Document your setup:**
   - Note any custom configurations
   - Keep track of environment-specific settings

5. **Regular maintenance:**
   - Update dependencies periodically
   - Clear caches if issues arise
   - Keep logs directory clean

## Quick Reference

```bash
# Validation
python scripts/validate-env.py
python tools/commands/validate-prerequisites.py

# Service management
# Start services
python tools/commands/start_parallel.py
# Linux/macOS: ./tools/commands/start.sh
# Windows: .\tools\commands\start.ps1

# Stop services: Press Ctrl+C in the terminal running services

# Restart services
# Linux/macOS: ./tools/commands/restart.sh
# Windows: .\tools\commands\restart.ps1

# Error diagnostics
python tools/commands/error.sh
# Windows PowerShell: .\tools\commands\error.ps1

# Database
python scripts/setup_db.py
psql $DATABASE_URL -c "SELECT 1;"

# Dependencies
pip install -r requirements.txt  # Python
npm install                      # Node.js

# Logs
tail -f logs/backend.log
tail -f logs/agent.log
tail -f logs/frontend.log
```

