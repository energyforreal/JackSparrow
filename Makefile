.PHONY: help start stop restart audit error clean install

help:
	@echo "JackSparrow Trading Agent - Available Commands:"
	@echo "  make start      - Start all services (backend, agent, frontend)"
	@echo "  make stop       - Stop all services"
	@echo "  make restart    - Clean restart of all services"
	@echo "  make audit      - Run system audit (linting, tests, health checks)"
	@echo "  make error      - Quick diagnostic for errors"
	@echo "  make clean      - Clean temporary files and logs"
	@echo "  make install    - Install all dependencies"

start:
	@echo "Starting JackSparrow services..."
	@if [ -f tools/commands/start.sh ]; then \
		bash tools/commands/start.sh; \
	elif [ -f tools/commands/start.ps1 ]; then \
		powershell -ExecutionPolicy Bypass -File tools/commands/start.ps1; \
	else \
		echo "Error: Start script not found"; \
		exit 1; \
	fi

stop:
	@echo "Stopping JackSparrow services..."
	@pkill -f "uvicorn api.main:app" || true
	@pkill -f "agent.core.intelligent_agent" || true
	@pkill -f "next dev" || true
	@echo "Services stopped"

restart: stop
	@echo "Restarting JackSparrow services..."
	@if [ -f tools/commands/restart.sh ]; then \
		bash tools/commands/restart.sh; \
	elif [ -f tools/commands/restart.ps1 ]; then \
		powershell -ExecutionPolicy Bypass -File tools/commands/restart.ps1; \
	else \
		$(MAKE) start; \
	fi

audit:
	@echo "Running system audit..."
	@if [ -f tools/commands/audit.sh ]; then \
		bash tools/commands/audit.sh; \
	elif [ -f tools/commands/audit.ps1 ]; then \
		powershell -ExecutionPolicy Bypass -File tools/commands/audit.ps1; \
	else \
		echo "Error: Audit script not found"; \
		exit 1; \
	fi

error:
	@echo "Running error diagnostics..."
	@if [ -f tools/commands/error.sh ]; then \
		bash tools/commands/error.sh; \
	elif [ -f tools/commands/error.ps1 ]; then \
		powershell -ExecutionPolicy Bypass -File tools/commands/error.ps1; \
	else \
		echo "Error: Error diagnostic script not found"; \
		exit 1; \
	fi

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

