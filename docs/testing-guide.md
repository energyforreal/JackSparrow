# Testing Guide

This guide provides comprehensive instructions for running tests and validating fixes in the JackSparrow Trading Agent project.

## Overview

The project includes comprehensive test suites covering:
- Unit tests for individual components
- Integration tests for component interactions
- **Functionality tests** for end-to-end system validation (including frontend)
- Validation scripts for fix verification
- Encoding tests for cross-platform compatibility

## Running Tests

### Quick Start

Run all fix-related tests:
```bash
python tools/commands/run-fix-tests.py
```

Validate all fixes are in place:
```bash
python tools/commands/validate-fixes.py
```

### Test Categories

#### Unit Tests

**Event Bus Deserialization Tests**
```bash
pytest tests/unit/trading_agent_tests/test_event_bus_deserialization.py -v
```

**XGBoost Node Tests**
```bash
pytest tests/unit/trading_agent_tests/test_xgboost_node.py -v
```

**Unicode Encoding Tests**
```bash
pytest tests/unit/tools/test_unicode_encoding.py -v
```

**Model Discovery Tests**
```bash
pytest tests/unit/trading_agent_tests/test_model_discovery.py -v
```

#### Integration Tests

**Event Pipeline Tests**
```bash
pytest tests/integration/test_event_pipeline.py -v
```

**Model Loading Tests**
```bash
pytest tests/integration/test_model_loading.py -v
```

**Startup Scripts Tests**
```bash
pytest tests/integration/test_startup_scripts.py -v
```

#### Functionality Tests

**Complete System Tests (Backend + Agent + Frontend)**
```bash
# Run all functionality tests including frontend
python tools/commands/start_and_test.py

# Run specific test groups
python tools/commands/start_and_test.py --groups infrastructure,core-services

# Run tests without starting services (assume already running)
python tools/commands/start_and_test.py --no-startup
```

**Frontend Functionality Tests**
```bash
# Frontend tests are included in the integration test group
python tools/commands/start_and_test.py --groups integration
```

The functionality test suite includes:
- **Infrastructure Tests**: Database, Redis, Delta Exchange connectivity
- **Core Services Tests**: Feature computation, ML models, WebSocket communication
- **Agent Logic Tests**: Decision making, risk management, signal generation
- **Integration Tests**: Agent communication, portfolio management, **frontend functionality**

**Frontend Functionality Test Coverage**:
- Frontend accessibility (HTTP endpoint)
- Frontend API integration (backend communication)
- Frontend WebSocket connection (real-time data)
- Frontend health endpoints
- CORS headers validation

### Validation Scripts

#### Validate Fixes

Check that all fixes are correctly implemented:
```bash
python tools/commands/validate-fixes.py
```

This validates:
- Unicode encoding fixes
- Event deserialization improvements
- XGBoost compatibility handling
- Corrupted model file handling
- Enhanced error handling

#### Test Unicode Encoding

Test Unicode handling on your platform:
```bash
python tools/commands/test-encoding.py
```

This tests:
- Unicode string handling
- Symbol rendering
- Script imports
- File operations with Unicode

#### Test Startup Sequence

Validate startup sequence works correctly:
```bash
python tools/commands/test-startup-sequence.py
```

## Test Coverage

### Current Coverage

- **Unit Tests**: Core components have unit test coverage
- **Integration Tests**: Key integration points are tested
- **Functionality Tests**: End-to-end system validation including frontend (101+ tests)
- **Validation Scripts**: All fixes are validated

### Coverage Requirements

- **Minimum Coverage**: 80% for all code
- **Critical Paths**: 100% coverage required for:
  - Risk management logic
  - Position sizing calculations
  - Trade execution
  - Error handling

## Running Tests with Coverage

```bash
# Run with coverage report
pytest --cov=agent --cov=backend --cov-report=html

# View coverage report
# Open htmlcov/index.html in browser
```

## Test Environment Setup

### Prerequisites

1. Python 3.12+
2. All dependencies installed:
   ```bash
   pip install -r backend/requirements.txt
   pip install -r agent/requirements.txt
   ```

3. Test dependencies:
   ```bash
   pip install pytest pytest-asyncio pytest-cov
   ```

### Environment Variables

Tests use minimal environment variables. Default test values are set in test files:
- `DATABASE_URL`: Test database URL
- `DELTA_EXCHANGE_API_KEY`: Test API key
- `DELTA_EXCHANGE_API_SECRET`: Test API secret
- `REDIS_URL`: Test Redis URL

## Troubleshooting

### Common Issues

**Import Errors**
- Ensure project root is in Python path
- Check that all dependencies are installed

**Async Test Failures**
- Ensure `pytest-asyncio` is installed
- Check that async fixtures are properly configured

**Model Loading Failures**
- Ensure XGBoost is installed for model tests
- Check that test model files are created correctly

**Unicode Encoding Errors**
- On Windows, ensure UTF-8 encoding is configured
- Check that scripts use ASCII-safe symbols on Windows

## Continuous Integration

Tests should be run:
- Before committing code
- In CI/CD pipeline (includes functionality tests with frontend)
- Before releases
- After major refactoring

### CI/CD Test Execution

The CI/CD pipeline automatically runs:
1. **Unit Tests**: Python unit tests for backend and agent
2. **Frontend Tests**: Next.js/React unit tests
3. **Functionality Tests**: Complete system tests including frontend integration
   - Services are started automatically
   - Tests run against running services
   - Reports are uploaded as artifacts

See `.github/workflows/cicd.yml` for the complete CI/CD configuration.

## Test Maintenance

### Adding New Tests

1. Follow existing test structure
2. Use appropriate test fixtures
3. Include docstrings
4. Follow naming conventions (`test_*.py`)

### Updating Tests

- Update tests when code changes
- Maintain test coverage above 80%
- Keep tests fast and reliable

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Project Testing Standards](docs/14-project-rules.md#testing-requirements)
- [Code Review Checklist](docs/14-project-rules.md#code-review-checklist)

