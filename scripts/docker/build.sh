#!/bin/bash
# Docker build script for JackSparrow Trading Agent
# Builds all Docker images for the project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo -e "${GREEN}Building JackSparrow Docker images...${NC}"

# Get version/commit SHA for tagging
VERSION="${VERSION:-latest}"
COMMIT_SHA="${COMMIT_SHA:-$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')}"
BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

echo -e "${YELLOW}Version: ${VERSION}${NC}"
echo -e "${YELLOW}Commit SHA: ${COMMIT_SHA}${NC}"
echo -e "${YELLOW}Build Date: ${BUILD_DATE}${NC}"
echo ""

# Build backend
echo -e "${GREEN}Building backend image...${NC}"
docker build \
    -f backend/Dockerfile \
    -t jacksparrow-backend:${VERSION} \
    -t jacksparrow-backend:${COMMIT_SHA} \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg VERSION="${VERSION}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Backend image built successfully${NC}"
else
    echo -e "${RED}✗ Backend image build failed${NC}"
    exit 1
fi

# Build agent
echo -e "${GREEN}Building agent image...${NC}"
docker build \
    -f agent/Dockerfile \
    -t jacksparrow-agent:${VERSION} \
    -t jacksparrow-agent:${COMMIT_SHA} \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg VERSION="${VERSION}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Agent image built successfully${NC}"
else
    echo -e "${RED}✗ Agent image build failed${NC}"
    exit 1
fi

# Build frontend
echo -e "${GREEN}Building frontend image...${NC}"
docker build \
    -f frontend/Dockerfile \
    -t jacksparrow-frontend:${VERSION} \
    -t jacksparrow-frontend:${COMMIT_SHA} \
    --build-arg BUILD_DATE="${BUILD_DATE}" \
    --build-arg VERSION="${VERSION}" \
    --build-arg COMMIT_SHA="${COMMIT_SHA}" \
    frontend/

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Frontend image built successfully${NC}"
else
    echo -e "${RED}✗ Frontend image build failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}All images built successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Images:"
docker images | grep jacksparrow | head -3

# Optional: Push to registry if REGISTRY is set
if [ -n "${DOCKER_REGISTRY}" ]; then
    echo ""
    echo -e "${YELLOW}Pushing images to registry: ${DOCKER_REGISTRY}${NC}"
    docker tag jacksparrow-backend:${VERSION} ${DOCKER_REGISTRY}/jacksparrow-backend:${VERSION}
    docker tag jacksparrow-agent:${VERSION} ${DOCKER_REGISTRY}/jacksparrow-agent:${VERSION}
    docker tag jacksparrow-frontend:${VERSION} ${DOCKER_REGISTRY}/jacksparrow-frontend:${VERSION}
    
    docker push ${DOCKER_REGISTRY}/jacksparrow-backend:${VERSION}
    docker push ${DOCKER_REGISTRY}/jacksparrow-agent:${VERSION}
    docker push ${DOCKER_REGISTRY}/jacksparrow-frontend:${VERSION}
    
    echo -e "${GREEN}✓ Images pushed to registry${NC}"
fi

