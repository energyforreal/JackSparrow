# Project Rules Documentation

## Overview

This document defines the coding standards, Git workflow, naming conventions, documentation standards, testing requirements, and code review process for the **JackSparrow** project.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Coding Standards](#coding-standards)
- [Git Workflow](#git-workflow)
- [Naming Conventions](#naming-conventions)
- [Documentation Standards](#documentation-standards)
- [Testing Requirements](#testing-requirements)
- [Code Review Process](#code-review-process)
- [File Organization](#file-organization)
- [Error Handling](#error-handling)
- [Logging Standards](#logging-standards)
- [Security Standards](#security-standards)
- [Performance Standards](#performance-standards)
- [Operational Command Guidelines](#operational-command-guidelines)
- [ML Model Management Standards](#ml-model-management-standards)
- [Related Documentation](#related-documentation)

---

## Coding Standards

### Python Code Style

**Style Guide**: Follow PEP 8 with some modifications

**Line Length**: Maximum 100 characters (soft limit at 88)

**Import Organization**:
```python
# Standard library imports
import os
import sys
from datetime import datetime

# Third-party imports
import fastapi
import numpy as np

# Local imports
from .core import Agent
from .utils import format_price
```

**Docstrings**: Use Google-style docstrings

```python
def calculate_position_size(signal_strength: float, risk_level: float) -> float:
    """Calculate position size based on signal strength and risk level.
    
    Args:
        signal_strength: Signal strength from 0.0 to 1.0
        risk_level: Risk level from 0.0 to 1.0
        
    Returns:
        Position size as percentage of portfolio (0.0 to 0.1)
        
    Raises:
        ValueError: If signal_strength or risk_level out of range
    """
    if not 0.0 <= signal_strength <= 1.0:
        raise ValueError("signal_strength must be between 0.0 and 1.0")
    # ... implementation
```

**Type Hints**: Always use type hints for function parameters and return types

```python
def process_trade(trade: Trade, context: AgentContext) -> TradeResult:  # See [Logic & Reasoning Documentation](05-logic-reasoning.md#agentcontext-structure) for AgentContext definition
    """Process a trade."""
    # ...
```

---

### TypeScript/React Code Style

**Style Guide**: Follow Airbnb JavaScript/TypeScript Style Guide

**Component Structure**:
```typescript
import React from 'react';
import { ComponentProps } from './types';

/**
 * Component description
 */
export function ComponentName({ prop1, prop2 }: ComponentProps) {
  // Hooks first
  const [state, setState] = React.useState('');
  
  // Effects
  React.useEffect(() => {
    // Effect logic
  }, []);
  
  // Handlers
  const handleClick = () => {
    // Handler logic
  };
  
  // Render
  return (
    <div>
      {/* Component JSX */}
    </div>
  );
}
```

**Type Definitions**: Always define types/interfaces

```typescript
interface ComponentProps {
  prop1: string;
  prop2: number;
  optionalProp?: boolean;
}
```

**Naming Conventions**:
- Components: PascalCase (`ComponentName`)
- Functions: camelCase (`handleClick`)
- Constants: UPPER_SNAKE_CASE (`MAX_RETRIES`)
- Types/Interfaces: PascalCase (`UserData`)

---

## Git Workflow

### Branch Strategy

**Main Branches**:
- `main`: Production-ready code
- `develop`: Integration branch for features

**Supporting Branches**:
- `feature/*`: New features
- `bugfix/*`: Bug fixes
- `hotfix/*`: Critical production fixes
- `release/*`: Release preparation

**Branch Naming**:
- `feature/agent-reasoning-engine`
- `bugfix/websocket-reconnection`
- `hotfix/critical-memory-leak`
- `release/v1.0.0`

---

### Commit Messages

**Format**: Follow Conventional Commits specification

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples**:
```
feat(agent): add 6-step reasoning chain

Implement structured reasoning process with situational assessment,
historical context retrieval, model consensus analysis, risk assessment,
decision synthesis, and confidence calibration.

Closes #123
```

```
fix(backend): resolve WebSocket reconnection issue

Fix exponential backoff logic in WebSocket client to prevent
infinite reconnection attempts.

Fixes #456
```

---

### Pull Request Process

1. **Create Feature Branch**:
   ```bash
   git checkout -b feature/new-feature develop
   ```

2. **Make Changes**: Write code, tests, and documentation

3. **Commit Changes**: Use conventional commit format

4. **Push Branch**:
   ```bash
   git push origin feature/new-feature
   ```

5. **Create Pull Request**:
   - Target: `develop` branch
   - Fill out PR template
   - Request reviewers
   - Link related issues

6. **Code Review**:
   - Address review comments
   - Update PR as needed
   - Ensure all checks pass

7. **Merge**: Squash and merge after approval

---

## Naming Conventions

### Python Naming

**Files**: `snake_case.py`
- `agent_service.py`
- `risk_manager.py`
- `feature_server.py`

**Classes**: `PascalCase`
- `AgentService`
- `RiskManager`
- `FeatureServer`

**Functions**: `snake_case()`
- `calculate_position_size()`
- `get_portfolio_status()`
- `process_trade()`

**Constants**: `UPPER_SNAKE_CASE`
- `MAX_POSITION_SIZE`
- `DEFAULT_RISK_LEVEL`
- `API_TIMEOUT_SECONDS`

**Private**: Prefix with underscore
- `_internal_method()`
- `_private_variable`

---

### TypeScript/React Naming

**Files**: `PascalCase.tsx` for components, `camelCase.ts` for utilities
- `AgentStatus.tsx`
- `useWebSocket.ts`
- `apiClient.ts`

**Components**: `PascalCase`
- `AgentStatus`
- `PortfolioSummary`
- `ReasoningChainView`

**Hooks**: `useCamelCase`
- `useWebSocket`
- `useAgent`
- `usePortfolio`

**Functions**: `camelCase`
- `handleClick`
- `formatPrice`
- `calculatePnL`

**Constants**: `UPPER_SNAKE_CASE`
- `API_BASE_URL`
- `MAX_RETRIES`
- `DEFAULT_TIMEOUT`

---

## Documentation Standards

### Code Documentation

**Python Docstrings**: Required for all public functions, classes, and modules

```python
class RiskManager:
    """Manages trading risk and position sizing.
    
    This class implements risk management logic including position sizing,
    stop loss calculation, and portfolio heat monitoring.
    """
    
    def calculate_position_size(self, signal_strength: float) -> float:
        """Calculate position size based on signal strength."""
        # ...
```

**TypeScript Comments**: Use JSDoc for public functions

```typescript
/**
 * Formats a price value for display
 * @param price - Price value to format
 * @param decimals - Number of decimal places
 * @returns Formatted price string
 */
export function formatPrice(price: number, decimals: number = 2): string {
  // ...
}
```

---

### README Files

**Required README Sections**:
- Project description
- Installation instructions
- Usage examples
- Configuration
- Contributing guidelines
- License

**Example Structure**:
```markdown
# Module Name

Brief description of the module.

## Installation

## Usage

## Configuration

## Contributing
```

---

### API Documentation

**Backend API**: Use FastAPI automatic documentation
- Add docstrings to endpoints
- Use Pydantic models for request/response
- Include examples

**Frontend Components**: Document props and usage
- Prop types/interfaces
- Usage examples
- Component behavior

---

## Testing Requirements

### Test Coverage

**Minimum Coverage**: 80% code coverage

**Critical Paths**: 100% coverage required
- Risk management logic
- Position sizing calculations
- Trade execution
- Error handling

---

### Test Organization

**Unit Tests**:
- One test file per source file
- Test file naming: `test_*.py` or `*.test.tsx`
- Mirror source directory structure

**Integration Tests**:
- Test module interactions
- Test API endpoints
- Test database operations

**End-to-End Tests**:
- Test complete user flows
- Test critical paths
- Test error scenarios

---

### Test Writing Guidelines

**Python Tests** (pytest):
```python
import pytest
from agent.risk import RiskManager

class TestRiskManager:
    def test_calculate_position_size_normal(self):
        """Test normal position size calculation."""
        manager = RiskManager()
        size = manager.calculate_position_size(signal_strength=0.8, risk_level=0.3)
        assert 0.0 <= size <= 0.1
        assert size == pytest.approx(0.064, rel=0.01)
    
    def test_calculate_position_size_invalid_input(self):
        """Test position size calculation with invalid input."""
        manager = RiskManager()
        with pytest.raises(ValueError):
            manager.calculate_position_size(signal_strength=1.5, risk_level=0.3)
```

**TypeScript Tests** (Jest/React Testing Library):
```typescript
import { render, screen } from '@testing-library/react';
import { AgentStatus } from './AgentStatus';

describe('AgentStatus', () => {
  it('displays monitoring state correctly', () => {
    render(<AgentStatus state="MONITORING" lastUpdate={new Date()} />);
    expect(screen.getByText('Monitoring Markets')).toBeInTheDocument();
  });
  
  it('displays correct color for monitoring state', () => {
    const { container } = render(
      <AgentStatus state="MONITORING" lastUpdate={new Date()} />
    );
    expect(container.firstChild).toHaveClass('status-green');
  });
});
```

---

### Running Tests

**Python**:
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=backend --cov=agent

# Run specific test file
pytest tests/unit/backend/test_services.py
```

**TypeScript**:
```bash
# Run all tests
npm test

# Run with coverage
npm test -- --coverage

# Run in watch mode
npm test -- --watch
```

---

## Code Review Process

### Review Checklist

**Functionality**:
- [ ] Code works as intended
- [ ] Edge cases handled
- [ ] Error handling implemented
- [ ] No breaking changes (or documented)

**Code Quality**:
- [ ] Follows coding standards
- [ ] Proper naming conventions
- [ ] Adequate comments/documentation
- [ ] No code duplication
- [ ] Proper abstraction

**Testing**:
- [ ] Tests written and passing
- [ ] Adequate test coverage
- [ ] Edge cases tested
- [ ] Integration tests updated

**Performance**:
- [ ] No obvious performance issues
- [ ] Database queries optimized
- [ ] Caching used appropriately
- [ ] No memory leaks

**Security**:
- [ ] No security vulnerabilities
- [ ] Input validation
- [ ] Authentication/authorization
- [ ] Secrets not exposed

---

### Review Guidelines

**For Authors**:
- Keep PRs focused and small
- Write clear commit messages
- Respond to review comments promptly
- Update PR based on feedback

**For Reviewers**:
- Be constructive and respectful
- Explain reasoning for suggestions
- Approve when standards are met
- Request changes when needed

**Review Timeline**:
- Initial review within 24 hours
- Follow-up reviews within 48 hours
- Critical fixes reviewed immediately

---

## File Organization

### Directory Structure

Follow the structure defined in [File Structure Documentation](08-file-structure.md)

**Key Principles**:
- One module per directory
- Clear separation of concerns
- Consistent naming
- Logical grouping

---

### Import Organization

**Python**:
```python
# Standard library
import os
from datetime import datetime

# Third-party
import numpy as np
import fastapi

# Local
from .core import Agent
from .utils import format_price
```

**TypeScript**:
```typescript
// React
import React, { useState, useEffect } from 'react';

// Third-party
import { format } from 'date-fns';

// Local
import { useWebSocket } from '@/hooks/useWebSocket';
import { apiClient } from '@/services/api';
```

---

## Error Handling

### Error Handling Standards

**Python**:
```python
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise CustomError("User-friendly message") from e
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise
```

**TypeScript**:
```typescript
try {
  const result = await riskyOperation();
  return result;
} catch (error) {
  console.error('Operation failed:', error);
  throw new CustomError('User-friendly message', { cause: error });
}
```

**Error Types**:
- Use specific error types
- Provide helpful error messages
- Log errors with context
- Don't expose internal details

---

## Logging Standards

All teams must follow the centralized plan outlined in [Logging Documentation](12-logging.md). The guidelines below summarise enforceable rules for code reviews.

### Log Levels

- **DEBUG**: Detailed information for debugging
- **INFO**: General informational messages
- **WARNING**: Warning messages for potential issues
- **ERROR**: Error messages for failures
- **CRITICAL**: Critical errors requiring immediate attention

### Log Format

**Structured Logging**:
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "trade_executed",
    trade_id="trade_123",
    symbol="BTCUSD",
    side="buy",
    quantity=0.1,
    price=50000.0
)
```

**Include Context**:
- Correlation IDs
- User IDs (if applicable)
- Request IDs
- Timestamps
- Relevant data
- `service`, `component`, `session_id`, and `environment` fields

### Startup Clearing

- Archive or delete previous logs before every start (implemented in startup scripts or service initialization code).
- Emit a `system.startup` event containing the new `session_id`, commit SHA, and environment.
- Verify automation (e.g., startup scripts, deployment pipelines) runs bootstrap scripts prior to launching services.

### Forwarding & Retention

- Honour `LOG_FORWARDING_ENABLED` and `LOG_FORWARDING_ENDPOINT` configuration in each environment.
- Maintain a default retention of 7 days locally; production retention must meet compliance requirements.
- When forwarding is enabled, retain a local copy for at least 24 hours to support incident response.

### Validation

- Add unit/integration tests that assert logging output shape for critical flows.
- Verify logging setup before merges that affect logging infrastructure (check log directories are writable and logs are being generated).
- Ensure CI verifies that JSON log schema includes required fields and that startup events were emitted.

---

## Security Standards

### Security Checklist

- [ ] No hardcoded secrets
- [ ] Environment variables for configuration
- [ ] Input validation
- [ ] SQL injection prevention
- [ ] XSS prevention
- [ ] CSRF protection
- [ ] Authentication required
- [ ] Rate limiting implemented
- [ ] Error messages don't expose internals

**Secure API Handler Example**:

```python
@router.post("/trade/execute", response_model=TradeResponse)
async def execute_trade(request: TradeRequest, user: User = Depends(get_current_user)):
    validate_trade_request(request)
    await rate_limiter.throttle(user.id)

    try:
        result = await agent_service.execute_trade(request, user.id)
    except RiskViolation as exc:
        logger.warning(
            "trade_rejected",
            user_id=user.id,
            symbol=request.symbol,
            reason=str(exc),
            correlation_id=request.correlation_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trade rejected by risk manager.",
        ) from exc
    return result
```

The snippet demonstrates secret-free configuration, dependency-injected authentication, input validation, rate limiting, and structured logging inside a single FastAPI endpoint.

---

## Performance Standards

### Performance Targets

- **API Response Time**: p95 < 200ms
- **WebSocket Latency**: < 50ms
- **Database Queries**: < 100ms
- **Feature Computation**: < 500ms
- **Model Inference**: < 1000ms

### Optimization Guidelines

- Use caching appropriately
- Optimize database queries
- Minimize network calls
- Use async/await for I/O
- Profile before optimizing

---

## Operational Command Guidelines

The JackSparrow command toolkit lives under `tools/commands/`. Use the following guidance when operating the project locally or in shared environments:

- **`start`** (`./tools/commands/start.sh`, `start.ps1`, or `python tools/commands/start_parallel.py`)
  - Launch before every development session
  - Uses parallel process manager to start all services simultaneously
  - Confirms backend, agent, and frontend are reachable on `localhost`
  - Streams real-time color-coded logs to console and writes to `logs/{service}.log`
  - Automatically sets up virtual environments and installs dependencies if needed
- **`restart`** (`./tools/commands/restart.sh` or `restart.ps1`)
  - Trigger after changing environment variables, dependencies, or configuration files
  - Performs a clean shutdown and relaunch; review `logs/restart.log` afterwards
- **`audit`** (`./tools/commands/audit.sh` or `audit.ps1`)
  - Run before opening pull requests, cutting releases, or after major refactors
  - Attach `logs/audit/report.md` to the PR/issue when findings require discussion
- **`error`** (`./tools/commands/error.sh` or `error.ps1`)
  - Execute when diagnosing runtime issues; share `logs/error/error-dump-<timestamp>.md` with the team if escalation is needed

Always bootstrap logging before running the commands (see [Logging Documentation](12-logging.md)) and clean up artefacts according to the retention policy.

---

## ML Model Management Standards

### Model File Organization

**Directory Structure**:
- **All models**: Stored under `agent/model_storage/` (discovered automatically; dated bundles often live in subfolders such as `jacksparrow_v15_BTCUSD_<date>/`).
- **Default pipeline bundle (typical Docker)**: `agent/model_storage/jacksparrow_v15_BTCUSD_<date>/{5m,15m}/` — `metadata_BTCUSD_*.json` + `pipeline_*_v14.pkl`; see [ML models](03-ml-models.md#bundle-profiles-and-docker-defaults).
- XGBoost models may also live under `agent/model_storage/xgboost/` (examples in docs).
- User-uploaded models go in `agent/model_storage/custom/`.
- Model-specific directories for organized storage (xgboost/, lstm/, transformer/) as needed.

**Environment Variables**:
- `MODEL_DIR` / `AGENT_MODEL_DIR`: Root or bundle folder for discovery (e.g. `./agent/model_storage` or a specific `jacksparrow_v15_BTCUSD_<date>` path).
- `MODEL_FORMAT`: `auto`, `v15_pipeline`, or `v4_ensemble` — selects how `metadata_BTCUSD_*.json` maps to a loader (`PipelineV15Node` vs `V4EnsembleNode`). See [ML models](03-ml-models.md#jacksparrow-v15-pipeline-5m--15m-joblib).

**File Naming**:
- Use semantic versioning: `model_name_v1.0.0.pkl`
- Include model type in filename when possible
- Keep filenames descriptive and consistent

### Model Metadata Standards

**Required Metadata Fields**:
- `model_name`: Unique identifier
- `model_type`: Model type (xgboost, lstm, transformer, etc.)
- `version`: Semantic version (MAJOR.MINOR.PATCH)
- `features_required`: List of required feature names
- `description`: Model description

**Optional Metadata Fields**:
- `author`: Model creator
- `created_at`: Creation timestamp
- `performance_metrics`: Model performance data
- `training_data`: Training data information

### Model Implementation Standards

**MCP Model Protocol Compliance**:
- All models must implement `MCPModelNode` interface
- Predictions must be normalized to -1.0 to +1.0 range
- Must provide human-readable reasoning/explanations
- Must include confidence scores
- Must track feature importance

**Model Node Requirements**:
```python
class CustomModelNode(MCPModelNode):
    """Custom model must implement MCPModelNode."""
    
    @property
    def model_name(self) -> str:
        """Return model identifier."""
        pass
    
    async def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        """Generate prediction following MCP Model Protocol."""
        pass
    
    def get_model_info(self) -> Dict:
        """Return model capabilities and requirements."""
        pass
```

### Model Versioning Standards

**Semantic Versioning**:
- **MAJOR**: Breaking changes, incompatible API
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

**Version Management**:
- Keep old versions for rollback capability
- Document version changes in metadata
- Test new versions before activation
- Maintain version history

### Model Testing Standards

**Before Upload**:
- Test model locally with sample data
- Verify prediction format matches MCP protocol
- Check feature requirements are met
- Validate metadata.json is complete

**After Upload**:
- Verify model is discovered correctly
- Test model registration with registry
- Validate predictions are generated
- Check model health status

For detailed model management documentation, see [ML Models Documentation](03-ml-models.md).

---

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - MCP architecture and protocols
- [ML Models Documentation](03-ml-models.md) - Model management and intelligence
- [Architecture Documentation](01-architecture.md) - System design
- [File Structure Documentation](08-file-structure.md) - Project organization
- [Deployment Documentation](10-deployment.md) - Setup instructions
- [Logging Documentation](12-logging.md) - Centralized logging standards
- [Build Guide](11-build-guide.md) - Build instructions
- [Backend Documentation](06-backend.md) - API implementation
- [Frontend Documentation](07-frontend.md) - Frontend implementation

