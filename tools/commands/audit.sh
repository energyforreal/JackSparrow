#!/bin/bash
# Run system audit

set -e

echo "Running system audit..."
echo ""

# Create audit log directory
mkdir -p logs/audit
AUDIT_LOG="logs/audit/audit_$(date +%Y%m%d_%H%M%S).log"

# Initialize audit log
echo "Audit started at $(date)" > $AUDIT_LOG
echo "================================" >> $AUDIT_LOG
echo "" >> $AUDIT_LOG

# Check Python formatting
echo "Checking Python code formatting..."
if [ -d backend ]; then
    cd backend
    if command -v black &> /dev/null; then
        if black --check . >> ../$AUDIT_LOG 2>&1; then
            echo "  ✓ Backend formatting OK"
        else
            echo "  ⚠ Backend formatting issues found"
        fi
    else
        echo "  ⚠ black not installed, skipping format check"
        echo "black not installed" >> ../$AUDIT_LOG
    fi
    cd ..
else
    echo "  ⚠ Backend directory not found"
    echo "Backend directory not found" >> $AUDIT_LOG
fi

if [ -d agent ]; then
    cd agent
    if command -v black &> /dev/null; then
        if black --check . >> ../$AUDIT_LOG 2>&1; then
            echo "  ✓ Agent formatting OK"
        else
            echo "  ⚠ Agent formatting issues found"
        fi
    else
        echo "  ⚠ black not installed, skipping format check"
        echo "black not installed" >> ../$AUDIT_LOG
    fi
    cd ..
else
    echo "  ⚠ Agent directory not found"
    echo "Agent directory not found" >> $AUDIT_LOG
fi

# Check health
echo "Checking service health..."
if command -v curl &> /dev/null; then
    if curl -s -f http://localhost:8000/api/v1/health >> $AUDIT_LOG 2>&1; then
        echo "  ✓ Backend health check passed"
    else
        echo "  ⚠ Backend health check failed"
    fi
else
    echo "  ⚠ curl not installed, skipping health check"
    echo "curl not installed" >> $AUDIT_LOG
fi

# Check logs for errors
echo "Checking logs for errors..."
if [ -d logs ] && [ "$(find logs -name '*.log' -type f 2>/dev/null | wc -l)" -gt 0 ]; then
    ERROR_COUNT=$(grep -r "ERROR\|WARN" logs/*.log 2>/dev/null | wc -l || echo "0")
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "  ⚠ Found $ERROR_COUNT error/warning lines in logs"
        grep -r "ERROR\|WARN" logs/*.log 2>/dev/null | head -20 >> $AUDIT_LOG 2>&1 || true
    else
        echo "  ✓ No errors found in logs"
        echo "No errors found in logs" >> $AUDIT_LOG
    fi
else
    echo "  ⚠ No log files found"
    echo "No log files found" >> $AUDIT_LOG
fi

echo "" >> $AUDIT_LOG
echo "Audit completed at $(date)" >> $AUDIT_LOG

echo ""
echo "Audit complete. Results saved to $AUDIT_LOG"

