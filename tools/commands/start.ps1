# Start all JackSparrow services (PowerShell)

Write-Host "Starting JackSparrow Trading Agent..." -ForegroundColor Green
Write-Host ""

# Create logs directory
New-Item -ItemType Directory -Force -Path logs | Out-Null

# Start Backend
Write-Host "Starting Backend (FastAPI)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; if (-not (Test-Path venv)) { python -m venv venv }; .\venv\Scripts\Activate.ps1; pip install -q -r requirements.txt; uvicorn api.main:app --host 0.0.0.0 --port 8000" -WindowStyle Normal

# Start Agent
Write-Host "Starting Agent..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd agent; if (-not (Test-Path venv)) { python -m venv venv }; .\venv\Scripts\Activate.ps1; pip install -q -r requirements.txt; python -m agent.core.intelligent_agent" -WindowStyle Normal

# Start Frontend
Write-Host "Starting Frontend (Next.js)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; if (-not (Test-Path node_modules)) { npm install }; npm run dev" -WindowStyle Normal

Write-Host ""
Write-Host "All services started successfully!" -ForegroundColor Green
Write-Host "Backend: http://localhost:8000" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Logs are in the logs/ directory" -ForegroundColor Gray

