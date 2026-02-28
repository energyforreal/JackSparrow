# Features Documentation

## Overview

**JackSparrow** is a comprehensive AI-powered trading agent designed for paper trading on Delta Exchange India. This document outlines all features and capabilities of the system.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Core Trading Agent Features](#core-trading-agent-features)
- [Feature Categories](#feature-categories)
- [Feature Roadmap](#feature-roadmap)
- [Feature Dependencies](#feature-dependencies)
- [Related Documentation](#related-documentation)

---

## Core Trading Agent Features

### 1. Autonomous Market Analysis

**Description**: The agent continuously monitors and analyzes market conditions without human intervention.

**Capabilities**:
- Real-time market data ingestion from Delta Exchange
- Continuous monitoring of BTCUSD (extensible to other symbols)
- Automatic detection of market regime changes
- Volatility and volume analysis
- Anomaly detection in market data

**Key Components**:
- Market Data Service
- Feature Engineering Pipeline
- Market Regime Classifier

---

### 2. AI Reasoning Capabilities

**Description**: The agent uses structured reasoning chains to make decisions, not just simple rule-based logic.

**6-Step Reasoning Process**:

1. **Situational Assessment**
   - Analyzes current market conditions
   - Identifies market regime (bull trending, bear trending, ranging, high volatility)
   - Detects anomalies and unusual patterns
   - Assesses data quality

2. **Historical Context Retrieval**
   - Searches vector memory for similar past situations
   - Analyzes outcomes of similar historical decisions
   - Extracts insights from past experiences
   - Identifies novel situations

3. **Model Consensus Analysis**
   - Aggregates predictions from multiple ML models
   - Calculates weighted consensus
   - Assesses model agreement level
   - Identifies conflicting signals

4. **Risk Assessment**
   - Evaluates portfolio heat (% of capital at risk)
   - Checks consecutive losses
   - Assesses volatility risk
   - Reviews model confidence levels
   - Calculates risk-adjusted position sizes

5. **Decision Synthesis**
   - Weighs all factors together
   - Considers market context, model predictions, historical patterns, and risks
   - Generates final recommendation (BUY, SELL, HOLD)
   - Determines optimal position size

6. **Confidence Calibration**
   - Adjusts confidence based on historical accuracy
   - Calibrates by market regime
   - Provides realistic probability estimates
   - Accounts for overconfidence

**Output**: Complete reasoning chain with explanations for transparency

**Example Scenario**:

> Current market: BTCUSD trading at $51,240 with rising volume.<br>
> Recent wins: 4 out of last 5 trades, portfolio heat at 0.22.<br>
> Outcome: The agent moves from **OBSERVING** → **THINKING** → **DELIBERATING**, reaches a BUY recommendation with a 0.68 consensus confidence, and allocates 4.5% of capital after applying regime-aware risk modifiers.

The example illustrates how raw market context, historical success rate, and model consensus interact to produce the final signal and position size.

---

### 3. Multi-Model Ensemble System

**Description**: Uses multiple ML models working together to generate more robust predictions.

**Model Portfolio**:

1. **XGBoost**
   - Primary predictor for trend identification
   - Fast inference time
   - Good for non-linear patterns
   - SHAP-based explanations

2. **LightGBM**
   - Fast inference for short-term signals
   - Efficient memory usage
   - Good for large feature sets

3. **LSTM (Long Short-Term Memory)**
   - Sequence learning for pattern recognition
   - Captures temporal dependencies
   - Good for trend continuation patterns

4. **Transformer**
   - Attention-based long-term dependencies
   - Captures complex relationships
   - State-of-the-art performance

5. **Random Forest**
   - Robust baseline model
   - Provides diversification
   - Good for feature importance

**Consensus Mechanism**:
- Weighted voting based on model performance
- Performance-adjusted weights (Sharpe ratio based)
- Confidence-weighted aggregation
- Requires 60% weighted consensus for execution
- Handles model failures gracefully

**Dynamic Weight Adjustment**:
- Models weighted by recent performance
- Exponential moving average of performance metrics
- Minimum weight to keep models active
- Automatic weight updates after each trade

---

### 4. Learning and Adaptation System

> **Status**: Disabled for the current lightweight build. The architecture remains documented for future use, but the runtime intentionally skips all adaptive learning steps to keep compute requirements minimal.

**Description**: (Paused) The agent previously learned from every trade outcome and continuously improved.

**Learning Components**:

**Performance Tracking**:
- Win rate by signal strength
- Average return by model contribution
- Drawdown attribution per model
- Prediction accuracy metrics
- Sharpe ratio tracking

**Model Weight Updates**:
- Dynamic weight adjustment based on recent performance
- Performance window: last 100 trades
- Considers both accuracy and Sharpe ratio
- Prevents over-weighting single models

**Strategy Adaptation**:
- Adjusts position sizing based on performance
- Modifies signal thresholds
- Adapts stop loss levels
- Changes holding period limits
- Reduces risk after consecutive losses

**Confidence Calibration**:
- Tracks actual success rate for each confidence level
- Adjusts future confidence predictions
- Separate calibration by market regime
- Prevents overconfidence

**Memory Storage**:
- Stores every decision in vector memory
- Creates embeddings for similarity search
- Enables retrieval of similar past situations
- Supports continuous learning

**Learning Reports**:
- Key lessons extracted from each trade
- Model performance changes
- Strategy adaptations made
- Confidence calibration updates

---

### 5. Risk Management Features

**Description**: Comprehensive risk management to protect capital and ensure sustainable trading.

**Risk Components**:

**Position Sizing**:
- Kelly Criterion for optimal sizing
- Maximum position: 10% of portfolio per trade
- Risk-adjusted sizing based on signal strength
- Volatility-adjusted position sizes

**Portfolio Heat Monitoring**:
- Tracks % of capital at risk
- Prevents over-exposure
- Circuit breakers when heat exceeds limits
- Real-time risk metrics

**Stop Loss Management**:
- Volatility-adjusted stop losses
- Dynamic stop loss levels
- Tighter stops in high volatility
- Position-specific risk limits

**Circuit Breakers**:
- Automatic trading halt after consecutive losses
- Portfolio protection at drawdown thresholds
- Service failure protection
- Manual emergency stop capability

**Risk Metrics**:
- Real-time portfolio heat calculation
- Maximum drawdown tracking
- Sharpe ratio monitoring
- Sortino ratio calculation
- Value at Risk (VaR) estimation

---

### 6. Real-Time Monitoring

**Description**: Comprehensive monitoring and observability for system health and performance.

**Monitoring Features**:

**Agent State Monitoring**:
- Current agent state with enhanced state machine
- State transition history
- Time in current state
- State change reasons

**Agent States**:
- `INITIALIZING` - Loading models and connecting to services
- `OBSERVING` - Passively monitoring market conditions
- `THINKING` - Active analysis in progress (processing reasoning chain)
- `DELIBERATING` - Weighing decision options
- `ANALYZING` - Processing signals and evaluating entry conditions
- `EXECUTING` - Placing or managing trade orders
- `MONITORING_POSITION` - Active position management with real-time exit condition monitoring
  - Monitors stop loss and take profit levels on each market tick
  - Automatically triggers exit trades when conditions are met
  - Tracks position PnL and duration
  - Transitions to OBSERVING when position is closed
- `DEGRADED` - Partial functionality due to service issues
- `EMERGENCY_STOP` - Critical failure, no trading allowed

**Health Checks**:
- Numerical health score (0.0 to 1.0)
- Component-specific status
- Service latency measurements
- Degradation reasons
- Automatic health monitoring

**Performance Metrics**:
- Real-time portfolio value
- Unrealized PnL tracking
- Realized PnL history
- Win rate statistics
- Trade count and frequency

**Model Performance Tracking**:
- Individual model accuracy
- Model inference latency
- Model error rates
- Model weight changes
- Model health status

**System Metrics**:
- API response times
- WebSocket connection status
- Database query performance
- Feature computation latency
- Memory and CPU usage

**Alerting**:
- Health degradation alerts
- Trade execution notifications
- Error alerts with correlation IDs
- Performance threshold alerts

**Operational Commands**:
- `start`: Launch backend, agent, and frontend together – see [Build Guide](11-build-guide.md#project-commands)
- `restart`: Perform a clean restart when configuration or dependencies change – see [Deployment Documentation](10-deployment.md#operations--maintenance-commands)
- `audit`: Run full quality gate and log review before releases – see [Audit Report](15-audit-report.md#running-the-audit-command)
- `error`: Capture live diagnostics and recent log highlights – see [Backend Documentation](06-backend.md#command-operations)

---

### 7. Decision Explanation and Transparency

**Description**: Every decision is fully explained with reasoning chains and model explanations.

**Explanation Features**:

**Reasoning Chain Display**:
- Complete 6-step reasoning process
- Each step shows thought process
- Evidence tracking for each step
- Confidence levels per step
- Final conclusion with rationale

**Model Explanations**:
- SHAP-based feature importance
- Human-readable reasoning for each model
- Top contributing features identified
- Feature contribution values
- Model-specific explanations

**Decision Context**:
- Market conditions at decision time
- Portfolio state when decision made
- Risk factors considered
- Historical context used
- Model consensus details

**Transparency Features**:
- Full decision audit trail
- Reasoning chain storage
- Model predictions logged
- Context preserved for learning
- Queryable decision history

---

### 8. Paper Trading Execution

**Description**: Safe paper trading on Delta Exchange India without real money risk.

**Execution Features**:

**Order Management**:
- Market and limit order support
- Order status tracking
- Execution price recording
- Slippage modeling
- Order rejection handling

**Position Management**:
- Real-time position tracking
- Entry and exit price recording
- Position duration monitoring
- Unrealized PnL calculation
- Position size management
- Automatic stop loss and take profit monitoring
- Exit condition evaluation on each market tick
- Automatic position closure when exit conditions met

**Trade Logging**:
- Complete trade history
- Decision context for each trade
- Reasoning chain storage
- Outcome recording
- Performance attribution

**Delta Exchange Integration**:
- REST API integration
- Circuit breaker protection
- Retry logic with exponential backoff
- Health monitoring
- Error handling

---

### 9. WebSocket Real-Time Updates

**Description**: Real-time communication between backend and frontend for live updates.

**Update Types**:

**Agent State Updates**:
- State changes broadcast immediately
- Current state with timestamp
- State change reasons
- State duration information

**Trade Execution Updates**:
- New trade notifications
- Trade details (symbol, side, price, quantity)
- Order status changes
- Execution confirmations

**Portfolio Updates**:
- Portfolio value changes
- Unrealized PnL updates
- Position changes
- Cash balance updates

**Health Status Updates**:
- Health score changes
- Component status updates
- Degradation notifications
- Recovery notifications

**Prediction Updates**:
- New prediction generated
- Reasoning chain available
- Model predictions updated
- Signal changes

**WebSocket Features**:
- Automatic reconnection
- Exponential backoff
- Message queuing during disconnection
- Subscription management
- Dead connection cleanup

---

### 10. Operational Command Suite

**Description**: Project-level commands simplify day-to-day operations and maintenance.

**Command Overview**:
- `python tools/commands/start_parallel.py`: Launches backend, agent, and frontend services from the project root. Verifies service dependencies (PostgreSQL, Redis, optional Qdrant) before starting. Also available as `./tools/commands/start.sh` (Linux/macOS) or `.\tools\commands\start.ps1` (Windows).
- `./tools/commands/restart.sh` or `.\tools\commands\restart.ps1`: Performs a clean stop followed by restart. Use it after changing configuration, dependencies, or environment variables.
- `./tools/commands/audit.sh` or `.\tools\commands\audit.ps1`: Runs formatting, linting, tests, service health checks, and log aggregation. Outputs detailed findings under `logs/audit/`.
- `./tools/commands/error.sh` or `.\tools\commands\error.ps1`: Performs a lightweight diagnostic pass—checks process health, tails recent logs, and highlights new warnings/errors.

**Operational Notes**:
- Command implementations live in `tools/commands/` directory with Python scripts and shell script wrappers.
- Logs generated by these commands are stored in the `logs/` directory (`start.log`, `restart/<timestamp>/`, `audit/`, `error/`).
- Audit reports complement the documentation in [docs/15-audit-report.md](15-audit-report.md), while troubleshooting steps reference [docs/10-deployment.md](10-deployment.md#operations--maintenance-commands).

---

### 11. Dashboard and Visualization

**Description**: Comprehensive web dashboard for monitoring and interaction.

**Dashboard Components**:

**Agent Status Display**:
- Current state indicator
- State history
- Last update timestamp
- Status messages

**Portfolio Summary**:
- Total portfolio value
- Cash vs positions breakdown
- Unrealized PnL
- Realized PnL
- Performance metrics

**Active Positions**:
- Current positions list
- Entry prices and times
- Current prices
- Unrealized PnL per position
- Position duration

**Recent Trades**:
- Last 10 trades
- Trade details
- PnL per trade
- Decision context links

**Signal Indicator**:
- Current signal (BUY/SELL/HOLD)
- Confidence level
- Model consensus breakdown
- Reasoning chain viewer

**Performance Charts**:
- Portfolio value over time
- PnL distribution
- Win rate trends
- Model performance comparison

**Health Monitor**:
- Overall health score
- Component status grid
- Service latencies
- Degradation reasons

**Reasoning Chain Viewer**:
- Expandable step-by-step reasoning
- Evidence display
- Confidence indicators
- Conclusion display

**Learning Reports**:
- (Paused) No new reports are generated while the learning loop is disabled.

---

## Feature Categories

### Core AI Features
- ✅ Autonomous market analysis
- ✅ Structured reasoning chains
- ✅ Multi-model ensemble
- ⚠️ Learning and adaptation (documented architecture, currently disabled)
- ✅ Confidence calibration
- ✅ Decision explanation

### Trading Features
- ✅ Paper trading execution
- ✅ Position management
- ✅ Order management
- ✅ Risk management
- ✅ Portfolio tracking

### Monitoring Features
- ✅ Real-time updates
- ✅ Health monitoring
- ✅ Performance tracking
- ✅ Alerting system
- ✅ Dashboard visualization
- ✅ Position impact preview (risk assessment for open positions)

#### Position Impact Preview

**Description**: Real-time risk assessment showing how price movements affect existing positions and total portfolio value.

**Capabilities**:
- **P&L Impact Calculation**: Shows dollar and percentage changes for each position
- **Risk Level Assessment**: Categorizes impact as low/medium/high/critical based on percentage change
- **Liquidation Risk Detection**: Alerts when stop-loss levels are approached
- **Portfolio Summary**: Aggregated impact across all positions
- **Visual Indicators**: Color-coded badges and icons for quick risk assessment

**Risk Levels**:
- **Low**: <2% position impact
- **Medium**: 2-5% position impact
- **High**: 5-10% position impact
- **Critical**: >10% position impact ⚠️

**Visual Feedback**:
- Green indicators for profitable impacts
- Red indicators for losses
- Risk level badges with appropriate colors
- Warning icons for liquidation risk

**Integration**: Seamlessly integrated into the RealTimePrice component, showing position impact alongside price change indicators.

### Technical Features
- ✅ MCP protocol integration
- ✅ WebSocket real-time communication
- ✅ Circuit breakers
- ✅ Graceful degradation
- ✅ Error handling
- ✅ Logging and observability

### Decision Support Matrix

| Capability Category   | Primary Modules                              | Key Outcome                                      |
|-----------------------|----------------------------------------------|--------------------------------------------------|
| Market Intelligence   | Market Data Service, Feature Server          | Fresh features, anomaly detection, and regime tagging |
| Decision Transparency | MCP Reasoning Engine, Reasoning Chain Viewer | Full audit trail for every recommendation        |
| Risk Management       | Risk Manager, Portfolio Heat Monitor         | Adaptive position sizing and drawdown protection |
| Learning & Adaptation | Learning System, Model Performance Tracker   | Continual weight adjustment and confidence calibration |
| User Communication    | FastAPI Backend, WebSocket layer, Frontend   | Real-time dashboards, alerts, and status updates |

---

## Feature Roadmap

### Current Phase (v1.0)
- ✅ Core trading agent functionality
- ✅ Multi-model ensemble
- ✅ Learning system
- ✅ Real-time dashboard
- ✅ Paper trading on Delta Exchange

### Future Enhancements
- 🔄 Additional trading symbols
- 🔄 Advanced order types (stop-loss, take-profit)
- 🔄 Portfolio optimization
- 🔄 Backtesting framework
- 🔄 Strategy templates
- 🔄 Mobile app interface
- 🔄 Telegram bot integration (optional - mobile notifications and commands)
- 🔄 Multi-exchange support

### Optional Features

**Telegram Interface** (Optional):
- Mobile notifications for trades and alerts *(backend support available; supply `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to enable outbound messages).*
- Command interface for manual controls *(future enhancement)*
- Status updates and monitoring
- Not required for core functionality
- Can be added as separate service if needed

---

## Feature Dependencies

### Critical Dependencies
- Delta Exchange API access
- Market data availability
- Model training data
- Database connectivity
- Redis cache availability

### Optional Dependencies
- Vector database (Qdrant/Pinecone) for memory
- Prometheus for metrics
- Grafana for visualization
- Telegram API for notifications

---

## Related Documentation

- [Architecture Documentation](01-architecture.md) - System design
- [Logic & Reasoning Documentation](05-logic-reasoning.md) - Decision-making process
- [Backend Documentation](06-backend.md) - API implementation
- [Frontend Documentation](07-frontend.md) - Dashboard implementation
- [UI/UX Documentation](09-ui-ux.md) - User interface design

