#!/bin/bash
# Production Docker deployment script for JackSparrow Trading Agent
# Rebuilds all images from scratch and deploys the stack

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

# Parse command line arguments
REMOVE_IMAGES=false
REMOVE_VOLUMES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --remove-images)
            REMOVE_IMAGES=true
            shift
            ;;
        --remove-volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: $0 [--remove-images] [--remove-volumes]"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}JackSparrow Production Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Function to check service health
check_health() {
    local service=$1
    local max_attempts=${2:-30}
    local attempt=1
    
    echo -e "${BLUE}Waiting for ${service} to be healthy...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if docker compose ps $service 2>/dev/null | grep -q "healthy"; then
            echo -e "${GREEN}✓ ${service} is healthy${NC}"
            return 0
        fi
        
        if docker compose ps $service 2>/dev/null | grep -q "unhealthy"; then
            echo -e "${RED}✗ ${service} is unhealthy${NC}"
            docker compose logs --tail=50 $service
            return 1
        fi
        
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${RED}✗ ${service} health check timeout${NC}"
    docker compose logs --tail=50 $service
    return 1
}

# Step 1: Stop existing containers
echo -e "${YELLOW}Step 1: Stopping existing containers...${NC}"
docker compose down || true
echo -e "${GREEN}✓ Containers stopped${NC}"
echo ""

# Step 2: Remove old images if requested
if [ "$REMOVE_IMAGES" = true ]; then
    echo -e "${YELLOW}Step 2: Removing old images...${NC}"
    docker images | grep jacksparrow | awk '{print $3}' | xargs -r docker rmi -f || true
    echo -e "${GREEN}✓ Old images removed${NC}"
    echo ""
fi

# Step 3: Remove volumes if requested (WARNING: This deletes data!)
if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${YELLOW}Step 3: Removing volumes (WARNING: This deletes database data!)...${NC}"
    read -p "Are you sure you want to delete all volumes? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        docker compose down -v || true
        echo -e "${GREEN}✓ Volumes removed${NC}"
    else
        echo -e "${YELLOW}Volumes removal cancelled${NC}"
    fi
    echo ""
fi

# Step 4: Rebuild all images with --no-cache
echo -e "${YELLOW}Step 4: Rebuilding all images from scratch (--no-cache)...${NC}"
echo -e "${BLUE}This may take several minutes...${NC}"
echo ""

# Build backend
echo -e "${BLUE}Building backend image...${NC}"
docker compose build --no-cache backend
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Backend image built successfully${NC}"
else
    echo -e "${RED}✗ Backend image build failed${NC}"
    exit 1
fi
echo ""

# Build agent
echo -e "${BLUE}Building agent image...${NC}"
docker compose build --no-cache agent
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Agent image built successfully${NC}"
else
    echo -e "${RED}✗ Agent image build failed${NC}"
    exit 1
fi
echo ""

# Build frontend
echo -e "${BLUE}Building frontend image...${NC}"
docker compose build --no-cache frontend
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Frontend image built successfully${NC}"
else
    echo -e "${RED}✗ Frontend image build failed${NC}"
    exit 1
fi
echo ""

# Step 5: Start all services
echo -e "${YELLOW}Step 5: Starting all services...${NC}"
docker compose up -d

echo ""
echo -e "${BLUE}Waiting for services to initialize...${NC}"
sleep 15

# Step 6: Check health of all services
echo ""
echo -e "${YELLOW}Step 6: Checking service health...${NC}"

# Check database services first
check_health "postgres" 20 || echo -e "${YELLOW}Warning: Postgres health check failed${NC}"
check_health "redis" 15 || echo -e "${YELLOW}Warning: Redis health check failed${NC}"

# Check application services
check_health "backend" 30 || echo -e "${YELLOW}Warning: Backend health check failed${NC}"
check_health "agent" 40 || echo -e "${YELLOW}Warning: Agent health check failed${NC}"
check_health "frontend" 30 || echo -e "${YELLOW}Warning: Frontend health check failed${NC}"

# Step 7: Display service status
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Summary${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
docker compose ps
echo ""

# Step 8: Display service URLs
echo -e "${GREEN}Service URLs:${NC}"
echo -e "  Frontend:    http://localhost:${FRONTEND_PORT:-3000}"
echo -e "  Backend API: http://localhost:${BACKEND_PORT:-8000}"
echo -e "  API Docs:    http://localhost:${BACKEND_PORT:-8000}/docs"
echo -e "  Agent:       http://localhost:${FEATURE_SERVER_PORT:-8001}"
echo ""

# Step 9: Display logs command
echo -e "${BLUE}To view logs, run:${NC}"
echo -e "  docker compose logs -f [service_name]"
echo ""
echo -e "${BLUE}To view all logs:${NC}"
echo -e "  docker compose logs -f"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Production deployment completed!${NC}"
echo -e "${GREEN}========================================${NC}"

