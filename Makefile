.PHONY: help start stop restart audit error clean install docker-dev docker-logs docker-start docker-audit docker-stop docker-restart docker-deploy

help:
	@echo "JackSparrow Trading Agent - Available Commands:"
	@echo "  make start      - Start all services (backend, agent, frontend)"
	@echo "  make stop       - Stop all services"
	@echo "  make restart    - Clean restart of all services"
	@echo "  make audit      - Run system audit (linting, tests, health checks)"
	@echo "  make error      - Quick diagnostic for errors"
	@echo "  make clean      - Clean temporary files and logs"
	@echo "  make install    - Install all dependencies"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-dev      - Start development environment with hot-reload"
	@echo "  make docker-deploy   - Deploy using Docker Compose (production)"
	@echo "  make docker-logs     - Show Docker logs [SERVICE=backend] [LEVEL=ERROR]"
	@echo "  make docker-start   - Start specific container [CONTAINER=backend]"
	@echo "  make docker-audit   - Audit Docker container errors"
	@echo "  make docker-stop    - Stop all Docker containers"
	@echo "  make docker-restart - Restart all Docker containers"

ifeq ($(OS),Windows_NT)
START_SCRIPT := tools/commands/start.ps1
STOP_SCRIPT := tools/commands/stop.ps1
RESTART_SCRIPT := tools/commands/restart.ps1
AUDIT_SCRIPT := tools/commands/audit.ps1
ERROR_SCRIPT := tools/commands/error.ps1
DOCKER_DEV_SCRIPT := scripts/docker/dev-start.ps1
DOCKER_DEPLOY_SCRIPT := scripts/docker/deploy.ps1
DOCKER_LOGS_SCRIPT := scripts/docker/logs.ps1
DOCKER_START_SCRIPT := scripts/docker/start-container.ps1
DOCKER_AUDIT_SCRIPT := scripts/docker/audit-errors.ps1
SHELL_CMD := powershell -ExecutionPolicy Bypass -File
else
START_SCRIPT := tools/commands/start.sh
STOP_SCRIPT := tools/commands/stop.sh
RESTART_SCRIPT := tools/commands/restart.sh
AUDIT_SCRIPT := tools/commands/audit.sh
ERROR_SCRIPT := tools/commands/error.sh
DOCKER_DEV_SCRIPT := scripts/docker/dev-start.sh
DOCKER_DEPLOY_SCRIPT := scripts/docker/deploy.sh
DOCKER_LOGS_SCRIPT := scripts/docker/logs.sh
DOCKER_START_SCRIPT := scripts/docker/start-container.sh
DOCKER_AUDIT_SCRIPT := scripts/docker/audit-errors.sh
SHELL_CMD := bash
endif

START_EXISTS := $(wildcard $(START_SCRIPT))
STOP_EXISTS := $(wildcard $(STOP_SCRIPT))
RESTART_EXISTS := $(wildcard $(RESTART_SCRIPT))
AUDIT_EXISTS := $(wildcard $(AUDIT_SCRIPT))
ERROR_EXISTS := $(wildcard $(ERROR_SCRIPT))

ifeq ($(START_EXISTS),)
start:
	@echo "Starting JackSparrow services..."
	@echo "Error: Start script not found"
	@exit 1
else
start:
	@echo "Starting JackSparrow services..."
	@$(SHELL_CMD) $(START_SCRIPT)
endif

ifeq ($(STOP_EXISTS),)
stop:
	@echo "Stopping JackSparrow services..."
	@if [ -f logs/backend.pid ]; then \
		kill $$(cat logs/backend.pid) 2>/dev/null || true; \
		rm -f logs/backend.pid; \
	fi; \
	if [ -f logs/agent.pid ]; then \
		kill $$(cat logs/agent.pid) 2>/dev/null || true; \
		rm -f logs/agent.pid; \
	fi; \
	if [ -f logs/frontend.pid ]; then \
		kill $$(cat logs/frontend.pid) 2>/dev/null || true; \
		rm -f logs/frontend.pid; \
	fi; \
	pkill -f "uvicorn.*api.main:app" 2>/dev/null || true; \
	pkill -f "agent.core.intelligent_agent" 2>/dev/null || true; \
	pkill -f "next dev" 2>/dev/null || true
	@echo "Services stopped"
else
stop:
	@echo "Stopping JackSparrow services..."
	@$(SHELL_CMD) $(STOP_SCRIPT)
	@echo "Services stopped"
endif

restart: stop
	@echo "Restarting JackSparrow services..."
ifneq ($(RESTART_EXISTS),)
	@$(SHELL_CMD) $(RESTART_SCRIPT)
else
	@$(MAKE) start
endif

ifeq ($(AUDIT_EXISTS),)
audit:
	@echo "Running system audit..."
	@echo "Error: Audit script not found"
	@exit 1
else
audit:
	@echo "Running system audit..."
	@$(SHELL_CMD) $(AUDIT_SCRIPT)
endif

ifeq ($(ERROR_EXISTS),)
error:
	@echo "Running error diagnostics..."
	@echo "Error: Error diagnostic script not found"
	@exit 1
else
error:
	@echo "Running error diagnostics..."
	@$(SHELL_CMD) $(ERROR_SCRIPT)
endif

clean:
	@echo "Cleaning temporary files..."
	@find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -r {} + 2>/dev/null || true
	@find . -type d -name ".next" -exec rm -r {} + 2>/dev/null || true
	@find . -type d -name "node_modules" -exec rm -r {} + 2>/dev/null || true
	@echo "Clean complete"

install:
	@echo "Installing dependencies..."
	@if [ -d backend ]; then \
		cd backend && pip install -r requirements.txt; \
	fi
	@if [ -d agent ]; then \
		cd agent && pip install -r requirements.txt; \
	fi
	@if [ -d frontend ]; then \
		cd frontend && npm install; \
	fi
	@echo "Installation complete"

# Docker commands
docker-dev:
	@echo "Starting Docker development environment with hot-reload..."
	@$(SHELL_CMD) $(DOCKER_DEV_SCRIPT)

docker-deploy:
	@echo "Deploying with Docker Compose..."
	@$(SHELL_CMD) $(DOCKER_DEPLOY_SCRIPT) up

docker-logs:
	@echo "Showing Docker logs..."
	@if [ -z "$(SERVICE)" ]; then \
		$(SHELL_CMD) $(DOCKER_LOGS_SCRIPT); \
	else \
		if [ "$(LEVEL)" ]; then \
			$(SHELL_CMD) $(DOCKER_LOGS_SCRIPT) $(SERVICE) --level=$(LEVEL); \
		else \
			$(SHELL_CMD) $(DOCKER_LOGS_SCRIPT) $(SERVICE); \
		fi \
	fi

docker-start:
	@echo "Starting Docker container..."
	@if [ -z "$(CONTAINER)" ]; then \
		echo "Error: CONTAINER not specified. Usage: make docker-start CONTAINER=backend"; \
		exit 1; \
	else \
		$(SHELL_CMD) $(DOCKER_START_SCRIPT) $(CONTAINER); \
	fi

docker-audit:
	@echo "Auditing Docker container errors..."
	@$(SHELL_CMD) $(DOCKER_AUDIT_SCRIPT)

docker-stop:
	@echo "Stopping all Docker containers..."
	@docker-compose down

docker-restart:
	@echo "Restarting all Docker containers..."
	@docker-compose restart

