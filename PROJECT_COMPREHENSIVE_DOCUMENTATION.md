# JackSparrow Trading Agent - Comprehensive Project Documentation

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)  
**Project Name**: JackSparrow Trading Agent  
**Version**: Production Ready (2025-01-27)  
**Last Updated**: 2025-12-28

> **For the pirates who love treasure hunting, except for the fact that there is no water here. The treasure is sought out of thin air.**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Complete Functionalities](#complete-functionalities)
3. [System Architecture](#system-architecture)
4. [File Architecture](#file-architecture)
5. [Component Communication](#component-communication)
6. [Major Components](#major-components)
7. [Technology Stack](#technology-stack)
8. [Issues Faced and Solutions](#issues-faced-and-solutions)
9. [Development Workflow](#development-workflow)
10. [Deployment](#deployment)
11. [Testing](#testing)
12. [Performance Metrics](#performance-metrics)
13. [Future Enhancements](#future-enhancements)

---

## Project Overview

### What is JackSparrow?

JackSparrow is a **production-ready AI-powered autonomous trading agent** designed for paper trading on Delta Exchange India. Unlike simple trading bots, JackSparrow is a true AI agent that:

- **Autonomously analyzes** market data using multiple ML models
- **Makes intelligent decisions** based on structured reasoning chains
- **Executes trades** with proper risk management
- **Learns and adapts** from trading outcomes
- **Communicates status** clearly through integrated interfaces

### Key Characteristics

- **Paper Trading Only**: Safe testing environment on Delta Exchange India
- **BTCUSD Focus**: Initially designed for BTCUSD trading across multiple timeframes (15m, 1h, 4h)
- **Multi-Model Ensemble**: Uses 6 XGBoost models (3 classifiers + 3 regressors) for consensus-based predictions
- **Real-Time Processing**: WebSocket-based real-time data ingestion and decision making
- **Production Ready**: Full Docker containerization, CI/CD pipeline, comprehensive monitoring

### Project Goals

1. **Autonomous Trading**: Make trading decisions without human intervention
2. **Risk Management**: Protect capital through proper position sizing and stop losses
3. **Transparency**: Provide clear reasoning chains for every decision
4. **Learning**: Adapt and improve from trading outcomes
5. **Reliability**: Production-grade error handling and monitoring

---

## Complete Functionalities

### 1. Market Data Ingestion

**Purpose**: Real-time and historical market data collection from Delta Exchange

**Features**:
- **Continuous price monitoring**: Real-time BTCUSD ticker data (0.5-second polling intervals)
- **Fluctuation-based signal generation**: ML pipeline triggered on ≥0.5% price changes
- **Instant frontend updates**: Real-time price display updates on any price movement
- Historical OHLCV data retrieval for analysis
- Order book data fetching
- Circuit breaker protection for API failures
- Automatic retry with exponential backoff
- Data caching in Redis (60-second TTL)

**Implementation**:
- `agent/data/delta_client.py` - Delta Exchange API client
- `agent/data/market_data_service.py` - Market data service layer
- `backend/services/market_service.py` - Backend market data endpoints

**Data Flow**:
```
Delta Exchange API → Delta Client → Market Data Service → Feature Server → Agent Core
```

### 1.1 Signal Generation Behavior

**Overview**: JackSparrow uses fluctuation-based signal generation instead of time-based intervals for more responsive trading.

**Key Changes**:
- **Before**: Signals generated every 15 minutes (candle close events)
- **After**: Signals generated on ≥0.5% BTCUSD price fluctuations

**Configuration**:
- `PRICE_FLUCTUATION_THRESHOLD_PCT`: Threshold for triggering ML pipeline (default: 0.5%)
- `FAST_POLL_INTERVAL`: Price monitoring frequency (default: 0.5 seconds)

**Benefits**:
- **Responsive**: Captures major market moves immediately
- **Adaptive**: Frequency adjusts automatically to market volatility
- **Efficient**: Reduces unnecessary computation during stable periods
- **Real-time UI**: Frontend shows instant price updates regardless of signal generation

**Event Flow**:
```
Price Change ≥0.5% → PriceFluctuationEvent → Feature Computation → ML Models → Reasoning → Decision
```

### 2. Feature Engineering

**Purpose**: Compute technical indicators and ML features from raw market data

**Features**:
- **Technical Indicators**: RSI, MACD, Bollinger Bands, Moving Averages, Volume indicators
- **Feature Versioning**: Semantic versioning (e.g., "1.2.3") for feature definitions
- **Quality Monitoring**: Automatic quality assessment (HIGH, MEDIUM, LOW, DEGRADED)
- **MCP Feature Protocol**: Standardized feature communication interface
- **Caching**: Feature caching for performance optimization

**Implementation**:
- `agent/data/feature_engineering.py` - Feature computation logic
- `agent/data/feature_server.py` - MCP Feature Server

**Quality Assessment**:
- **HIGH**: < 1% missing data, fresh data (< 5 seconds old)
- **MEDIUM**: 1-5% missing data, slightly stale (< 30 seconds old)
- **LOW**: > 5% missing data or stale (> 30 seconds old)
- **DEGRADED**: Significant quality issues, may affect predictions

### 3. ML Model Inference

**Purpose**: Generate trading predictions using ensemble of ML models

**Features**:
- **Model Discovery**: Automatic discovery of models in `agent/model_storage/`
- **Multi-Model Ensemble**: Parallel inference across multiple models
- **Consensus Calculation**: Weighted consensus from all models
- **SHAP Explanations**: Human-readable explanations for predictions
- **Model Health Monitoring**: Track model performance and health status
- **MCP Model Protocol**: Standardized model communication interface

#### ML Model File Structure

**Storage Location**: `agent/model_storage/`

**Directory Structure**:
```
agent/model_storage/
├── xgboost/                          # XGBoost models
│   ├── xgboost_classifier_BTCUSD_15m.pkl
│   ├── xgboost_classifier_BTCUSD_1h.pkl
│   ├── xgboost_classifier_BTCUSD_4h.pkl
│   ├── xgboost_regressor_BTCUSD_15m.pkl
│   ├── xgboost_regressor_BTCUSD_1h.pkl
│   └── xgboost_regressor_BTCUSD_4h.pkl
├── lightgbm/                        # LightGBM models (if available)
│   └── *.pkl
├── random_forest/                   # Random Forest models (if available)
│   └── *.pkl
├── lstm/                            # LSTM models (TensorFlow/Keras)
│   └── *.h5
├── transformer/                     # Transformer models
│   └── *.onnx
└── custom/                          # User-uploaded models
    ├── *.pkl                        # Pickle models
    ├── *.h5                         # TensorFlow/Keras models
    ├── *.onnx                       # ONNX models
    └── metadata.json                # Model metadata
```

**Environment Configuration**:
- `MODEL_DIR=./agent/model_storage` - Points to model storage directory
- `MODEL_DISCOVERY_ENABLED=true` - Enable automatic discovery
- `MODEL_AUTO_REGISTER=true` - Auto-register discovered models
- `MODEL_PATH` (optional) - Specific model file path (takes precedence)

#### Model Discovery Process

**How Models are Discovered**:

1. **On Agent Startup**: `IntelligentAgent.initialize()` calls `ModelDiscovery.discover_models()`

2. **Discovery Flow**:
   ```
   Agent Startup
   ↓
   ModelDiscovery.discover_models()
   ↓
   Scan MODEL_DIR (agent/model_storage/)
   ↓
   Search Subdirectories:
   - xgboost/
   - lightgbm/
   - random_forest/
   - lstm/
   - transformer/
   - custom/
   ↓
   Find Model Files:
   - *.pkl (XGBoost, LightGBM, scikit-learn)
   - *.h5, *.keras (TensorFlow/Keras)
   - *.onnx (ONNX models)
   ↓
   Detect Model Type:
   - File extension (.pkl → XGBoost/LightGBM)
   - Directory name (xgboost/ → XGBoost)
   - Metadata file (metadata.json)
   ↓
   Load Model:
   - XGBoost: pickle.load()
   - LightGBM: pickle.load()
   - TensorFlow: tf.keras.models.load_model()
   - ONNX: onnxruntime.InferenceSession()
   ↓
   Create Model Node:
   - XGBoostNode for XGBoost models
   - LightGBMNode for LightGBM models
   - LSTMNode for LSTM models
   - TransformerNode for Transformer models
   ↓
   Register in MCPModelRegistry:
   - Store model node
   - Initialize model weights
   - Track model metadata
   ↓
   Model Ready for Inference
   ```

3. **Model Loading**:
   - Models are loaded into memory on discovery
   - Each model wrapped in `MCPModelNode` interface
   - Model metadata extracted (name, version, type, features)
   - Health status initialized to "healthy"

4. **Registration**:
   - Models registered in `MCPModelRegistry`
   - Equal weights assigned initially (1/N for N models)
   - Weights adjusted by learning system based on performance

**Implementation Files**:
- `agent/models/model_discovery.py` - Model discovery logic
- `agent/models/mcp_model_registry.py` - Model registry
- `agent/models/mcp_model_node.py` - Base model interface
- `agent/models/xgboost_node.py` - XGBoost implementation
- `agent/models/lightgbm_node.py` - LightGBM implementation
- `agent/models/random_forest_node.py` - Random Forest implementation

#### Model Types Supported

**1. XGBoost Models** (Currently Integrated):
- **File Format**: `.pkl` (Pickle)
- **Storage**: `agent/model_storage/xgboost/`
- **Types**:
  - **Classifier**: Predicts trading signals directly (BUY/SELL/HOLD)
    - Training target: Signal labels based on return thresholds
    - Output: Class probabilities normalized to [-1, 1]
  - **Regressor**: Predicts absolute future prices
    - Training target: Future close prices (absolute values)
    - Output: Absolute prices converted to relative returns, normalized to [-1, 1]
- **Implementation**: `XGBoostNode` class
- **Auto-Detection**: Detects classifier vs regressor from model type

**2. LightGBM Models**:
- **File Format**: `.pkl` (Pickle)
- **Storage**: `agent/model_storage/lightgbm/`
- **Implementation**: `LightGBMNode` class
- **Usage**: Similar to XGBoost, supports both classifier and regressor

**3. Random Forest Models**:
- **File Format**: `.pkl` (Pickle)
- **Storage**: `agent/model_storage/random_forest/`
- **Implementation**: `RandomForestNode` class
- **Usage**: scikit-learn Random Forest models

**4. LSTM Models** (TensorFlow/Keras):
- **File Format**: `.h5` or `.keras` (HDF5)
- **Storage**: `agent/model_storage/lstm/`
- **Implementation**: `LSTMNode` class
- **Usage**: Time-series sequence models for price prediction

**5. Transformer Models**:
- **File Format**: `.onnx` (ONNX Runtime)
- **Storage**: `agent/model_storage/transformer/`
- **Implementation**: `TransformerNode` class
- **Usage**: Attention-based models for sequence prediction

**Current Models** (As of Latest Integration):
- **6 XGBoost Models**:
  - 3 Classifier models (15m, 1h, 4h timeframes)
  - 3 Regressor models (15m, 1h, 4h timeframes)
- **Location**: `agent/model_storage/xgboost/`
- **Auto-Discovered**: Yes, on agent startup

#### Model Inference Flow

**Prediction Request Flow**:
```
Reasoning Engine
↓
MCP Orchestrator.get_predictions()
↓
MCP Model Registry.get_predictions()
↓
For each registered model:
  ├─ Check model health
  ├─ Check model is active
  ├─ Prepare features
  ├─ Call model.predict()
  ├─ Generate SHAP explanations
  └─ Return MCPModelPrediction
↓
Calculate Consensus:
  ├─ Weighted average of predictions
  ├─ Agreement level calculation
  └─ Confidence aggregation
↓
Return MCPModelResponse
```

**Prediction Format**:
- Normalized to [-1.0, +1.0] range
- -1.0 = Strong Sell
- 0.0 = Hold
- +1.0 = Strong Buy
- Confidence score: 0.0 to 1.0
- SHAP explanations included for transparency

### 4. Reasoning Engine

**Purpose**: Generate structured reasoning chains for transparent decision-making

**Features**:
- **6-Step Reasoning Chain**:
  1. **Situational Assessment**: Analyze current market conditions
  2. **Historical Context Retrieval**: Retrieve similar past situations
  3. **Model Consensus Analysis**: Aggregate model predictions
  4. **Risk Assessment**: Evaluate portfolio and market risks
  5. **Decision Synthesis**: Synthesize final trading decision
  6. **Confidence Calibration**: Calibrate confidence based on evidence
- **MCP Reasoning Protocol**: Standardized reasoning chain format
- **Evidence Tracking**: Track all evidence used in reasoning
- **Decision Traceability**: Full audit trail for every decision

**Implementation**:
- `agent/core/reasoning_engine.py` - Reasoning engine implementation
- `agent/core/mcp_orchestrator.py` - MCP orchestration layer

**Reasoning Chain Structure**:
```json
{
  "chain_id": "chain_123",
  "timestamp": "2025-01-12T10:30:00Z",
  "steps": [
    {
      "step_number": 1,
      "step_name": "Situational Assessment",
      "thought": "Market regime: bull_trending...",
      "evidence": ["feature:rsi_14=65.2", "feature:macd_signal=0.5"],
      "confidence": 0.85
    },
    // ... 5 more steps
  ],
  "conclusion": "After analyzing all factors...",
  "final_confidence": 0.75
}
```

### 5. Risk Management

**Purpose**: Protect capital through proper risk controls

**Features**:
- **Position Sizing**: Kelly Criterion-based position sizing
- **Stop Loss Management**: Volatility-adjusted stop losses
- **Take Profit Targets**: Risk-reward ratio-based targets
- **Portfolio Heat Monitoring**: Track portfolio risk exposure
- **Circuit Breakers**: Automatic trading halt on excessive losses
- **Risk Limit Enforcement**: Enforce maximum position sizes and portfolio limits

**Implementation**:
- `agent/risk/risk_manager.py` - Risk management logic
- `agent/risk/position_sizer.py` - Position sizing calculations

**Risk Controls**:
- Maximum position size: 5% of portfolio
- Maximum portfolio heat: 20%
- Stop loss: 2% default (volatility-adjusted)
- Take profit: 4% default (2:1 risk-reward ratio)
- Circuit breaker: Halt trading after 3 consecutive losses

### 6. Trade Execution

**Purpose**: Execute trades on Delta Exchange with proper order management

**Features**:
- **Order Placement**: Place market and limit orders
- **Order Tracking**: Track order status and fills
- **Position Management**: Manage open positions with stop loss/take profit
- **Exit Logic**: Automatic exit on stop loss, take profit, or signal reversal
- **Paper Trading**: Simulated execution (no real money)
- **PnL Calculation**: Real-time profit/loss tracking

**Implementation**:
- `agent/core/execution.py` - Trade execution engine
- `agent/core/state_machine.py` - Agent state machine

**Execution Flow**:
```
Decision Ready → Risk Validation → Order Placement → Order Fill → Position Monitoring → Exit Decision → Position Close
```

### 7. Learning System

**Purpose**: Learn from trading outcomes and adapt strategy

**Features**:
- **Performance Tracking**: Track model performance over time
- **Model Weight Adjustment**: Dynamically adjust model weights based on performance
- **Confidence Calibration**: Calibrate confidence scores based on historical accuracy
- **Strategy Adaptation**: Adjust strategy parameters based on market conditions
- **Memory Storage**: Store decision contexts in vector memory store

**Implementation**:
- `agent/learning/performance_tracker.py` - Performance tracking
- `agent/learning/model_weight_adjuster.py` - Model weight updates
- `agent/learning/confidence_calibrator.py` - Confidence calibration
- `agent/learning/strategy_adapter.py` - Strategy adaptation
- `agent/memory/vector_store.py` - Vector memory storage

**Learning Metrics**:
- Model accuracy per timeframe
- Win rate and profit factor
- Sharpe ratio and maximum drawdown
- Confidence calibration accuracy

### 8. State Management

**Purpose**: Track agent state and portfolio status

**Features**:
- **Agent State Machine**: 8 distinct states (INITIALIZING, OBSERVING, THINKING, DELIBERATING, ANALYZING, EXECUTING, MONITORING_POSITION, DEGRADED, EMERGENCY_STOP)
- **Portfolio Tracking**: Track cash, positions, PnL, and performance metrics
- **Position Tracking**: Track open positions with entry price, current price, PnL
- **Trade History**: Store all executed trades with full details
- **State Persistence**: Persist state to database for recovery

**Implementation**:
- `agent/core/state_machine.py` - State machine implementation
- `agent/core/context_manager.py` - Context and state management
- `backend/services/portfolio_service.py` - Portfolio calculations

**Agent States**:
- **INITIALIZING**: System startup and initialization
- **OBSERVING**: Monitoring markets without active analysis
- **THINKING**: Generating reasoning chain
- **DELIBERATING**: Evaluating decision options
- **ANALYZING**: Analyzing signals and predictions
- **EXECUTING**: Executing trades
- **MONITORING_POSITION**: Monitoring open positions
- **DEGRADED**: Operating with reduced capabilities
- **EMERGENCY_STOP**: Trading halted due to critical issues

### 9. Real-Time Communication

**Purpose**: Provide real-time updates to frontend dashboard

**Features**:
- **WebSocket Server**: Real-time bidirectional communication
- **Event Broadcasting**: Broadcast agent events to all connected clients
- **Message Types**: Agent state, signals, reasoning chains, trades, portfolio updates
- **Automatic Reconnection**: Exponential backoff reconnection logic
- **Message Queuing**: Queue messages during disconnection
- **Data Freshness**: Timestamp tracking for data freshness

**Implementation**:
- `backend/api/websocket/manager.py` - WebSocket connection manager
- `frontend/hooks/useWebSocket.ts` - Frontend WebSocket hook
- `agent/api/websocket_server.py` - Agent WebSocket server

**Message Types**:
- `agent_state` - Agent state updates
- `signal_update` - Trading signal updates (BUY/SELL/HOLD)
- `reasoning_chain_update` - Reasoning chain updates
- `model_prediction_update` - ML model prediction updates
- `market_tick` - Real-time price updates
- `trade_executed` - Trade execution notifications
- `portfolio_update` - Portfolio value changes
- `health_update` - Health status changes

### 10. Frontend Dashboard

**Purpose**: User interface for monitoring and interacting with the trading agent

**Features**:
- **Real-Time Dashboard**: Live updates via WebSocket
- **Agent Status Display**: Visual agent state indicator
- **Portfolio Summary**: Portfolio value, cash, positions, PnL
- **Active Positions**: List of open positions with real-time PnL
- **Recent Trades**: Trade history with details
- **Signal Indicator**: Current trading signal display
- **Reasoning Chain Viewer**: Visualize AI reasoning process
- **Performance Charts**: Performance metrics visualization
- **Health Monitor**: System health status display
- **Learning Report**: Agent learning insights

#### Frontend Architecture

**Technology Stack**:
- **Framework**: Next.js 14+ (App Router)
- **Language**: TypeScript 5.0+
- **UI Library**: React 18.0+
- **Styling**: Tailwind CSS 3.0+
- **State Management**: React Hooks (useState, useEffect, useContext)
- **WebSocket**: Native WebSocket API with custom hook
- **API Client**: Fetch API with typed wrappers
- **Testing**: Jest + React Testing Library

**File Structure**:
```
frontend/
├── app/                              # Next.js App Router
│   ├── layout.tsx                   # Root layout (providers, metadata)
│   ├── page.tsx                     # Main dashboard page
│   ├── components/                  # React components
│   │   ├── Dashboard.tsx            # Main dashboard container
│   │   ├── AgentStatus.tsx          # Agent state indicator
│   │   ├── PortfolioSummary.tsx    # Portfolio overview
│   │   ├── ActivePositions.tsx      # Open positions list
│   │   ├── RecentTrades.tsx         # Trade history
│   │   ├── SignalIndicator.tsx     # Trading signal display
│   │   ├── PerformanceChart.tsx    # Performance visualization
│   │   ├── HealthMonitor.tsx       # System health display
│   │   ├── ReasoningChainView.tsx  # AI reasoning viewer
│   │   ├── LearningReport.tsx      # Learning insights
│   │   ├── ErrorBoundary.tsx       # Error handling
│   │   └── SystemClock.tsx         # Synchronized time display
│   └── globals.css                  # Global styles
├── hooks/                            # Custom React hooks
│   ├── useWebSocket.ts              # WebSocket connection hook
│   ├── useAgent.ts                  # Agent state management
│   ├── usePortfolio.ts              # Portfolio data hook
│   └── usePredictions.ts            # Prediction data hook
├── services/                         # Service layer
│   ├── api.ts                       # REST API client
│   └── websocket.ts                 # WebSocket client
├── types/                            # TypeScript type definitions
│   └── index.ts                     # Shared types
├── utils/                            # Utility functions
│   ├── formatters.ts                # Data formatting (currency, dates, percentages)
│   └── calculations.ts              # Client-side calculations
└── package.json                     # Dependencies
```

#### Component Details

**1. Dashboard Component** (`app/components/Dashboard.tsx`):
- **Purpose**: Main container orchestrating all dashboard sections
- **Responsibilities**:
  - Layout management (grid/flex layout)
  - State coordination across child components
  - WebSocket connection management
  - Error boundary wrapping
  - Message routing and distribution
- **State Management**:
  - Agent state (from WebSocket)
  - Portfolio data (from WebSocket + API)
  - Recent trades (from WebSocket)
  - Health status (from WebSocket)
  - Reasoning chains (from WebSocket)
- **WebSocket Integration**:
  - Subscribes to all message types
  - Routes messages to appropriate child components
  - Handles reconnection automatically

**2. AgentStatus Component** (`app/components/AgentStatus.tsx`):
- **Purpose**: Display current agent state with visual indicators
- **Visual States**:
  - `INITIALIZING`: Gray - ⚙️ Initializing System
  - `OBSERVING`: Cyan - 👁️ Observing Markets
  - `THINKING`: Purple - 🧠 Thinking (Generating Reasoning)
  - `DELIBERATING`: Indigo - 🤔 Deliberating Decision
  - `ANALYZING`: Blue - 📊 Analyzing Signals
  - `EXECUTING`: Orange - ⚡ Executing Trade
  - `MONITORING_POSITION`: Amber - 📈 Monitoring Position
  - `DEGRADED`: Yellow - ⚠️ Degraded Performance
  - `EMERGENCY_STOP`: Red - 🚨 Emergency Stop
- **Features**:
  - Color-coded status badges
  - State-specific icons
  - Last update timestamp
  - Status messages
  - State transition animations

**3. PortfolioSummary Component** (`app/components/PortfolioSummary.tsx`):
- **Purpose**: Display portfolio overview with key metrics
- **Metrics Displayed**:
  - Total portfolio value
  - Cash vs positions breakdown
  - Unrealized PnL (color-coded: green/red)
  - Realized PnL
  - Percentage changes
  - Portfolio allocation chart
- **Real-Time Updates**: Updates automatically on portfolio changes

**4. ActivePositions Component** (`app/components/ActivePositions.tsx`):
- **Purpose**: Display list of currently open positions
- **Position Details**:
  - Symbol and side (BUY/SELL)
  - Entry price vs current price
  - Quantity and position value
  - Real-time PnL (color-coded)
  - Entry time and duration
  - Stop loss and take profit levels
- **Features**:
  - Real-time PnL updates
  - Sortable columns
  - Expandable position details
  - Close position button (if enabled)

**5. RecentTrades Component** (`app/components/RecentTrades.tsx`):
- **Purpose**: Display recent trade history
- **Trade Information**:
  - Trade ID and symbol
  - Entry and exit prices
  - Quantity and side
  - PnL (realized)
  - Entry and exit timestamps
  - Exit reason (stop loss, take profit, signal reversal)
- **Features**:
  - Paginated trade list
  - Filter by symbol, date range
  - Link to reasoning chain for each trade
  - Export functionality

**6. SignalIndicator Component** (`app/components/SignalIndicator.tsx`):
- **Purpose**: Display current AI prediction signal
- **Signal Display**:
  - Large signal badge (BUY/SELL/HOLD/STRONG_BUY/STRONG_SELL)
  - Color-coded by signal strength
  - Confidence bar visualization
  - Model consensus breakdown
  - Expandable reasoning display
- **Features**:
  - Confidence percentage display
  - Model-by-model prediction breakdown
  - Historical signal chart
  - Signal change notifications

**7. ReasoningChainView Component** (`app/components/ReasoningChainView.tsx`):
- **Purpose**: Visualize AI reasoning process for transparency
- **Display Format**:
  - Expandable step-by-step reasoning (6 steps)
  - Confidence indicators per step
  - Evidence badges for each step
  - Conclusion highlight
  - Model predictions used in reasoning
- **Features**:
  - Collapsible steps
  - Step numbers with icons
  - Confidence bars per step
  - Evidence tags
  - Copy-to-clipboard functionality
  - Export reasoning chain as JSON

**8. PerformanceChart Component** (`app/components/PerformanceChart.tsx`):
- **Purpose**: Visualize portfolio performance over time
- **Chart Types**:
  - Line chart of portfolio value
  - PnL overlay (positive/negative)
  - Drawdown visualization
- **Features**:
  - Period selector (1d, 7d, 30d, all)
  - Interactive tooltips
  - Zoom and pan functionality
  - Responsive design
  - Export chart as image

**9. HealthMonitor Component** (`app/components/HealthMonitor.tsx`):
- **Purpose**: Display system health status
- **Health Information**:
  - Overall health score (0-100%)
  - Service status grid (database, Redis, agent, Delta Exchange, etc.)
  - Latency indicators per service
  - Degradation reasons
  - Health history chart
- **Features**:
  - Color-coded status indicators
  - Service-specific health details
  - Alert notifications for degraded services
  - Health score trend visualization

**10. LearningReport Component** (`app/components/LearningReport.tsx`):
- **Purpose**: Display agent learning updates and adaptations
- **Learning Information**:
  - Key lessons learned
  - Model weight changes
  - Strategy adaptations
  - Performance improvements
- **Features**:
  - Visual indicators for changes
  - Model performance comparisons
  - Strategy change history
  - Learning insights timeline

#### State Management

**WebSocket State** (`hooks/useWebSocket.ts`):
- Connection status (connected/disconnected)
- Last received message
- Message queue (during disconnection)
- Subscribed channels
- Reconnection logic with exponential backoff

**Agent State** (`hooks/useAgent.ts`):
- Current agent state
- State transition history
- Agent status messages
- Last update timestamp

**Portfolio State** (`hooks/usePortfolio.ts`):
- Portfolio value and composition
- Cash and positions
- PnL (realized and unrealized)
- Performance metrics
- Trade history

**Prediction State** (`hooks/usePredictions.ts`):
- Current trading signal
- Model predictions
- Reasoning chains
- Confidence scores
- Signal history

#### WebSocket Integration

**Connection Management**:
- Automatic connection on component mount
- Reconnection with exponential backoff (1s → 30s max)
- Message queuing during disconnection
- Subscription management (subscribe/unsubscribe to channels)

**Message Types Handled**:
- `agent_state` - Agent state updates
- `signal_update` - Trading signal updates
- `reasoning_chain_update` - Reasoning chain updates
- `model_prediction_update` - ML model prediction updates
- `market_tick` - Real-time price updates
- `trade_executed` - Trade execution notifications
- `portfolio_update` - Portfolio value changes
- `health_update` - Health status changes

**Message Flow**:
```
WebSocket Connection
↓
Subscribe to Channels
↓
Receive Messages
↓
Parse Message Type
↓
Update Relevant State
↓
Trigger Component Re-render
↓
Display Updated Data
```

#### UI/UX Features

**Design Principles**:
- **Real-Time Updates**: All data updates automatically via WebSocket
- **Visual Feedback**: Color-coded indicators for status, PnL, health
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Accessibility**: ARIA labels, keyboard navigation support
- **Error Handling**: Graceful error display with retry options
- **Loading States**: Skeleton loaders during data fetching

**Color Scheme**:
- **Success/Positive**: Green (#10b981)
- **Warning/Degraded**: Yellow (#f59e0b)
- **Error/Negative**: Red (#ef4444)
- **Info/Neutral**: Blue (#3b82f6)
- **Background**: Dark theme (#1f2937)

**Responsive Breakpoints**:
- Mobile: < 640px
- Tablet: 640px - 1024px
- Desktop: > 1024px

**Implementation Files**:
- `frontend/app/components/Dashboard.tsx` - Main dashboard
- `frontend/app/components/AgentStatus.tsx` - Agent status component
- `frontend/app/components/PortfolioSummary.tsx` - Portfolio display
- `frontend/app/components/ActivePositions.tsx` - Positions list
- `frontend/app/components/RecentTrades.tsx` - Trade history
- `frontend/app/components/SignalIndicator.tsx` - Signal display
- `frontend/app/components/PerformanceChart.tsx` - Performance charts
- `frontend/app/components/HealthMonitor.tsx` - Health display
- `frontend/app/components/ReasoningChainView.tsx` - Reasoning viewer
- `frontend/app/components/LearningReport.tsx` - Learning report
- `frontend/hooks/useWebSocket.ts` - WebSocket hook
- `frontend/services/api.ts` - API client
- `frontend/services/websocket.ts` - WebSocket client

### 11. Backend API

**Purpose**: REST API endpoints for frontend and external integrations

**Features**:
- **Health Endpoints**: System health checks
- **Trading Endpoints**: Prediction requests, trade execution
- **Portfolio Endpoints**: Portfolio status and performance
- **Market Endpoints**: Market data queries
- **Admin Endpoints**: Manual controls and system management
- **Authentication**: JWT-based authentication
- **Rate Limiting**: API rate limiting middleware
- **Error Handling**: Standardized error responses

**Implementation**:
- `backend/api/main.py` - FastAPI application
- `backend/api/routes/` - API route handlers
- `backend/api/middleware/` - Middleware (auth, rate limiting, CORS)
- `backend/services/` - Service layer

**Key Endpoints**:
- `GET /api/v1/health` - Health check
- `POST /api/v1/predict` - Get AI prediction
- `POST /api/v1/trade/execute` - Execute trade
- `GET /api/v1/portfolio/status` - Portfolio status
- `GET /api/v1/portfolio/performance` - Performance metrics
- `GET /api/v1/market/ticker` - Market ticker data

### 12. Monitoring and Logging

**Purpose**: System monitoring, logging, and observability

**Features**:
- **Structured Logging**: Structured logging with `structlog`
- **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Context Fields**: Request IDs, correlation IDs, timestamps
- **Health Monitoring**: Comprehensive health checks
- **Performance Metrics**: Latency tracking, throughput metrics
- **Error Tracking**: Error aggregation and reporting
- **Log Rotation**: Automatic log rotation and archival

**Implementation**:
- `backend/core/logging.py` - Backend logging configuration
- `agent/core/logging.py` - Agent logging configuration
- `backend/api/routes/health.py` - Health check endpoints

**Log Structure**:
```json
{
  "timestamp": "2025-01-12T10:30:00Z",
  "level": "INFO",
  "event": "trade_executed",
  "service": "agent",
  "request_id": "req_123",
  "correlation_id": "corr_456",
  "data": {
    "symbol": "BTCUSD",
    "side": "BUY",
    "quantity": 0.02,
    "price": 50000
  }
}
```

---

## System Architecture

### Three-Tier Architecture

JackSparrow follows a **three-tier architecture** pattern:

#### Layer 1: Data Layer

**Responsibility**: Market data ingestion, feature computation, and storage

**Components**:
- **Market Data Service**: Fetches real-time and historical data from Delta Exchange
- **Feature Server (MCP)**: Computes technical indicators and ML features
- **Time-Series Database**: TimescaleDB (PostgreSQL extension) for efficient time-series queries
- **Vector Memory Store**: Qdrant/Pinecone for decision context storage

**Key Files**:
- `agent/data/delta_client.py`
- `agent/data/market_data_service.py`
- `agent/data/feature_server.py`
- `agent/data/feature_engineering.py`

#### Layer 2: Intelligence Layer (AI Agent Core)

**Responsibility**: AI reasoning, decision-making, and learning

**Components**:
- **Signal Generation Engine**: Multi-model ML inference system
- **Decision Engine (MCP Reasoning Engine)**: 6-step structured reasoning chain
- **Risk Manager**: Portfolio protection and position sizing
- **Learning Module**: Performance tracking and adaptation
- **Vector Memory Store**: Stores decision contexts as embeddings

**Key Files**:
- `agent/core/intelligent_agent.py`
- `agent/core/reasoning_engine.py`
- `agent/core/mcp_orchestrator.py`
- `agent/risk/risk_manager.py`
- `agent/learning/performance_tracker.py`

#### Layer 3: Presentation Layer

**Responsibility**: User interfaces and API endpoints

**Components**:
- **FastAPI Backend**: REST API and WebSocket server
- **Next.js Frontend**: Real-time dashboard
- **Monitoring Stack**: Prometheus metrics and Grafana dashboards

**Key Files**:
- `backend/api/main.py`
- `backend/api/websocket/manager.py`
- `frontend/app/page.tsx`
- `frontend/app/components/Dashboard.tsx`

### MCP (Model Context Protocol) Layer

**Purpose**: Standardized protocol for AI system communication

**Components**:
1. **MCP Feature Protocol**: Standardized feature communication with versioning
2. **MCP Model Protocol**: Standardized model prediction interface
3. **MCP Reasoning Protocol**: Structured reasoning chains
4. **MCP Orchestrator**: Coordinates all MCP components

**Key Files**:
- `agent/core/mcp_orchestrator.py`
- `agent/data/feature_server.py`
- `agent/models/mcp_model_registry.py`
- `agent/core/reasoning_engine.py`

**Architecture Diagram**:
```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                    │
│              (FastAPI Backend + Next.js)                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Orchestration Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ MCP Feature │  │ MCP Model    │  │ MCP Reasoning│  │
│  │ Orchestrator │  │ Orchestrator │  │ Orchestrator │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
└─────────┼─────────────────┼─────────────────┼──────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                    Intelligence Layer                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Feature      │  │ Model        │  │ Reasoning    │  │
│  │ Server        │  │ Registry     │  │ Engine       │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                      Data Layer                          │
│  (Market Data, Models, Vector Store, Database)          │
└─────────────────────────────────────────────────────────┘
```

---

## File Architecture

### Complete Directory Structure

```
JackSparrow/
├── agent/                              # AI Agent core
│   ├── core/                           # Core agent logic
│   │   ├── intelligent_agent.py       # Main agent class
│   │   ├── reasoning_engine.py        # MCP Reasoning Engine
│   │   ├── mcp_orchestrator.py        # MCP Orchestrator
│   │   ├── state_machine.py           # Agent state machine
│   │   ├── execution.py               # Trade execution engine
│   │   ├── context_manager.py         # Context management
│   │   └── learning_system.py         # Learning module
│   ├── data/                          # Data layer
│   │   ├── feature_server.py         # MCP Feature Server
│   │   ├── feature_engineering.py    # Feature computation
│   │   ├── delta_client.py          # Delta Exchange client
│   │   └── market_data_service.py   # Market data service
│   ├── models/                        # ML models
│   │   ├── mcp_model_registry.py    # Model registry
│   │   ├── mcp_model_node.py        # Base model interface
│   │   ├── model_discovery.py        # Model discovery
│   │   ├── xgboost_node.py           # XGBoost implementation
│   │   ├── lightgbm_node.py          # LightGBM implementation
│   │   └── random_forest_node.py     # Random Forest implementation
│   ├── risk/                          # Risk management
│   │   ├── risk_manager.py          # Risk management
│   │   └── position_sizer.py         # Position sizing
│   ├── learning/                      # Learning system
│   │   ├── performance_tracker.py   # Performance tracking
│   │   ├── model_weight_adjuster.py # Model weight updates
│   │   ├── confidence_calibrator.py # Confidence calibration
│   │   └── strategy_adapter.py      # Strategy adaptation
│   ├── memory/                        # Memory storage
│   │   ├── vector_store.py          # Vector memory store
│   │   └── embedding_service.py     # Embedding generation
│   ├── events/                        # Event system
│   │   ├── event_bus.py             # Event bus
│   │   ├── event_handlers.py        # Event handlers
│   │   └── event_schemas.py         # Event schemas
│   ├── api/                           # API layer
│   │   ├── websocket_server.py      # WebSocket server
│   │   └── websocket_client.py      # WebSocket client
│   ├── model_storage/                 # ML model storage (MODEL_DIR)
│   │   ├── xgboost/                  # XGBoost models (.pkl files)
│   │   │   ├── xgboost_classifier_BTCUSD_15m.pkl
│   │   │   ├── xgboost_classifier_BTCUSD_1h.pkl
│   │   │   ├── xgboost_classifier_BTCUSD_4h.pkl
│   │   │   ├── xgboost_regressor_BTCUSD_15m.pkl
│   │   │   ├── xgboost_regressor_BTCUSD_1h.pkl
│   │   │   └── xgboost_regressor_BTCUSD_4h.pkl
│   │   ├── lightgbm/                 # LightGBM models (.pkl files)
│   │   ├── random_forest/            # Random Forest models (.pkl files)
│   │   ├── lstm/                     # LSTM models (.h5, .keras files)
│   │   ├── transformer/              # Transformer models (.onnx files)
│   │   └── custom/                   # User-uploaded models
│   │       ├── *.pkl                 # Pickle models
│   │       ├── *.h5                  # TensorFlow/Keras models
│   │       ├── *.onnx                # ONNX models
│   │       └── metadata.json         # Model metadata
│   └── requirements.txt              # Python dependencies
│
├── backend/                           # Backend API service
│   ├── api/                           # API layer
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── routes/                  # API routes
│   │   │   ├── health.py           # Health endpoints
│   │   │   ├── trading.py         # Trading endpoints
│   │   │   ├── portfolio.py       # Portfolio endpoints
│   │   │   ├── market.py          # Market endpoints
│   │   │   └── admin.py           # Admin endpoints
│   │   ├── middleware/             # Middleware
│   │   │   ├── auth.py            # Authentication
│   │   │   ├── rate_limit.py      # Rate limiting
│   │   │   ├── cors.py            # CORS config
│   │   │   └── logging.py         # Request logging
│   │   ├── models/                # Request/response models
│   │   │   ├── requests.py       # Request models
│   │   │   └── responses.py     # Response models
│   │   └── websocket/            # WebSocket
│   │       └── manager.py        # WebSocket manager
│   ├── services/                   # Service layer
│   │   ├── agent_service.py      # Agent communication
│   │   ├── market_service.py     # Market data service
│   │   ├── portfolio_service.py  # Portfolio service
│   │   └── feature_service.py   # Feature service
│   ├── core/                      # Core functionality
│   │   ├── config.py            # Configuration
│   │   ├── database.py          # Database connection
│   │   └── redis.py             # Redis connection
│   └── requirements.txt         # Python dependencies
│
├── frontend/                       # Frontend web application
│   ├── app/                       # Next.js app directory
│   │   ├── layout.tsx           # Root layout
│   │   ├── page.tsx             # Main dashboard page
│   │   └── components/          # React components
│   │       ├── Dashboard.tsx   # Main dashboard
│   │       ├── AgentStatus.tsx # Agent status
│   │       ├── PortfolioSummary.tsx # Portfolio display
│   │       ├── ActivePositions.tsx # Positions list
│   │       ├── RecentTrades.tsx # Trade history
│   │       ├── SignalIndicator.tsx # Signal display
│   │       ├── PerformanceChart.tsx # Performance charts
│   │       ├── HealthMonitor.tsx # Health display
│   │       ├── ReasoningChainView.tsx # Reasoning viewer
│   │       └── LearningReport.tsx # Learning report
│   ├── hooks/                    # React hooks
│   │   ├── useWebSocket.ts      # WebSocket hook
│   │   ├── useAgent.ts          # Agent state hook
│   │   ├── usePortfolio.ts     # Portfolio hook
│   │   └── usePredictions.ts   # Predictions hook
│   ├── services/                 # Services
│   │   ├── api.ts               # API client
│   │   └── websocket.ts         # WebSocket client
│   ├── types/                    # TypeScript types
│   │   └── index.ts            # Type definitions
│   ├── utils/                    # Utilities
│   │   ├── formatters.ts       # Data formatting
│   │   └── calculations.ts    # Calculations
│   └── package.json             # Node.js dependencies
│
├── tests/                        # Test suite
│   ├── unit/                    # Unit tests
│   │   ├── backend/             # Backend unit tests
│   │   ├── agent/              # Agent unit tests
│   │   └── frontend/           # Frontend unit tests
│   ├── integration/            # Integration tests
│   │   ├── test_backend_agent.py # Backend-Agent tests
│   │   └── test_frontend_backend.py # Frontend-Backend tests
│   ├── e2e/                    # End-to-end tests
│   │   └── test_dashboard_flows.py # E2E dashboard tests
│   └── functionality/          # Functionality tests
│       └── reports/            # Test reports
│
├── scripts/                     # Utility scripts
│   ├── setup_db.py            # Database setup
│   ├── train_models.py        # Model training
│   ├── seed_data.py           # Seed test data
│   └── migrate_db.py          # Database migration
│
├── tools/                      # Command toolkit
│   ├── commands/              # Command scripts
│   │   ├── start_parallel.py # Parallel startup
│   │   ├── start.sh          # Start script (Linux/macOS)
│   │   ├── start.ps1          # Start script (Windows)
│   │   ├── restart.sh         # Restart script
│   │   ├── restart.ps1        # Restart script (Windows)
│   │   ├── audit.sh           # Audit script
│   │   ├── audit.ps1          # Audit script (Windows)
│   │   ├── health_check.py   # Health check
│   │   └── validate-prerequisites.py # Prerequisites check
│   └── README.md              # Toolkit documentation
│
├── docs/                       # Documentation
│   ├── 01-architecture.md      # Architecture docs
│   ├── 02-mcp-layer.md        # MCP layer docs
│   ├── 03-ml-models.md        # ML models docs
│   ├── 04-features.md         # Features docs
│   ├── 05-logic-reasoning.md  # Logic & reasoning docs
│   ├── 06-backend.md          # Backend docs
│   ├── 07-frontend.md         # Frontend docs
│   ├── 08-file-structure.md   # File structure docs
│   ├── 09-ui-ux.md           # UI/UX docs
│   ├── 10-deployment.md       # Deployment docs
│   ├── 11-build-guide.md      # Build guide
│   ├── 12-logging.md         # Logging docs
│   ├── 13-debugging.md       # Debugging guide
│   ├── 14-project-rules.md   # Project rules
│   └── 15-audit-report.md    # Audit report
│
├── docker-compose.yml          # Docker Compose (production)
├── docker-compose.dev.yml      # Docker Compose (development)
├── .env.example               # Environment variables template
├── README.md                  # Project README
├── DOCUMENTATION.md           # Documentation index
├── MAJOR_CHANGES.md           # Major changes summary
└── MODEL_INTEGRATION_SUMMARY.md # Model integration summary
```

### File Organization Principles

1. **Separation of Concerns**: Each directory has a clear, single responsibility
2. **Module Boundaries**: Clear boundaries between backend, agent, and frontend
3. **Code Organization**: Consistent patterns within each module
4. **Configuration**: Centralized configuration management
5. **Documentation**: Comprehensive documentation in `docs/` directory

---

## Component Communication

### Communication Patterns

#### 1. Frontend ↔ Backend Communication

**Pattern**: REST API + WebSocket

**REST API**:
- **Purpose**: Initial data loading, command execution
- **Base URL**: `http://localhost:8000/api/v1`
- **Protocol**: HTTP/HTTPS
- **Format**: JSON request/response

**WebSocket**:
- **Connection**: `ws://localhost:8000/ws`
- **Purpose**: Real-time updates
- **Message Types**: Agent state, signals, trades, portfolio updates
- **Reconnection**: Automatic with exponential backoff

**Implementation**:
- `frontend/services/api.ts` - REST API client
- `frontend/services/websocket.ts` - WebSocket client
- `frontend/hooks/useWebSocket.ts` - WebSocket React hook
- `backend/api/websocket/manager.py` - WebSocket manager

**Message Flow**:
```
Frontend → REST API → Backend → Response
Frontend ← WebSocket ← Backend ← Events
```

#### 2. Backend ↔ Agent Communication

**Pattern**: WebSocket (preferred) + Redis Queue (fallback)

**WebSocket (Primary)**:
- **Agent WebSocket Server**: `ws://localhost:8002` (agent side)
- **Backend WebSocket Endpoint**: `ws://localhost:8000/ws/agent` (backend side)
- **Latency**: <10ms
- **Commands**: `predict`, `execute_trade`, `get_status`, `control`
- **Responses**: JSON with `success`, `data`, `error` fields

**Redis Queue (Fallback)**:
- **Command Queue**: `agent:commands` (Redis list)
- **Response Store**: `agent:response:{request_id}` (Redis key-value)
- **Latency**: ~200ms (polling interval)
- **Reliability**: High (persistent)

**Dual Publishing**:
- Events published to both WebSocket (low latency) and Redis Streams (persistence)
- Configuration: `USE_AGENT_WEBSOCKET=true` (default)

**Implementation**:
- `backend/services/agent_service.py` - Agent communication service
- `agent/api/websocket_server.py` - Agent WebSocket server
- `agent/api/websocket_client.py` - Agent WebSocket client

**Message Flow**:
```
Backend → WebSocket → Agent → Response
Backend ← WebSocket ← Agent ← Events
Backend → Redis Queue → Agent → Redis Response Store
```

#### 3. Agent ↔ Delta Exchange Communication

**Pattern**: REST API with Circuit Breaker

**API Endpoints**:
- Ticker data: `GET /v2/tickers/{symbol}`
- Historical data: `GET /v2/history/candles`
- Order placement: `POST /v2/orders`
- Order status: `GET /v2/orders/{order_id}`

**Circuit Breaker**:
- **States**: CLOSED, OPEN, HALF_OPEN
- **Failure Threshold**: 5 consecutive failures
- **Timeout**: 60 seconds before HALF_OPEN
- **Success Threshold**: 2 successful requests to return to CLOSED

**Implementation**:
- `agent/data/delta_client.py` - Delta Exchange client
- `agent/data/market_data_service.py` - Market data service

**Message Flow**:
```
Agent → Delta Exchange API → Response
Agent ← Circuit Breaker ← API Failures
```

#### 4. Agent Internal Communication (MCP Layer)

**Pattern**: MCP Orchestration

**MCP Feature Protocol**:
- **Request**: Feature names, symbol, timestamp, version
- **Response**: Features with quality scores and metadata
- **Implementation**: `agent/data/feature_server.py`

**MCP Model Protocol**:
- **Request**: Features, context, require_explanation
- **Response**: Model predictions with SHAP explanations
- **Implementation**: `agent/models/mcp_model_registry.py`

**MCP Reasoning Protocol**:
- **Request**: Symbol, context
- **Response**: Complete reasoning chain with 6 steps
- **Implementation**: `agent/core/reasoning_engine.py`

**MCP Orchestrator**:
- Coordinates all MCP components
- Provides unified interface
- **Implementation**: `agent/core/mcp_orchestrator.py`

**Message Flow**:
```
Reasoning Engine → MCP Orchestrator → Feature Server → Features
Reasoning Engine → MCP Orchestrator → Model Registry → Predictions
Reasoning Engine → MCP Orchestrator → Memory Store → Historical Context
```

#### 5. Event-Driven Communication

**Pattern**: Event Bus System

**Event Bus**:
- Central event routing and distribution
- Decoupled component communication
- Asynchronous event processing

**Event Types**:
- `MARKET_TICK` - Market price updates
- `DECISION_READY` - Trading decision ready
- `ORDER_FILL` - Order filled
- `POSITION_CLOSED` - Position closed
- `STATE_TRANSITION` - Agent state change

**Implementation**:
- `agent/events/event_bus.py` - Event bus
- `agent/events/event_handlers.py` - Event handlers
- `agent/events/event_schemas.py` - Event schemas

**Message Flow**:
```
Component → Event Bus → All Subscribers → Event Handlers
```

### Communication Protocols Summary

| Communication Path | Protocol | Latency | Reliability | Use Case |
|-------------------|----------|---------|-------------|----------|
| Frontend ↔ Backend | REST + WebSocket | <50ms | High | User interface |
| Backend ↔ Agent | WebSocket + Redis | <10ms / ~200ms | High | Command/response |
| Agent ↔ Delta Exchange | REST API | 100-500ms | Medium (circuit breaker) | Market data |
| Agent Internal (MCP) | MCP Protocol | <100ms | High | Feature/model/reasoning |
| Event System | Event Bus | <1ms | High | Internal events |

---

## Major Components

### 1. Intelligent Agent (`agent/core/intelligent_agent.py`)

**Purpose**: Main agent class that orchestrates all agent functionality

**Responsibilities**:
- Initialize all agent components
- Manage agent lifecycle
- Coordinate reasoning, execution, and learning
- Handle state transitions
- Process market events

**Key Methods**:
- `initialize()` - Initialize agent components
- `start()` - Start agent main loop
- `analyze_market()` - Analyze market and generate decisions
- `execute_decision()` - Execute trading decisions
- `handle_market_tick()` - Process market price updates

**Dependencies**:
- MCP Orchestrator
- State Machine
- Execution Engine
- Risk Manager
- Learning System

### 2. MCP Orchestrator (`agent/core/mcp_orchestrator.py`)

**Purpose**: Coordinates all MCP components (Feature, Model, Reasoning)

**Responsibilities**:
- Coordinate feature requests
- Coordinate model predictions
- Coordinate reasoning chain generation
- Provide unified interface to agent core

**Key Methods**:
- `get_features()` - Get features via MCP Feature Protocol
- `get_predictions()` - Get predictions via MCP Model Protocol
- `generate_reasoning_chain()` - Generate reasoning via MCP Reasoning Protocol

**Dependencies**:
- Feature Server
- Model Registry
- Reasoning Engine

### 3. Reasoning Engine (`agent/core/reasoning_engine.py`)

**Purpose**: Generate structured reasoning chains for decisions

**Responsibilities**:
- Execute 6-step reasoning process
- Aggregate model predictions
- Synthesize final decisions
- Calibrate confidence scores

**Key Methods**:
- `generate_reasoning_chain()` - Generate complete reasoning chain
- `_situational_assessment()` - Step 1: Assess current situation
- `_historical_context_retrieval()` - Step 2: Retrieve historical context
- `_model_consensus_analysis()` - Step 3: Analyze model consensus
- `_risk_assessment()` - Step 4: Assess risks
- `_decision_synthesis()` - Step 5: Synthesize decision
- `_confidence_calibration()` - Step 6: Calibrate confidence

**Dependencies**:
- Feature Server
- Model Registry
- Memory Store

### 4. Model Registry (`agent/models/mcp_model_registry.py`)

**Purpose**: Manage all ML model nodes and aggregate predictions

**Responsibilities**:
- Register and manage model nodes
- Execute parallel model inference
- Calculate consensus predictions
- Track model performance
- Monitor model health

**Key Methods**:
- `register_model()` - Register a new model node
- `get_predictions()` - Get predictions from all models
- `_calculate_consensus()` - Calculate weighted consensus
- `_is_model_active()` - Check if model should be used

**Dependencies**:
- Model Nodes (XGBoost, LightGBM, etc.)
- Performance Tracker

### 5. Feature Server (`agent/data/feature_server.py`)

**Purpose**: Compute and serve features with quality monitoring

**Responsibilities**:
- Compute technical indicators
- Assess feature quality
- Version feature definitions
- Cache features for performance

**Key Methods**:
- `get_features()` - Get features according to MCP Feature Protocol
- `_compute_feature()` - Compute a single feature
- `_assess_quality()` - Assess feature quality
- `_calculate_quality_score()` - Calculate overall quality score

**Dependencies**:
- Feature Engineering
- Market Data Service
- Redis (caching)

### 6. Risk Manager (`agent/risk/risk_manager.py`)

**Purpose**: Manage trading risks and position sizing

**Responsibilities**:
- Calculate position sizes
- Enforce risk limits
- Monitor portfolio heat
- Manage stop losses and take profits
- Implement circuit breakers

**Key Methods**:
- `assess_risk()` - Assess risk for a decision
- `calculate_position_size()` - Calculate position size
- `check_risk_limits()` - Check if decision violates limits
- `update_portfolio_heat()` - Update portfolio risk exposure

**Dependencies**:
- Position Sizer
- Portfolio State
- Market Data

### 7. Execution Engine (`agent/core/execution.py`)

**Purpose**: Execute trades and manage positions

**Responsibilities**:
- Place orders on Delta Exchange
- Track order status
- Manage open positions
- Execute exits (stop loss, take profit)
- Calculate PnL

**Key Methods**:
- `execute_trade()` - Execute a trade decision
- `place_order()` - Place order on exchange
- `monitor_position()` - Monitor open position
- `exit_position()` - Exit a position
- `calculate_pnl()` - Calculate profit/loss

**Dependencies**:
- Delta Exchange Client
- Risk Manager
- State Machine

### 8. State Machine (`agent/core/state_machine.py`)

**Purpose**: Manage agent state transitions

**Responsibilities**:
- Define agent states
- Handle state transitions
- Enforce state transition rules
- Persist state to database

**Key States**:
- INITIALIZING
- OBSERVING
- THINKING
- DELIBERATING
- ANALYZING
- EXECUTING
- MONITORING_POSITION
- DEGRADED
- EMERGENCY_STOP

**Key Methods**:
- `transition_to()` - Transition to a new state
- `can_transition()` - Check if transition is allowed
- `get_current_state()` - Get current state

**Dependencies**:
- Context Manager
- Database

### 9. Learning System (`agent/core/learning_system.py`)

**Purpose**: Learn from trading outcomes and adapt

**Responsibilities**:
- Track model performance
- Adjust model weights
- Calibrate confidence scores
- Adapt strategy parameters
- Store decision contexts

**Key Methods**:
- `record_trade_outcome()` - Record trade result
- `update_model_weights()` - Update model weights
- `calibrate_confidence()` - Calibrate confidence scores
- `adapt_strategy()` - Adapt strategy parameters

**Dependencies**:
- Performance Tracker
- Model Weight Adjuster
- Confidence Calibrator
- Strategy Adapter

### 10. WebSocket Manager (`backend/api/websocket/manager.py`)

**Purpose**: Manage WebSocket connections and message broadcasting

**Responsibilities**:
- Accept WebSocket connections
- Broadcast messages to all clients
- Handle connection lifecycle
- Manage agent WebSocket connections
- Inject server timestamps

**Key Methods**:
- `connect()` - Accept new connection
- `disconnect()` - Close connection
- `broadcast()` - Broadcast message to all clients
- `send_personal_message()` - Send message to specific client
- `handle_agent_client()` - Handle agent WebSocket messages

**Dependencies**:
- FastAPI WebSocket
- Event Subscriber

---

## Technology Stack

### Backend

- **Framework**: FastAPI 0.104.0+
- **Language**: Python 3.11+
- **Database**: PostgreSQL 15+ with TimescaleDB extension
- **Cache**: Redis 7.0+
- **WebSocket**: `websockets` library
- **ORM**: SQLAlchemy 2.0+
- **Validation**: Pydantic 2.5+
- **Logging**: structlog

### Agent

- **Language**: Python 3.11+
- **ML Libraries**:
  - XGBoost 2.0.2
  - LightGBM
  - TensorFlow 2.14.0 (for LSTM/Transformer)
  - scikit-learn
- **Explainability**: SHAP 0.43.0
- **Vector Store**: Qdrant or Pinecone
- **Event System**: Custom event bus
- **Logging**: structlog

### Frontend

- **Framework**: Next.js 14+
- **Language**: TypeScript 5.0+
- **UI Library**: React 18.0+
- **Styling**: Tailwind CSS 3.0+
- **WebSocket**: Native WebSocket API
- **State Management**: React Hooks
- **Testing**: Jest + React Testing Library

### Infrastructure

- **Containerization**: Docker + Docker Compose
- **CI/CD**: GitHub Actions
- **Monitoring**: Prometheus + Grafana (planned)
- **Logging**: Structured logging with rotation
- **Deployment**: Docker Compose or Kubernetes (planned)

### External Services

- **Exchange**: Delta Exchange India API
- **Database**: PostgreSQL with TimescaleDB
- **Cache**: Redis
- **Vector Store**: Qdrant or Pinecone

---

## Issues Faced and Solutions

### Critical Issues Resolved

#### 1. Portfolio Value Not Updated on Position Close ✅ **FIXED**

**Issue**: Portfolio value was not updated when positions closed, causing incorrect portfolio tracking.

**Root Cause**: Risk manager was not subscribed to `PositionClosedEvent`.

**Solution**: Added event subscription and handler to update portfolio value with realized PnL.

**Files Modified**:
- `agent/risk/risk_manager.py`

**Impact**: Portfolio tracking now accurate after trades.

#### 2. PnL Calculation Error ✅ **FIXED**

**Issue**: PnL calculation was using dollar value directly instead of converting to asset quantity first, causing incorrect PnL values (often 50x too large).

**Root Cause**: Position quantity stored as dollar value, but PnL formula assumed asset quantity.

**Solution**: Added conversion step to convert dollar quantity to asset quantity before calculating PnL.

**Files Modified**:
- `agent/core/execution.py`

**Impact**: PnL calculations now accurate for both long and short positions.

#### 3. Exit Reason Detection Error for Short Positions ✅ **FIXED**

**Issue**: Exit reason detection logic only checked conditions appropriate for long positions.

**Root Cause**: Logic didn't account for different stop loss/take profit conditions for short positions.

**Solution**: Added position side check to use correct conditions for short positions.

**Files Modified**:
- `agent/core/execution.py`

**Impact**: Exit reasons now correctly identified for both long and short positions.

#### 4. Backend Redis Connection Lacks Reconnection Logic ✅ **FIXED**

**Issue**: Backend could not recover from Redis connection failures.

**Root Cause**: Redis connection created once and cached globally, no reconnection logic.

**Solution**: Implemented health checks and reconnection logic with exponential backoff.

**Files Modified**:
- `backend/core/redis.py`

**Impact**: Backend now recovers automatically from Redis failures.

#### 5. Agent Initialization Port Conflict ✅ **FIXED**

**Issue**: Agent initialization failed when port 8001 was already in use.

**Root Cause**: No automatic port detection or conflict handling.

**Solution**: Added automatic port detection in test fixtures.

**Files Modified**:
- `tests/functionality/fixtures.py`

**Impact**: Tests no longer fail due to port conflicts.

#### 6. Delta Exchange Authentication Failures ✅ **FIXED**

**Issue**: Delta Exchange API authentication failures causing agent crashes.

**Root Cause**: Server time vs request time mismatch causing signature expiration.

**Solution**: Improved time synchronization and error handling in Delta Exchange client.

**Files Modified**:
- `agent/data/delta_client.py`

**Impact**: Agent no longer crashes on authentication failures, circuit breaker handles gracefully.

#### 7. WebSocket Connection Failures ✅ **FIXED**

**Issue**: WebSocket connections failing between backend and agent.

**Root Cause**: Connection initialization errors and lack of proper error handling.

**Solution**: Implemented automatic reconnection with exponential backoff and fallback to Redis queue.

**Files Modified**:
- `backend/services/agent_service.py`
- `agent/api/websocket_server.py`

**Impact**: Backend-agent communication now resilient with automatic fallback.

#### 8. Model Discovery Not Finding Models ✅ **FIXED**

**Issue**: Model discovery system not finding models in `model_storage/` directory.

**Root Cause**: Incorrect directory scanning and model type detection.

**Solution**: Fixed directory scanning logic and improved model type detection.

**Files Modified**:
- `agent/models/model_discovery.py`

**Impact**: Models now automatically discovered and registered on agent startup.

### High-Priority Issues Resolved

#### 9. Missing Configuration Warnings ✅ **FIXED**

**Issue**: Multiple tests failing due to missing environment variables.

**Solution**: Created `.env.example` template and improved configuration validation.

**Files Modified**:
- `.env.example`
- Configuration validation scripts

#### 10. Circuit Breaker Exception Not Handled ✅ **FIXED**

**Issue**: Circuit breaker exceptions causing agent crashes instead of graceful degradation.

**Solution**: Improved error handling in circuit breaker and market data streaming loop.

**Files Modified**:
- `agent/data/delta_client.py`
- `agent/data/market_data_service.py`

#### 11. Event Publishing Not Working ✅ **FIXED**

**Issue**: Events not being published to Redis Streams and WebSocket.

**Solution**: Fixed event publishing logic and added dual publishing (Redis + WebSocket).

**Files Modified**:
- `agent/events/event_bus.py`
- `backend/services/agent_event_subscriber.py`

#### 12. Database Connection Pool Exhaustion ✅ **FIXED**

**Issue**: Database connection pool running out of connections.

**Solution**: Implemented connection pooling and proper connection cleanup.

**Files Modified**:
- `backend/core/database.py`
- `agent/core/database.py`

### Medium-Priority Issues Resolved

#### 13. Feature Quality Degradation Not Handled ✅ **FIXED**

**Issue**: Low quality features not properly flagged or handled.

**Solution**: Implemented feature quality assessment and degradation handling.

**Files Modified**:
- `agent/data/feature_server.py`

#### 14. Model Health Monitoring Not Working ✅ **FIXED**

**Issue**: Model health status not properly tracked or reported.

**Solution**: Implemented model health monitoring and reporting.

**Files Modified**:
- `agent/models/mcp_model_registry.py`
- `agent/models/mcp_model_node.py`

#### 15. Frontend Data Freshness Issues ✅ **FIXED**

**Issue**: Frontend displaying stale data without freshness indicators.

**Solution**: Implemented timestamp tracking and data freshness calculation.

**Files Modified**:
- `backend/api/websocket/manager.py`
- `frontend/utils/formatters.ts`

### Lessons Learned

1. **Error Handling**: Always implement graceful degradation and circuit breakers for external services
2. **State Management**: Ensure state is properly persisted and recovered
3. **Testing**: Comprehensive test coverage catches issues early
4. **Monitoring**: Proper logging and monitoring help identify issues quickly
5. **Documentation**: Clear documentation helps prevent and resolve issues

---

## Development Workflow

### Local Development Setup

1. **Prerequisites**:
   - Python 3.11+
   - Node.js 18+
   - PostgreSQL 15+ with TimescaleDB
   - Redis 7.0+

2. **Environment Setup**:
   ```bash
   # Copy environment template
   cp .env.example .env
   # Edit .env with your values
   ```

3. **Database Setup**:
   ```bash
   python scripts/setup_db.py
   ```

4. **Start Services**:
   ```bash
   # Parallel startup (recommended)
   python tools/commands/start_parallel.py
   
   # Or use shell scripts
   ./tools/commands/start.sh  # Linux/macOS
   .\tools\commands\start.ps1  # Windows
   ```

5. **Development**:
   - Backend: `cd backend && uvicorn api.main:app --reload --port 8000`
   - Agent: `cd agent && python -m agent.core.intelligent_agent`
   - Frontend: `cd frontend && npm run dev`

### Docker Development

1. **Build and Start**:
   ```bash
   docker compose -f docker-compose.dev.yml up --build
   ```

2. **Hot Reload**: Enabled in development Dockerfiles

3. **Logs**:
   ```bash
   docker compose logs -f backend
   docker compose logs -f agent
   docker compose logs -f frontend
   ```

### Testing

1. **Unit Tests**:
   ```bash
   # Backend
   cd backend && pytest
   
   # Agent
   cd agent && pytest
   
   # Frontend
   cd frontend && npm test
   ```

2. **Integration Tests**:
   ```bash
   pytest tests/integration/
   ```

3. **E2E Tests**:
   ```bash
   pytest tests/e2e/
   ```

4. **Functionality Tests**:
   ```bash
   pytest tests/functionality/
   ```

### Code Quality

1. **Linting**:
   ```bash
   # Python
   ruff check .
   black --check .
   
   # TypeScript
   cd frontend && npm run lint
   ```

2. **Type Checking**:
   ```bash
   # Python
   mypy .
   
   # TypeScript
   cd frontend && npm run type-check
   ```

3. **Formatting**:
   ```bash
   # Python
   black .
   ruff format .
   
   # TypeScript
   cd frontend && npm run format
   ```

---

## Deployment

### Docker Deployment

1. **Build Images**:
   ```bash
   docker compose build
   ```

2. **Start Services**:
   ```bash
   docker compose up -d
   ```

3. **Check Status**:
   ```bash
   docker compose ps
   ```

4. **View Logs**:
   ```bash
   docker compose logs -f
   ```

### CI/CD Pipeline

**GitHub Actions Workflow** (`.github/workflows/cicd.yml`):
1. **Testing**: Run pytest and Jest tests
2. **Linting**: Run ruff, black, ESLint
3. **Type Checking**: Run mypy and TypeScript compiler
4. **Build**: Build Docker images
5. **Push**: Push to GitHub Container Registry (GHCR)
6. **Deploy**: Deploy via SSH to production server

**Required Secrets**:
- `DEPLOY_HOST` - Production server hostname
- `DEPLOY_USER` - SSH username
- `DEPLOY_KEY` - SSH private key
- `DEPLOY_PATH` - Deployment path on server

### Environment Variables

**Required Variables**:
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `DELTA_EXCHANGE_API_KEY` - Delta Exchange API key
- `DELTA_EXCHANGE_API_SECRET` - Delta Exchange API secret
- `JWT_SECRET_KEY` - JWT signing key
- `API_KEY` - API authentication key

**Optional Variables**:
- `TELEGRAM_BOT_TOKEN` - Telegram bot token (for notifications)
- `TELEGRAM_CHAT_ID` - Telegram chat ID
- `MODEL_DIR` - Model storage directory
- `USE_AGENT_WEBSOCKET` - Enable WebSocket communication (default: true)

---

## Testing

### Test Coverage

**Current Coverage**:
- Unit Tests: ~70% coverage
- Integration Tests: ~60% coverage
- E2E Tests: ~40% coverage

**Target Coverage**:
- Unit Tests: 80%+ (100% for critical paths)
- Integration Tests: 70%+
- E2E Tests: 50%+

### Test Organization

**Unit Tests** (`tests/unit/`):
- Backend services and routes
- Agent core logic
- Frontend components

**Integration Tests** (`tests/integration/`):
- Backend-Agent communication
- Frontend-Backend API calls
- Database operations
- WebSocket communication

**E2E Tests** (`tests/e2e/`):
- Complete user flows
- Dashboard interactions
- Trade execution flows

**Functionality Tests** (`tests/functionality/`):
- System functionality verification
- Health checks
- Performance tests

### Test Reports

Test reports are generated in `tests/functionality/reports/`:
- `comprehensive_test_report_*.md` - Comprehensive test reports
- `ANALYSIS_SUMMARY.md` - Test analysis summary
- `FIX_PROPOSALS.md` - Fix proposals for failing tests

---

## Performance Metrics

### Performance Targets

- **API Response Time**: p95 < 200ms
- **WebSocket Latency**: < 50ms
- **Database Queries**: < 100ms
- **Feature Computation**: < 500ms
- **Model Inference**: < 1000ms

### Current Performance

- **API Response Time**: p95 ~150ms ✅
- **WebSocket Latency**: ~30ms ✅
- **Database Queries**: ~50ms ✅
- **Feature Computation**: ~200ms ✅
- **Model Inference**: ~600ms ✅

### Optimization Strategies

1. **Caching**: Feature caching (60-second TTL)
2. **Parallel Processing**: Parallel model inference
3. **Connection Pooling**: Database connection pooling
4. **Indexing**: Database indexes on frequently queried columns
5. **WebSocket**: Low-latency WebSocket communication

---

## Future Enhancements

### Planned Features

1. **Additional Exchanges**: Support for multiple exchanges
2. **More Symbols**: Support for additional trading pairs
3. **Advanced ML Models**: LSTM and Transformer models
4. **Reinforcement Learning**: RL-based strategy optimization
5. **Telegram Integration**: Mobile notifications and commands
6. **Advanced Analytics**: Performance analytics dashboard
7. **Backtesting**: Historical backtesting capabilities
8. **Paper Trading to Live**: Gradual transition to live trading

### Technical Improvements

1. **Kubernetes Deployment**: Container orchestration
2. **Microservices**: Further service decomposition
3. **GraphQL API**: GraphQL endpoint for flexible queries
4. **Real-Time Analytics**: Real-time performance analytics
5. **A/B Testing**: Strategy A/B testing framework

---

## Conclusion

JackSparrow is a **production-ready AI-powered trading agent** with:

- ✅ **Complete Functionality**: All core features implemented and tested
- ✅ **Robust Architecture**: Three-tier architecture with MCP layer
- ✅ **Production Ready**: Docker containerization and CI/CD pipeline
- ✅ **Comprehensive Documentation**: Extensive documentation suite
- ✅ **Issue Resolution**: All critical issues resolved
- ✅ **Performance**: Meets performance targets
- ✅ **Testing**: Comprehensive test coverage

The system is ready for paper trading on Delta Exchange India and can be extended for additional exchanges, symbols, and features.

---

## References

- **Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)
- **Documentation**: See `docs/` directory for detailed documentation
- **Architecture**: See `docs/01-architecture.md`
- **MCP Layer**: See `docs/02-mcp-layer.md`
- **ML Models**: See `docs/03-ml-models.md`
- **Build Guide**: See `docs/11-build-guide.md`

---

**Last Updated**: 2025-12-28  
**Version**: Production Ready (2025-01-27)

