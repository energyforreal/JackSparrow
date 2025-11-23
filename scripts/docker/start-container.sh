#!/bin/bash
# Docker container start script for JackSparrow Trading Agent
# Starts individual containers with dependency handling

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Check if containers are provided
if [ $# -eq 0 ]; then
    echo -e "${RED}Error: No containers specified${NC}"
    echo "Usage: $0 <container1> [container2] ..."
    echo "Example: $0 backend agent"
    exit 1
fi

CONTAINERS=("$@")

# Function to check if container is running
is_container_running() {
    local service=$1
    docker-compose ps "$service" 2>/dev/null | grep -q "Up\|running"
}

# Function to start container
start_container() {
    local service=$1
    
    if is_container_running "$service"; then
        echo -e "${GREEN}✓ $service is already running${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Starting $service...${NC}"
    
    # Start dependencies first
    case $service in
        backend)
            start_container "postgres" || true
            start_container "redis" || true
            ;;
        agent)
            start_container "postgres" || true
            start_container "redis" || true
            start_container "backend" || true
            ;;
        frontend)
            start_container "backend" || true
            ;;
    esac
    
    # Start the container
    if docker-compose up -d "$service"; then
        echo -e "${GREEN}✓ $service started successfully${NC}"
        
        # Wait for health check
        echo -e "${YELLOW}  Waiting for $service to be healthy...${NC}"
        sleep 5
        
        local max_attempts=30
        local attempt=1
        while [ $attempt -le $max_attempts ]; do
            if docker-compose ps "$service" 2>/dev/null | grep -q "healthy"; then
                echo -e "${GREEN}✓ $service is healthy${NC}"
                return 0
            fi
            sleep 2
            attempt=$((attempt + 1))
        done
        
        echo -e "${YELLOW}⚠ $service started but health check pending${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed to start $service${NC}"
        return 1
    fi
}

echo -e "${GREEN}Starting Docker Containers${NC}"
echo -e "${YELLOW}Containers: ${CONTAINERS[*]}${NC}"
echo ""

SUCCESS=true
for container in "${CONTAINERS[@]}"; do
    if ! start_container "$container"; then
        SUCCESS=false
    fi
done

echo ""
if [ "$SUCCESS" = true ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}All containers started successfully!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    docker-compose ps
else
    echo -e "${RED}Some containers failed to start${NC}"
    exit 1
fi

