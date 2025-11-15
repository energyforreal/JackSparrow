#!/bin/bash
# Restart all JackSparrow services

set -e

echo "Restarting JackSparrow Trading Agent..."
echo ""

# Stop services
if [ -f logs/backend.pid ]; then
    kill $(cat logs/backend.pid) 2>/dev/null || true
    rm logs/backend.pid
fi

if [ -f logs/agent.pid ]; then
    kill $(cat logs/agent.pid) 2>/dev/null || true
    rm logs/agent.pid
fi

if [ -f logs/frontend.pid ]; then
    kill $(cat logs/frontend.pid) 2>/dev/null || true
    rm logs/frontend.pid
fi

echo "Services stopped"
sleep 2

# Start services
bash tools/commands/start.sh

