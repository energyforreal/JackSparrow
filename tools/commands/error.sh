#!/bin/bash
# Quick error diagnostic

echo "JackSparrow Error Diagnostics"
echo "=============================="
echo ""

# Create error log directory
mkdir -p logs/error
ERROR_LOG="logs/error/summary_$(date +%Y%m%d_%H%M%S).log"

# Check service status
echo "Service Status:"
if [ -f logs/backend.pid ]; then
    PID=$(cat logs/backend.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "  ✓ Backend running (PID: $PID)" | tee -a $ERROR_LOG
    else
        echo "  ✗ Backend not running" | tee -a $ERROR_LOG
    fi
else
    echo "  ✗ Backend PID file not found" | tee -a $ERROR_LOG
fi

if [ -f logs/agent.pid ]; then
    PID=$(cat logs/agent.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "  ✓ Agent running (PID: $PID)" | tee -a $ERROR_LOG
    else
        echo "  ✗ Agent not running" | tee -a $ERROR_LOG
    fi
else
    echo "  ✗ Agent PID file not found" | tee -a $ERROR_LOG
fi

# Check recent errors
echo ""
echo "Recent Errors (last 20 lines):"
tail -20 logs/*.log 2>/dev/null | grep -i "error\|exception\|traceback" | head -20 | tee -a $ERROR_LOG || echo "  No errors found" | tee -a $ERROR_LOG

echo ""
echo "Diagnostics saved to $ERROR_LOG"

