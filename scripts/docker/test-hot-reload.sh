#!/bin/bash
# Automated test script for Docker hot reload functionality
# Tests that code changes trigger automatic reloads/restarts

set -e

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

# Test results
TESTS_PASSED=0
TESTS_FAILED=0
TEST_RESULTS=()

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up test files...${NC}"
    # Remove test comments from files
    sed -i.bak '/# HOT_RELOAD_TEST/d' backend/api/main.py 2>/dev/null || true
    sed -i.bak '/# HOT_RELOAD_TEST/d' agent/core/intelligent_agent.py 2>/dev/null || true
    rm -f backend/api/main.py.bak agent/core/intelligent_agent.py.bak 2>/dev/null || true
    echo -e "${GREEN}Cleanup complete${NC}"
}

trap cleanup EXIT

# Function to check if services are running
check_services_running() {
    local services=$(docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps --services --filter "status=running" 2>/dev/null || echo "")
    if [ -z "$services" ]; then
        return 1
    fi
    return 0
}

# Function to wait for service to be ready
wait_for_service() {
    local service=$1
    local max_attempts=30
    local attempt=0
    
    echo -e "${BLUE}Waiting for $service to be ready...${NC}"
    while [ $attempt -lt $max_attempts ]; do
        if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps $service | grep -q "Up"; then
            sleep 2  # Give it a moment to fully start
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

# Function to check logs for reload message
check_reload_message() {
    local service=$1
    local pattern=$2
    local timeout=${3:-10}
    
    local start_time=$(date +%s)
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        if docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs --tail=50 $service 2>/dev/null | grep -q "$pattern"; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

# Test function
run_test() {
    local test_name=$1
    local test_func=$2
    
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}Test: $test_name${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if $test_func; then
        echo -e "${GREEN}✓ PASSED: $test_name${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        TEST_RESULTS+=("PASS: $test_name")
        return 0
    else
        echo -e "${RED}✗ FAILED: $test_name${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        TEST_RESULTS+=("FAIL: $test_name")
        return 1
    fi
}

# Test 1: Backend hot reload
test_backend_reload() {
    echo -e "${BLUE}Making change to backend file...${NC}"
    echo "# HOT_RELOAD_TEST $(date +%s)" >> backend/api/main.py
    
    echo -e "${BLUE}Waiting for backend reload...${NC}"
    if check_reload_message "backend" "Detected file change\|Reloading"; then
        echo -e "${GREEN}Backend reload detected${NC}"
        
        # Verify service is still healthy
        sleep 2
        if curl -f -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
            return 0
        else
            echo -e "${RED}Backend health check failed after reload${NC}"
            return 1
        fi
    else
        echo -e "${RED}Backend reload not detected in logs${NC}"
        return 1
    fi
}

# Test 2: Agent hot reload
test_agent_reload() {
    echo -e "${BLUE}Making change to agent file...${NC}"
    echo "# HOT_RELOAD_TEST $(date +%s)" >> agent/core/intelligent_agent.py
    
    echo -e "${BLUE}Waiting for agent restart...${NC}"
    if check_reload_message "agent" "file_changed\|restarting agent\|Starting agent process"; then
        echo -e "${GREEN}Agent restart detected${NC}"
        
        # Verify agent is still running
        sleep 3
        if docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps agent | grep -q "Up"; then
            return 0
        else
            echo -e "${RED}Agent not running after restart${NC}"
            return 1
        fi
    else
        echo -e "${RED}Agent restart not detected in logs${NC}"
        return 1
    fi
}

# Test 3: Verify file watcher is running
test_file_watcher_running() {
    echo -e "${BLUE}Checking if file watcher is running...${NC}"
    if docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T agent ps aux 2>/dev/null | grep -q "dev_watcher"; then
        echo -e "${GREEN}File watcher process found${NC}"
        return 0
    else
        echo -e "${YELLOW}File watcher process not found (may be running as main process)${NC}"
        # Check logs for watcher startup message
        if docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs agent 2>/dev/null | grep -q "watcher_ready\|File watcher is ready"; then
            return 0
        else
            echo -e "${RED}File watcher not detected${NC}"
            return 1
        fi
    fi
}

# Test 4: Verify watchdog is installed
test_watchdog_installed() {
    echo -e "${BLUE}Checking if watchdog is installed...${NC}"
    if docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T agent pip list 2>/dev/null | grep -q "watchdog"; then
        echo -e "${GREEN}Watchdog is installed${NC}"
        return 0
    else
        echo -e "${RED}Watchdog is not installed${NC}"
        return 1
    fi
}

# Main test execution
main() {
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}Docker Hot Reload Automated Test Suite${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    # Check if services are running
    if ! check_services_running; then
        echo -e "${YELLOW}Services are not running. Starting services...${NC}"
        echo -e "${BLUE}Please start services manually first:${NC}"
        echo -e "${BLUE}  ./scripts/docker/dev-start.sh --build${NC}"
        echo -e "${BLUE}  or${NC}"
        echo -e "${BLUE}  make docker-dev${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Services are running. Starting tests...${NC}"
    
    # Wait for services to be ready
    wait_for_service "backend" || echo -e "${YELLOW}Warning: Backend may not be ready${NC}"
    wait_for_service "agent" || echo -e "${YELLOW}Warning: Agent may not be ready${NC}"
    
    # Run tests
    run_test "Watchdog Installation" test_watchdog_installed
    run_test "File Watcher Running" test_file_watcher_running
    run_test "Backend Hot Reload" test_backend_reload
    run_test "Agent Hot Reload" test_agent_reload
    
    # Print summary
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}Test Summary${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    for result in "${TEST_RESULTS[@]}"; do
        if [[ $result == PASS:* ]]; then
            echo -e "${GREEN}$result${NC}"
        else
            echo -e "${RED}$result${NC}"
        fi
    done
    
    echo -e "\n${CYAN}Total: $((TESTS_PASSED + TESTS_FAILED)) tests${NC}"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    
    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "\n${GREEN}✓ All tests passed!${NC}"
        exit 0
    else
        echo -e "\n${RED}✗ Some tests failed${NC}"
        exit 1
    fi
}

# Run main function
main

