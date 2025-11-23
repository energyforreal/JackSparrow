#!/bin/bash
# Docker logs analysis script for JackSparrow Trading Agent
# Analyzes Docker container logs with filtering and export capabilities

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Parse arguments
SERVICE=""
LEVEL="ALL"
TAIL=100
FOLLOW=false
EXPORT=false
OUTPUT_DIR="logs/docker-logs"

while [[ $# -gt 0 ]]; do
    case $1 in
        --level=*)
            LEVEL="${1#*=}"
            shift
            ;;
        --tail=*)
            TAIL="${1#*=}"
            shift
            ;;
        -f|--follow)
            FOLLOW=true
            shift
            ;;
        --export)
            EXPORT=true
            shift
            ;;
        --output-dir=*)
            OUTPUT_DIR="${1#*=}"
            shift
            ;;
        *)
            if [ -z "$SERVICE" ]; then
                SERVICE="$1"
            fi
            shift
            ;;
    esac
done

# Create output directory if exporting
if [ "$EXPORT" = true ]; then
    mkdir -p "$OUTPUT_DIR"
    TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
    OUTPUT_FILE="$OUTPUT_DIR/logs-${SERVICE:-all}-${LEVEL}-${TIMESTAMP}.log"
fi

echo -e "${GREEN}Docker Logs Analysis${NC}"
echo -e "${YELLOW}Service: ${SERVICE:-all}${NC}"
echo -e "${YELLOW}Level: $LEVEL${NC}"
echo -e "${YELLOW}Tail: $TAIL${NC}"
if [ "$EXPORT" = true ]; then
    echo -e "${CYAN}Exporting to: $OUTPUT_FILE${NC}"
fi
echo ""

# Function to filter logs by level
filter_logs() {
    local level=$1
    case $level in
        ERROR)
            grep -iE "ERROR|Exception|Traceback|Failed|Error" || true
            ;;
        WARNING)
            grep -iE "WARNING|Warning" || true
            ;;
        INFO)
            grep -iE "INFO|info" || true
            ;;
        DEBUG)
            grep -iE "DEBUG|debug" || true
            ;;
        ALL)
            cat
            ;;
        *)
            cat
            ;;
    esac
}

# Get list of services
if [ -z "$SERVICE" ]; then
    SERVICES=("backend" "agent" "frontend" "postgres" "redis")
else
    SERVICES=("$SERVICE")
fi

for svc in "${SERVICES[@]}"; do
    echo -e "${CYAN}=== $svc ===${NC}"
    
    if docker-compose logs --tail=$TAIL "$svc" 2>/dev/null | filter_logs "$LEVEL" > /tmp/docker_logs_$$; then
        while IFS= read -r line; do
            if echo "$line" | grep -qiE "ERROR|Exception|Traceback|Failed|Error"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -qiE "WARNING|Warning"; then
                echo -e "${YELLOW}$line${NC}"
            elif echo "$line" | grep -qiE "INFO|info"; then
                echo -e "${GREEN}$line${NC}"
            else
                echo -e "${WHITE}$line${NC}"
            fi
            
            if [ "$EXPORT" = true ]; then
                echo "[$svc] $line" >> "$OUTPUT_FILE"
            fi
        done < /tmp/docker_logs_$$
        rm -f /tmp/docker_logs_$$
    else
        echo -e "${RED}Failed to get logs for $svc${NC}"
    fi
    
    echo ""
done

# Export logs if requested
if [ "$EXPORT" = true ] && [ -f "$OUTPUT_FILE" ]; then
    echo -e "${GREEN}Logs exported to: $OUTPUT_FILE${NC}"
fi

# Follow mode
if [ "$FOLLOW" = true ]; then
    echo -e "${CYAN}Following logs (press Ctrl+C to stop)...${NC}"
    if [ -n "$SERVICE" ]; then
        docker-compose logs -f "$SERVICE"
    else
        docker-compose logs -f
    fi
fi

