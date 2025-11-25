# Windows Setup Guide for JackSparrow Trading Agent

This guide provides Windows-specific instructions for setting up the JackSparrow Trading Agent locally without Docker.

## Prerequisites

### 1. Python 3.11+

**Installation Options:**

**Option A: Official Installer (Recommended)**
1. Download Python 3.11+ from https://www.python.org/downloads/windows/
2. Run the installer
3. **Important**: Check "Add Python to PATH" during installation
4. Verify installation:
   ```powershell
   python --version
   ```

**Option B: Using Chocolatey**
```powershell
choco install python311
```

**Option C: Using Windows Store**
1. Open Microsoft Store
2. Search for "Python 3.11"
3. Install Python 3.11

**Verification:**
```powershell
python --version
# Should show: Python 3.11.x or higher
```

### 2. Node.js 18+

**Installation Options:**

**Option A: Official Installer (Recommended)**
1. Download Node.js 18+ from https://nodejs.org/
2. Run the installer (includes npm)
3. Verify installation:
   ```powershell
   node --version
   npm --version
   ```

**Option B: Using Chocolatey**
```powershell
choco install nodejs-lts
```

**Verification:**
```powershell
node --version
# Should show: v18.x.x or higher
npm --version
```

### 3. PostgreSQL 15+ with TimescaleDB

**Installation Steps:**

1. **Download PostgreSQL:**
   - Visit https://www.postgresql.org/download/windows/
   - Download PostgreSQL 15+ installer
   - Run the installer

2. **During Installation:**
   - Choose installation directory (default is fine)
   - Set a password for the `postgres` superuser (remember this!)
   - Choose port (default 5432 is fine)
   - Select components: PostgreSQL Server, pgAdmin 4, Command Line Tools

3. **Install TimescaleDB Extension:**
   - Download TimescaleDB for Windows from https://docs.timescale.com/install/latest/self-hosted/installation-windows/
   - Or use pre-built binaries: https://github.com/timescale/timescaledb/releases
   - Extract and copy DLL files to PostgreSQL installation directory
   - Enable extension in PostgreSQL:
     ```sql
     CREATE EXTENSION IF NOT EXISTS timescaledb;
     ```

4. **Start PostgreSQL Service:**
   ```powershell
   # As Administrator
   net start postgresql-x64-15
   # Or find your service name:
   Get-Service postgresql*
   ```

5. **Verify Installation:**
   ```powershell
   psql --version
   # Connect to PostgreSQL:
   psql -U postgres
   ```

**Alternative: Using Chocolatey**
```powershell
choco install postgresql15
# TimescaleDB must be installed separately
```

### 4. Redis 7.0+

**Installation Options:**

**Option A: Windows Port (Recommended for Development)**
1. Download Redis for Windows from:
   - https://github.com/microsoftarchive/redis/releases
   - Or https://github.com/tporadowski/redis/releases (more recent)
2. Extract ZIP file
3. Run `redis-server.exe` from extracted folder
4. Keep the window open (or install as service)

**Option B: Using WSL2 (Linux Subsystem)**
```powershell
# Install WSL2
wsl --install
# Then install Redis in WSL:
wsl
sudo apt update
sudo apt install redis-server
sudo service redis-server start
```

**Option C: Using Chocolatey**
```powershell
choco install redis-64
```

**Start Redis:**
```powershell
# Navigate to Redis directory
cd C:\path\to\redis
.\redis-server.exe

# Or if installed as service:
net start redis
```

**Verify Redis:**
```powershell
redis-cli ping
# Should return: PONG
```

## Project Setup

### 1. Clone Repository

```powershell
git clone https://github.com/energyforreal/JackSparrow
cd JackSparrow
```

### 2. Create .env File

```powershell
# Copy example (if exists)
Copy-Item .env.example .env

# Or create manually
New-Item .env
```

**Edit `.env` file with required variables:**

```env
# Database (REQUIRED)
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/trading_agent

# Redis (default)
REDIS_URL=redis://localhost:6379

# Delta Exchange (REQUIRED - Paper Trading)
DELTA_EXCHANGE_API_KEY=your_api_key_here
DELTA_EXCHANGE_API_SECRET=your_api_secret_here
DELTA_EXCHANGE_BASE_URL=https://api.india.delta.exchange

# Security (REQUIRED)
JWT_SECRET_KEY=your_jwt_secret_minimum_32_characters_long
API_KEY=your_api_key_minimum_32_characters_long

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### 3. Validate Environment

```powershell
python scripts/validate-env.py
```

This will check:
- All required variables are present
- Variable formats are correct
- Security keys meet minimum requirements

### 4. Validate Prerequisites

```powershell
python tools/commands/validate-prerequisites.py
```

This will check:
- Python version
- Node.js version
- PostgreSQL accessibility
- Redis accessibility
- Port availability

### 5. Initialize Database

```powershell
python scripts/setup_db.py
```

This creates:
- TimescaleDB extension
- All required tables
- Hypertables for time-series data
- Indexes

### 6. Install Dependencies

**Backend:**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Agent:**
```powershell
cd ..\agent
python -m venv venv
.\venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Note**: ML libraries (TensorFlow, PyTorch) may take time to install on Windows. If you encounter issues:
- Ensure Visual C++ Redistributable is installed
- Consider using CPU-only versions for development

