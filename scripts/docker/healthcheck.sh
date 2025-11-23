#!/bin/bash
# Health check script for JackSparrow Docker deployment
# Checks the health of all services

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

echo -e "${BLUE}JackSparrow Health Check${NC}"
echo "=========================================="
echo ""

# Check if docker-compose is running
if ! docker-compose ps | grep -q "Up"; then
    echo -e "${RED}✗ Docker Compose services are not running${NC}"
    echo -e "${YELLOW}Run 'docker-compose up -d' to start services${NC}"
    exit 1
fi

# Function to check HTTP endpoint
check_http() {
    local url=$1
    local name=$2
    
    if curl -f -s "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ ${name} is reachable${NC}"
        return 0
    else
        echo -e "${RED}✗ ${name} is not reachable${NC}"
        return 1
    fi
}

# Function to check container health
check_container() {
    local service=$1
    local container_status=$(docker-compose ps $service 2>/dev/null | tail -n +3 | awk '{print $1}')
    
    if [ -z "$container_status" ]; then
        echo -e "${RED}✗ ${service} container not found${NC}"
        return 1
    fi
    
    local health_status=$(docker inspect --format='{{.State.Health.Status}}' "jacksparrow-${service}" 2>/dev/null || echo "none")
    
    if [ "$health_status" = "healthy" ]; then
        echo -e "${GREEN}✓ ${service} is healthy${NC}"
        return 0
    elif [ "$health_status" = "starting" ]; then
        echo -e "${YELLOW}⏳ ${service} is starting...${NC}"
        return 1
    elif [ "$health_status" = "unhealthy" ]; then
        echo -e "${RED}✗ ${service} is unhealthy${NC}"
        return 1
    else
        # No health check configured, check if running
        if docker ps --filter "name=jacksparrow-${service}" --format "{{.Status}}" | grep -q "Up"; then
            echo -e "${GREEN}✓ ${service} is running${NC}"
            return 0
        else
            echo -e "${RED}✗ ${service} is not running${NC}"
            return 1
        fi
    fi
}

# Check containers
echo -e "${BLUE}Checking container health...${NC}"
check_container "postgres"
check_container "redis"
check_container "backend"
check_container "agent"
check_container "frontend"

echo ""

# Check HTTP endpoints
echo -e "${BLUE}Checking HTTP endpoints...${NC}"

# Get ports from environment or use defaults
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

check_http "http://localhost:${BACKEND_PORT}/api/v1/health" "Backend API"
check_http "http://localhost:${FRONTEND_PORT}" "Frontend"

echo ""

# Check database connectivity
echo -e "${BLUE}Checking database connectivity...${NC}"
if docker-compose exec -T postgres pg_isready -U "${POSTGRES_USER:-jacksparrow}" -d "${POSTGRES_DB:-trading_agent}" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL is accessible${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not accessible${NC}"
fi

# Check Redis connectivity
echo -e "${BLUE}Checking Redis connectivity...${NC}"
if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis is accessible${NC}"
else
    echo -e "${RED}✗ Redis is not accessible${NC}"
fi

echo ""

# Check logs for errors
echo -e "${BLUE}Checking for recent errors in logs...${NC}"
ERROR_COUNT=0

# Check backend logs
if docker-compose logs --tail=50 backend 2>/dev/null | grep -i "error\|exception\|traceback" | grep -v "DEBUG" > /dev/null; then
    echo -e "${YELLOW}⚠ Backend logs contain errors${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# Check agent logs
if docker-compose logs --tail=50 agent 2>/dev/null | grep -i "error\|exception\|traceback" | grep -v "DEBUG" > /dev/null; then
    echo -e "${YELLOW}⚠ Agent logs contain errors${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# Check frontend logs
if docker-compose logs --tail=50 frontend 2>/dev/null | grep -i "error\|exception" | grep -v "DEBUG" > /dev/null; then
    echo -e "${YELLOW}⚠ Frontend logs contain errors${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

if [ $ERROR_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓ No recent errors found in logs${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Health check completed${NC}"

# Generate summary
echo ""
echo -e "${BLUE}Service Status Summary:${NC}"
docker-compose ps

