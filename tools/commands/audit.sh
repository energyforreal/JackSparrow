#!/bin/bash
# Run comprehensive system audit

set -e

echo "Running comprehensive system audit..."
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "❌ Python not found. Cannot run comprehensive audit."
    exit 1
fi

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check if comprehensive audit script exists
if [ ! -f "scripts/comprehensive_audit.py" ]; then
    echo "❌ Comprehensive audit script not found at scripts/comprehensive_audit.py"
    echo "Falling back to basic audit..."
    echo ""

    # Fallback to basic audit (original functionality)
    mkdir -p logs/audit
    AUDIT_LOG="logs/audit/audit_$(date +%Y%m%d_%H%M%S).log"

    echo "Audit started at $(date)" > $AUDIT_LOG
    echo "================================" >> $AUDIT_LOG
    echo "" >> $AUDIT_LOG

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
        fi
        cd ..
    fi

    echo "Basic audit complete. Results saved to $AUDIT_LOG"
    exit 0
fi

# Run comprehensive audit
echo "Executing comprehensive audit script..."
echo ""

# Parse command line arguments and pass them to the Python script
AUDIT_ARGS=""
if [ "$1" = "--verbose" ] || [ "$1" = "-v" ]; then
    AUDIT_ARGS="$AUDIT_ARGS --verbose"
fi
if [ "$1" = "--quick" ] || [ "$1" = "-q" ]; then
    AUDIT_ARGS="$AUDIT_ARGS --quick"
fi

$PYTHON_CMD scripts/comprehensive_audit.py $AUDIT_ARGS

echo ""
echo "Comprehensive audit complete!"

