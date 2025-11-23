#!/bin/bash
# Docker deployment script for JackSparrow Trading Agent
# Deploys the application using docker-compose

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

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo -e "${YELLOW}Please create .env file from .env.example${NC}"
    exit 1
fi

# Function to check service health
check_health() {
    local service=$1
    local max_attempts=${2:-30}
    local attempt=1
    
    echo -e "${BLUE}Waiting for ${service} to be healthy...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if docker-compose ps $service | grep -q "healthy"; then
            echo -e "${GREEN}✓ ${service} is healthy${NC}"
            return 0
        fi
        
        if docker-compose ps $service | grep -q "unhealthy"; then
            echo -e "${RED}✗ ${service} is unhealthy${NC}"
            return 1
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${RED}✗ ${service} health check timeout${NC}"
    return 1
}

# Deployment mode
MODE="${1:-up}"
PULL_IMAGES="${PULL_IMAGES:-false}"

echo -e "${GREEN}JackSparrow Docker Deployment${NC}"
echo -e "${YELLOW}Mode: ${MODE}${NC}"
echo ""

# Pull latest images if requested
if [ "$PULL_IMAGES" = "true" ]; then
    echo -e "${BLUE}Pulling latest images...${NC}"
    docker-compose pull || echo -e "${YELLOW}Warning: Some images may not be available in registry${NC}"
    echo ""
fi

case "$MODE" in
    up)
        echo -e "${GREEN}Starting all services...${NC}"
        docker-compose up -d --build
        
        echo ""
        echo -e "${BLUE}Waiting for services to start...${NC}"
        sleep 10
        
        # Check health of critical services
        check_health "postgres" 15 || true
        check_health "redis" 10 || true
        check_health "backend" 20 || true
        check_health "agent" 30 || true
        check_health "frontend" 20 || true
        
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}Deployment completed!${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        docker-compose ps
        ;;
    
    down)
        echo -e "${YELLOW}Stopping all services...${NC}"
        docker-compose down
        echo -e "${GREEN}✓ All services stopped${NC}"
        ;;
    
    restart)
        echo -e "${YELLOW}Restarting all services...${NC}"
        docker-compose restart
        echo -e "${GREEN}✓ All services restarted${NC}"
        ;;
    
    update)
        echo -e "${BLUE}Performing rolling update...${NC}"
        
        # Pull latest images
        docker-compose pull
        
        # Update services one by one
        echo -e "${BLUE}Updating backend...${NC}"
        docker-compose up -d --no-deps backend
        check_health "backend" 20 || true
        
        echo -e "${BLUE}Updating agent...${NC}"
        docker-compose up -d --no-deps agent
        check_health "agent" 30 || true
        
        echo -e "${BLUE}Updating frontend...${NC}"
        docker-compose up -d --no-deps frontend
        check_health "frontend" 20 || true
        
        echo -e "${GREEN}✓ Rolling update completed${NC}"
        ;;
    
    logs)
        docker-compose logs -f
        ;;
    
    *)
        echo -e "${RED}Unknown mode: ${MODE}${NC}"
        echo "Usage: $0 [up|down|restart|update|logs]"
        exit 1
        ;;
esac

