#!/bin/bash
# Run system audit

set -e

echo "Running system audit..."
echo ""

# Create audit log directory
mkdir -p logs/audit
AUDIT_LOG="logs/audit/audit_$(date +%Y%m%d_%H%M%S).log"

# Check Python formatting
echo "Checking Python code formatting..."
cd backend
if command -v black &> /dev/null; then
    black --check . >> ../$AUDIT_LOG 2>&1 || echo "  ⚠ Backend formatting issues found"
else
    echo "  ⚠ black not installed, skipping format check"
fi
cd ..

cd agent
if command -v black &> /dev/null; then
    black --check . >> ../$AUDIT_LOG 2>&1 || echo "  ⚠ Agent formatting issues found"
else
    echo "  ⚠ black not installed, skipping format check"
fi
cd ..

# Check health
echo "Checking service health..."
if command -v curl &> /dev/null; then
    curl -s http://localhost:8000/api/v1/health >> $AUDIT_LOG 2>&1 || echo "  ⚠ Backend health check failed"
fi

# Check logs for errors
echo "Checking logs for errors..."
grep -r "ERROR\|WARN" logs/*.log 2>/dev/null | head -20 >> $AUDIT_LOG 2>&1 || echo "  ✓ No errors found in logs"

echo ""
echo "Audit complete. Results saved to $AUDIT_LOG"

