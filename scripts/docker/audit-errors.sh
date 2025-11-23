#!/bin/bash
# Docker error audit script for JackSparrow Trading Agent
# Scans all container logs for errors and generates a comprehensive report

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Parse arguments
HOURS=24
OUTPUT_DIR="logs/docker-audit"

while [[ $# -gt 0 ]]; do
    case $1 in
        --hours=*)
            HOURS="${1#*=}"
            shift
            ;;
        --output-dir=*)
            OUTPUT_DIR="${1#*=}"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create output directory
mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
REPORT_FILE="$OUTPUT_DIR/audit-$TIMESTAMP.md"

echo -e "${GREEN}Docker Error Audit${NC}"
echo -e "${YELLOW}Scanning logs from last $HOURS hours...${NC}"
echo ""

# Services to audit
SERVICES=("backend" "agent" "frontend" "postgres" "redis")

# Generate report header
cat > "$REPORT_FILE" <<EOF
# Docker Error Audit Report

**Generated:** $(date "+%Y-%m-%d %H:%M:%S")
**Time Range:** Last $HOURS hours
**Services Audited:** ${SERVICES[*]}

---

EOF

TOTAL_ERRORS=0

for service in "${SERVICES[@]}"; do
    echo -e "${CYAN}Auditing $service...${NC}"
    
    # Get logs from last N hours
    SINCE_TIME=$(date -u -d "$HOURS hours ago" "+%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -v-${HOURS}H "+%Y-%m-%dT%H:%M:%S" 2>/dev/null || echo "")
    
    if [ -z "$SINCE_TIME" ]; then
        # Fallback: use docker-compose logs without time filter
        LOGS=$(docker-compose logs --tail=1000 "$service" 2>&1 || echo "")
    else
        LOGS=$(docker-compose logs --since "$SINCE_TIME" "$service" 2>&1 || echo "")
    fi
    
    if [ $? -ne 0 ] || [ -z "$LOGS" ]; then
        echo -e "  ${YELLOW}⚠ Could not retrieve logs for $service${NC}"
        echo "" >> "$REPORT_FILE"
        echo "## $service" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo "⚠ Could not retrieve logs" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        continue
    fi
    
    # Error patterns
    declare -A ERROR_PATTERNS=(
        ["Exception"]="Python exceptions"
        ["Traceback"]="Python tracebacks"
        ["ERROR"]="General errors"
        ["Failed"]="Failed operations"
        ["ConnectionError"]="Connection errors"
        ["TimeoutError"]="Timeout errors"
        ["DatabaseError"]="Database errors"
        ["RedisError"]="Redis errors"
        ["HTTP.*5[0-9][0-9]"]="HTTP 5xx errors"
        ["HTTP.*4[0-9][0-9]"]="HTTP 4xx errors"
    )
    
    ERROR_COUNT=0
    
    echo "" >> "$REPORT_FILE"
    echo "## $service" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    
    for pattern in "${!ERROR_PATTERNS[@]}"; do
        CATEGORY="${ERROR_PATTERNS[$pattern]}"
        MATCHES=$(echo "$LOGS" | grep -iE "$pattern" || true)
        
        if [ -n "$MATCHES" ]; then
            ERROR_COUNT=$((ERROR_COUNT + 1))
            UNIQUE_COUNT=$(echo "$MATCHES" | sort -u | wc -l)
            TOTAL_MATCHES=$(echo "$MATCHES" | wc -l)
            
            echo "### $CATEGORY" >> "$REPORT_FILE"
            echo "" >> "$REPORT_FILE"
            echo "**Occurrences:** $TOTAL_MATCHES" >> "$REPORT_FILE"
            echo "**Unique Errors:** $UNIQUE_COUNT" >> "$REPORT_FILE"
            echo "" >> "$REPORT_FILE"
            echo "\`\`\`" >> "$REPORT_FILE"
            echo "$MATCHES" | head -5 >> "$REPORT_FILE"
            echo "\`\`\`" >> "$REPORT_FILE"
            echo "" >> "$REPORT_FILE"
        fi
    done
    
    if [ $ERROR_COUNT -eq 0 ]; then
        echo "✓ No errors found" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo -e "  ${GREEN}✓ No errors found${NC}"
    else
        TOTAL_ERRORS=$((TOTAL_ERRORS + ERROR_COUNT))
        echo -e "  ${RED}✗ Found $ERROR_COUNT error categories${NC}"
    fi
done

# Add summary
cat >> "$REPORT_FILE" <<EOF

---

## Summary

**Total Services Audited:** ${#SERVICES[@]}
**Total Error Categories:** $TOTAL_ERRORS

## Recommendations

EOF

if [ $TOTAL_ERRORS -eq 0 ]; then
    cat >> "$REPORT_FILE" <<EOF
- ✓ No errors detected in the specified time range
- Continue monitoring for any issues
EOF
else
    cat >> "$REPORT_FILE" <<EOF
- Review error categories above for each service
- Check for patterns in error occurrences
- Investigate high-frequency errors first
- Consider increasing log verbosity for detailed debugging
- Review service health checks and dependencies
EOF
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Audit Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${CYAN}Report saved to: $REPORT_FILE${NC}"
if [ $TOTAL_ERRORS -eq 0 ]; then
    echo -e "${GREEN}Total error categories found: $TOTAL_ERRORS${NC}"
else
    echo -e "${YELLOW}Total error categories found: $TOTAL_ERRORS${NC}"
fi

