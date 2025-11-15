#!/bin/bash
# Start all JackSparrow services

set -e

echo "Starting JackSparrow Trading Agent..."
echo ""

# Create logs directory
mkdir -p logs

# Start Backend
echo "Starting Backend (FastAPI)..."
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "Backend started (PID: $BACKEND_PID)"

# Start Agent
echo "Starting Agent..."
cd agent
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
python -m agent.core.intelligent_agent > ../logs/agent.log 2>&1 &
AGENT_PID=$!
cd ..
echo "Agent started (PID: $AGENT_PID)"

# Start Frontend
echo "Starting Frontend (Next.js)..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "Frontend started (PID: $FRONTEND_PID)"

# Save PIDs
echo "$BACKEND_PID" > logs/backend.pid
echo "$AGENT_PID" > logs/agent.pid
echo "$FRONTEND_PID" > logs/frontend.pid

echo ""
echo "All services started successfully!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "Logs are in the logs/ directory"
echo "Use 'make stop' to stop all services"

