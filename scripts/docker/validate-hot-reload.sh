#!/bin/bash
# Validation script for Docker hot reload setup

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Validating Docker Hot Reload Setup...${NC}\n"

# Check if docker-compose files exist
echo -e "${BLUE}Checking Docker Compose files...${NC}"
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}✗ docker-compose.yml not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ docker-compose.yml found${NC}"

if [ ! -f "docker-compose.dev.yml" ]; then
    echo -e "${RED}✗ docker-compose.dev.yml not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ docker-compose.dev.yml found${NC}"

# Check if Dockerfile.dev files exist
echo -e "\n${BLUE}Checking development Dockerfiles...${NC}"
for service in backend agent frontend; do
    if [ "$service" = "frontend" ]; then
        dockerfile="frontend/Dockerfile.dev"
    else
        dockerfile="${service}/Dockerfile.dev"
    fi
    
    if [ ! -f "$dockerfile" ]; then
        echo -e "${RED}✗ ${dockerfile} not found${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ ${dockerfile} found${NC}"
done

# Check if dev_watcher.py exists
echo -e "\n${BLUE}Checking agent file watcher...${NC}"
if [ ! -f "agent/scripts/dev_watcher.py" ]; then
    echo -e "${RED}✗ agent/scripts/dev_watcher.py not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ agent/scripts/dev_watcher.py found${NC}"

# Check if watchdog is mentioned in Dockerfile.dev
echo -e "\n${BLUE}Checking watchdog installation...${NC}"
if grep -q "watchdog" agent/Dockerfile.dev; then
    echo -e "${GREEN}✓ watchdog installation found in agent/Dockerfile.dev${NC}"
else
    echo -e "${YELLOW}⚠ watchdog not found in agent/Dockerfile.dev${NC}"
fi

# Check if dev_watcher is used as CMD
if grep -q "dev_watcher" agent/Dockerfile.dev; then
    echo -e "${GREEN}✓ dev_watcher CMD found in agent/Dockerfile.dev${NC}"
else
    echo -e "${YELLOW}⚠ dev_watcher CMD not found in agent/Dockerfile.dev${NC}"
fi

# Check volume mounts in docker-compose.dev.yml
echo -e "\n${BLUE}Checking volume mounts...${NC}"
if grep -q "./backend:/app/backend" docker-compose.dev.yml; then
    echo -e "${GREEN}✓ Backend volume mount found${NC}"
else
    echo -e "${YELLOW}⚠ Backend volume mount not found${NC}"
fi

if grep -q "./agent:/app/agent" docker-compose.dev.yml; then
    echo -e "${GREEN}✓ Agent volume mount found${NC}"
else
    echo -e "${YELLOW}⚠ Agent volume mount not found${NC}"
fi

if grep -q "./frontend:/app" docker-compose.dev.yml; then
    echo -e "${GREEN}✓ Frontend volume mount found${NC}"
else
    echo -e "${YELLOW}⚠ Frontend volume mount not found${NC}"
fi

# Check if uvicorn --reload is used
echo -e "\n${BLUE}Checking backend reload configuration...${NC}"
if grep -q "--reload" docker-compose.dev.yml || grep -q "--reload" backend/Dockerfile.dev; then
    echo -e "${GREEN}✓ Backend reload flag found${NC}"
else
    echo -e "${YELLOW}⚠ Backend reload flag not found${NC}"
fi

# Check if frontend uses npm run dev
echo -e "\n${BLUE}Checking frontend dev server...${NC}"
if grep -q "npm run dev" frontend/Dockerfile.dev; then
    echo -e "${GREEN}✓ Frontend dev server configuration found${NC}"
else
    echo -e "${YELLOW}⚠ Frontend dev server configuration not found${NC}"
fi

# Check documentation
echo -e "\n${BLUE}Checking documentation...${NC}"
if [ -f "docs/docker-hot-reload.md" ]; then
    echo -e "${GREEN}✓ docs/docker-hot-reload.md found${NC}"
else
    echo -e "${YELLOW}⚠ docs/docker-hot-reload.md not found${NC}"
fi

echo -e "\n${GREEN}Validation complete!${NC}"
echo -e "\n${BLUE}To test hot reload:${NC}"
echo -e "1. Start services: ${YELLOW}./scripts/docker/dev-start.sh --build${NC}"
echo -e "2. Make a change to a Python file in backend/ or agent/"
echo -e "3. Check logs: ${YELLOW}docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f${NC}"

