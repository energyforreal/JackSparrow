#!/bin/bash
# Docker development startup script for JackSparrow Trading Agent
# Starts development environment with hot-reload enabled

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
BUILD=false
DETACHED=false
SERVICE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD=true
            shift
            ;;
        -d|--detached)
            DETACHED=true
            shift
            ;;
        *)
            SERVICE="$1"
            shift
            ;;
    esac
done

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo -e "${YELLOW}Using default environment variables${NC}"
fi

echo -e "${GREEN}JackSparrow Docker Development Environment${NC}"
echo -e "${CYAN}Hot-reload enabled - code changes will be reflected automatically${NC}"
echo ""

# Build images if requested
if [ "$BUILD" = true ]; then
    echo -e "${BLUE}Building development images...${NC}"
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml build
    if [ $? -ne 0 ]; then
        echo -e "${RED}Build failed${NC}"
        exit 1
    fi
    echo ""
fi

# Start services
COMPOSE_ARGS=("-f" "docker-compose.yml" "-f" "docker-compose.dev.yml")

if [ "$DETACHED" = true ]; then
    COMPOSE_ARGS+=("up" "-d")
    echo -e "${BLUE}Starting services in detached mode...${NC}"
else
    COMPOSE_ARGS+=("up")
    echo -e "${BLUE}Starting services (press Ctrl+C to stop)...${NC}"
fi

if [ -n "$SERVICE" ]; then
    COMPOSE_ARGS+=("$SERVICE")
    echo -e "${YELLOW}Starting service: $SERVICE${NC}"
fi

echo ""
echo -e "${CYAN}Services will auto-reload on code changes:${NC}"
echo -e "${WHITE}  - Backend: uvicorn --reload${NC}"
echo -e "${WHITE}  - Frontend: npm run dev (Next.js hot-reload)${NC}"
echo -e "${WHITE}  - Agent: watchdog file watcher${NC}"
echo ""

docker-compose "${COMPOSE_ARGS[@]}"