**Frontend:**
```powershell
cd ..\frontend
npm install
```

## Starting Services

### Option 1: Parallel Startup (Recommended)

```powershell
# From project root
python tools\commands\start_parallel.py

# Or directly:
python tools/commands/start_parallel.py
```

This starts all services simultaneously with real-time log streaming.

### Option 2: Manual Startup (Separate Terminals)

**Terminal 1 - Backend:**
```powershell
cd backend
.\venv\Scripts\activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 - Agent:**
```powershell
cd agent
.\venv\Scripts\activate
python -m agent.core.intelligent_agent
```

**Terminal 3 - Frontend:**
```powershell
cd frontend
npm run dev
```

## Windows-Specific Issues and Solutions

### Issue 1: Python Not Found

**Problem**: `python` command not recognized

**Solution**:
1. Reinstall Python with "Add to PATH" checked
2. Or manually add to PATH:
   ```powershell
   # Find Python installation
   where.exe python
   # Add to PATH in System Environment Variables
   ```

### Issue 2: Virtual Environment Activation Fails

**Problem**: `.\venv\Scripts\activate` doesn't work

**Solution**:
```powershell
# Use full path or:
.\venv\Scripts\Activate.ps1

# If execution policy error:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue 3: PostgreSQL Service Won't Start

**Problem**: PostgreSQL service fails to start

**Solution**:
```powershell
# Check service status
Get-Service postgresql*

# Check logs
Get-Content "C:\Program Files\PostgreSQL\15\data\log\*.log" -Tail 50

# Try starting manually
net start postgresql-x64-15

# If port conflict:
# Edit postgresql.conf and change port
```

### Issue 4: Redis Connection Refused

**Problem**: Cannot connect to Redis

**Solution**:
1. Ensure Redis server is running:
   ```powershell
   # Check if running
   Get-Process redis-server -ErrorAction SilentlyContinue
   
   # Start Redis
   cd C:\path\to\redis
   .\redis-server.exe
   ```

2. Check firewall settings
3. Verify port 6379 is not blocked

### Issue 5: Port Already in Use

**Problem**: Port 8000, 3000, or 8001 already in use

**Solution**:
```powershell
# Find process using port
netstat -ano | findstr :8000

# Kill process (replace PID)
taskkill /PID <PID> /F

# Or change port in .env file
```

### Issue 6: ML Libraries Installation Fails

**Problem**: TensorFlow/PyTorch installation fails

**Solution**:
1. Install Visual C++ Redistributable:
   - Download from Microsoft
   - Install both x64 and x86 versions

2. Use CPU-only versions:
   ```powershell
   pip install tensorflow-cpu
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```

3. Consider using conda:
   ```powershell
   conda install tensorflow pytorch
   ```

### Issue 7: Path Length Issues

**Problem**: Path too long errors

**Solution**:
1. Enable long paths in Windows:
   ```powershell
   # As Administrator
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   ```

2. Or move project to shorter path (e.g., `C:\JS\`)

### Issue 8: npm Install Fails

**Problem**: npm install errors or timeouts

**Solution**:
```powershell
# Clear npm cache
npm cache clean --force

# Use different registry (if needed)
npm config set registry https://registry.npmjs.org/

# Increase timeout
npm config set fetch-timeout 600000

# Retry installation
npm install
```

## Verification Checklist

After setup, verify everything works:

- [ ] Python 3.11+ installed and in PATH
- [ ] Node.js 18+ installed and in PATH
- [ ] PostgreSQL 15+ running and accessible
- [ ] Redis running and accessible
- [ ] `.env` file created with all required variables
- [ ] Environment validation passes: `python scripts/validate-env.py`
- [ ] Prerequisites validation passes: `python tools/commands/validate-prerequisites.py`
- [ ] Database initialized: `python scripts/setup_db.py`
- [ ] Backend dependencies installed
- [ ] Agent dependencies installed
- [ ] Frontend dependencies installed
- [ ] All services start successfully

## Quick Reference Commands

```powershell
# Validate environment
python scripts/validate-env.py

# Validate prerequisites
python tools/commands/validate-prerequisites.py

# Start all services
python tools\commands\start_parallel.py

# Stop all services
# Stop services: Press Ctrl+C in the terminal running services

# Restart services
.\tools\commands\restart.ps1

# Check for errors
.\tools\commands\error.ps1

# Run audit
.\tools\commands\audit.ps1
```

## Getting Help

If you encounter issues:

1. Run validation scripts first:
   ```powershell
   python scripts/validate-env.py
   python tools/commands/validate-prerequisites.py
   ```

2. Check service logs in `logs/` directory

3. See [Troubleshooting Guide](troubleshooting-local-startup.md)

4. Review [Build Guide](11-build-guide.md)

5. Check [Deployment Documentation](10-deployment.md)

## Next Steps

After successful setup:

1. Configure Delta Exchange API keys in `.env`
2. Upload ML models (optional)
3. Start trading agent
4. Monitor via dashboard at http://localhost:3000

See [Build Guide](11-build-guide.md) for complete setup instructions.

