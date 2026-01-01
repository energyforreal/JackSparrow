# Agent Functionality Testing Guide

## Overview

This guide explains how to test the JackSparrow Trading Agent's functionality using the comprehensive test suite.

## Test Suite Structure

### New Test: `test_agent_functionality.py`

A comprehensive test suite that validates the agent's working behavior, including:

1. **Agent Initialization** - Verifies all components are properly initialized
2. **State Machine** - Tests agent state transitions and context management
3. **Decision Making** - Validates trading decision generation
4. **Signal Generation** - Tests signal creation and validation
5. **Model Integration** - Verifies ML model loading and predictions
6. **Feature Computation** - Tests feature calculation from market data
7. **Reasoning Chain** - Validates 6-step reasoning chain generation
8. **Risk Management** - Tests risk assessment and position sizing
9. **Backend Communication** - Verifies agent-backend integration
10. **Health Status** - Tests agent health reporting
11. **Trading Logic** - Validates trading decision execution
12. **Event Publishing** - Tests event emission capabilities

## Running Tests

### Run All Functionality Tests

```bash
python tests/functionality/run_all_tests.py
```

### Run Only Agent Functionality Tests

```bash
python tests/functionality/run_agent_tests.py
```

### Run Specific Test Group

```bash
python tests/functionality/run_all_tests.py --groups agent-logic
```

### Run Tests Sequentially (for debugging)

```bash
python tests/functionality/run_all_tests.py --sequential
```

### Run Tests with Verbose Output

```bash
python tests/functionality/run_all_tests.py --verbose
```

## Prerequisites

Before running tests, ensure:

1. **Services are Running**:
   - Backend API (http://localhost:8000)
   - Agent service
   - Redis (localhost:6379)
   - PostgreSQL database (if using database tests)

2. **Environment Variables**:
   - `DATABASE_URL` - PostgreSQL connection string
   - `REDIS_URL` - Redis connection string (default: redis://localhost:6379)
   - `DELTA_EXCHANGE_API_KEY` - Delta Exchange API key (optional)
   - `DELTA_EXCHANGE_API_SECRET` - Delta Exchange API secret (optional)

3. **Dependencies**:
   - All Python dependencies installed (from `agent/requirements.txt`)
   - Test dependencies available

## Test Results

Test results are generated in multiple formats:

- **Markdown Report**: `tests/functionality/reports/comprehensive_test_report_*.md`
- **JSON Report**: `tests/functionality/reports/comprehensive_test_report_*.json`

## Understanding Test Status

- **PASS**: Test passed successfully
- **FAIL**: Test failed - critical issue
- **WARNING**: Test passed but with concerns
- **DEGRADED**: Test passed but performance degraded
- **SKIPPED**: Test skipped (usually due to missing dependencies)

## Troubleshooting

### Agent Not Initializing

- Check that all dependencies are installed
- Verify environment variables are set correctly
- Check agent logs for initialization errors

### Tests Timing Out

- Ensure services are running and responsive
- Check network connectivity
- Increase timeout in `config.py` if needed

### Model Discovery Failing

- Verify models exist in `agent/model_storage/`
- Check `MODEL_DIR` or `MODEL_PATH` environment variables
- Ensure model files are valid

### Backend Communication Failing

- Verify backend is running on port 8000
- Check backend health endpoint: `http://localhost:8000/api/v1/health`
- Ensure agent service is registered with backend

## Test Coverage

The test suite covers:

- ✅ Agent initialization and component setup
- ✅ State machine transitions
- ✅ Decision-making process
- ✅ Signal generation
- ✅ ML model integration
- ✅ Feature computation
- ✅ Reasoning chain generation
- ✅ Risk management
- ✅ Backend communication
- ✅ Health status reporting
- ✅ Trading logic
- ✅ Event publishing

## Continuous Integration

For CI/CD pipelines, run tests with:

```bash
python tests/functionality/run_all_tests.py --sequential --verbose
```

This ensures deterministic execution and detailed output for debugging.

## Contributing

When adding new agent functionality:

1. Add corresponding tests to `test_agent_functionality.py`
2. Follow the existing test structure and naming conventions
3. Ensure tests are idempotent and can run in parallel
4. Update this guide if adding new test categories

