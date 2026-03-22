# Logic & Reasoning Documentation

## Overview

This document describes **JackSparrow's** reasoning engine, decision-making process, and learning algorithms. The agent uses a structured 6-step reasoning chain to make decisions, not simple rule-based logic.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Agent Reasoning Engine](#agent-reasoning-engine)
- [Agent State Machine](#agent-state-machine)
- [6-Step Reasoning Chain](#6-step-reasoning-chain)
- [Decision Framework](#decision-framework)
- [Learning Algorithms](#learning-algorithms)
- [Vector Memory System](#vector-memory-system)
- [Model Consensus Mechanism](#model-consensus-mechanism)
- [Model Intelligence and Interaction](#model-intelligence-and-interaction)
- [Related Documentation](#related-documentation)

---

## Agent Reasoning Engine

### Core Principle

The agent **thinks**, not just reacts. It follows a structured reasoning process that:
1. Observes market conditions with context
2. Reasons about observations using structured thinking
3. Decides based on multi-factor analysis
4. Learns from outcomes and adapts behavior
5. Explains decisions in human-understandable terms

### MCP Reasoning Engine

The reasoning engine is implemented as part of the MCP (Model Context Protocol) layer, specifically using the **MCP Reasoning Protocol**. This ensures standardized reasoning chains with full traceability and integration with features and models.

**Implementation**: `agent/core/reasoning_engine.py` implements the MCP Reasoning Engine.

**Integration**: The reasoning engine integrates with:
- **MCP Feature Server** - For feature requests via MCP Feature Protocol
- **MCP Model Registry** - For model predictions via MCP Model Protocol
- **Vector Memory Store** - For historical context retrieval

For detailed MCP Reasoning Protocol documentation, see [MCP Layer Documentation - Reasoning Protocol](02-mcp-layer.md#mcp-reasoning-protocol).

---

## Agent State Machine

### Enhanced State Machine

The agent uses an enhanced state machine that reflects its thinking process:

**State Definitions**:

1. **INITIALIZING**
   - Loading ML models
   - Connecting to services (database, Redis, Delta Exchange)
   - Registering models with MCP Model Registry
   - Initializing vector memory store
   - **Transition to**: OBSERVING when initialization complete

2. **OBSERVING**
   - Passively monitoring market conditions
   - Collecting market data
   - No active analysis
   - **Transition to**: THINKING when significant market change detected

3. **THINKING**
   - Active analysis in progress
   - Generating reasoning chain (6-step process)
   - Processing model predictions
   - **Transition to**: DELIBERATING when reasoning chain complete

4. **DELIBERATING**
   - Weighing decision options
   - Evaluating risks and opportunities
   - Synthesizing final decision
   - **Transition to**: EXECUTING if trade decision made, or ANALYZING if more analysis needed

5. **ANALYZING**
   - Processing signals and evaluating entry conditions
   - Checking risk limits
   - Validating trade conditions
   - **Transition to**: EXECUTING if entry conditions met, or OBSERVING if no trade

6. **EXECUTING**
   - Placing trade orders
   - Managing order execution
   - **Transition to**: MONITORING_POSITION when position opened

7. **MONITORING_POSITION**
   - Active position management
   - Monitoring exit conditions (stop-loss, take-profit) on each market tick
   - Tracking position performance and PnL
   - Automatically triggers exit when stop loss or take profit levels are hit
   - **Transition to**: OBSERVING when position closed

> **Note**: The historical `LEARNING` state is intentionally disabled in this build to avoid heavy post-trade computation. Outcome analysis can be re-enabled in future releases without impacting the current lightweight runtime.

9. **DEGRADED**
   - Partial functionality due to service issues
   - Some models or services unavailable
   - Trading may be limited or paused
   - **Transition to**: OBSERVING when services restored

10. **EMERGENCY_STOP**
    - Critical failure detected
    - All trading halted
    - Requires manual intervention
    - **Transition to**: INITIALIZING after manual reset

### State Transitions

State transitions are deterministic and based on:
- Agent's current context
- Service health status
- Market conditions
- Trade outcomes
- Manual interventions

### AgentContext Structure

The agent maintains comprehensive context about its environment:

```python
class AgentContext(BaseModel):
    """Complete context the agent maintains about its environment."""
    
    # Market Context
    current_price: float
    market_regime: str  # "bull_trending", "bear_trending", "ranging", "high_volatility"
    volatility_percentile: float  # 0-100
    volume_profile: str  # "high", "normal", "low"
    time_of_day: str  # "asian", "european", "us", "overnight"
    
    # Portfolio Context
    cash_available: float
    position_size: float
    unrealized_pnl: float
    position_duration_minutes: Optional[int]
    
    # Recent History
    last_10_trades: List[Dict]
    recent_win_rate: float
    consecutive_losses: int
    
    # Agent State
    current_state: AgentState
    last_state_change: datetime
    confidence_level: float  # 0-1, agent's self-assessed confidence
    
    # Risk Metrics
    portfolio_heat: float  # % of capital at risk
    max_drawdown_current: float
    sharpe_ratio_rolling: float
```

**AgentContext Example Payload**:

```json
{
  "current_price": 51240.5,
  "market_regime": "bull_trending",
  "volatility_percentile": 42.1,
  "volume_profile": "high",
  "time_of_day": "us",
  "cash_available": 94500.0,
  "position_size": 4500.0,
  "unrealized_pnl": 380.25,
  "position_duration_minutes": 120,
  "last_10_trades": [
    {"trade_id": "trade_1042", "pnl": 145.2, "outcome": "win"},
    {"trade_id": "trade_1041", "pnl": -32.8, "outcome": "loss"}
  ],
  "recent_win_rate": 0.68,
  "consecutive_losses": 0,
  "current_state": "THINKING",
  "last_state_change": "2025-01-12T10:28:14Z",
  "confidence_level": 0.74,
  "portfolio_heat": 0.22,
  "max_drawdown_current": 0.045,
  "sharpe_ratio_rolling": 1.82
}
```

Use this structure when building integrations or writing simulations that feed custom contexts into the reasoning engine.

The AgentContext is used throughout the reasoning process to make context-aware decisions.

---

## 6-Step Reasoning Chain

### Step 1: Situational Assessment

**Purpose**: Understand what is happening right now in the market.

**Process**:
1. Fetch current market features
2. Analyze market regime (bull trending, bear trending, ranging, high volatility)
3. Check for anomalies in market data
4. Assess data quality
5. Formulate situational understanding

**Output**:
- Market regime identification
- Volatility assessment
- Volume profile analysis
- Anomaly detection
- Data quality score

**Example Output**:
```
SITUATION ASSESSMENT:
- Market Regime: bull_trending
- Volatility: 45.2th percentile (NORMAL)
- Volume: normal
- Time: us session

Current State:
- Price: $50,000.00
- Trend: Uptrend with momentum
- Momentum: Strong bullish

Anomalies Detected: 0
```

**Confidence**: Based on feature quality score

---

### Step 2: Historical Context Retrieval

**Purpose**: Learn from similar past situations.

**Process**:
1. Create embedding of current situation
2. Search vector memory for similar past situations
3. Analyze outcomes of similar situations
4. Extract insights and patterns
5. Identify novel situations

**Output**:
- Number of similar situations found
- Win rate in similar situations
- Average PnL in similar situations
- Most common decision in similar situations
- Key insights from history

**Example Output**:
```
HISTORICAL ANALYSIS:
Found 5 similar situations:
- Win Rate: 4/5 (80.0%)
- Average PnL: $125.50
- Most common decision: BUY

Key insights from similar situations:
- Strong uptrends in this regime tend to continue
- Entry timing was critical - early entries performed better
```

**Confidence**: Based on similarity score and historical success rate

**Novelty Detection**: If no similar situations found (similarity < 0.7), confidence is reduced

---

### Step 3: Model Consensus Analysis

**Purpose**: Aggregate predictions from multiple ML models using MCP Model Protocol.

**Process**:
1. Request predictions from all active models via MCP Model Registry
2. Models respond using MCP Model Protocol with standardized format
3. Calculate weighted consensus based on model performance
4. Assess model agreement level
5. Identify conflicting signals
6. Generate consensus explanation

**MCP Integration**: This step uses the **MCP Model Protocol** to communicate with models. All model predictions follow the standardized `MCPModelPrediction` format with:
- Normalized predictions (-1.0 to +1.0)
- Confidence scores
- Human-readable reasoning
- Feature importance tracking

**Model Portfolio**:
- XGBoost: Trend identification
- LightGBM: Short-term signals
- LSTM: Sequence patterns
- Transformer: Long-term dependencies
- Random Forest: Baseline
- Custom Models: User-uploaded models discovered automatically

**Model Intelligence**: The agent intelligently understands each model's capabilities and selects appropriate models based on market context. See [ML Models Documentation - Model Intelligence](03-ml-models.md#ai-agent-model-intelligence) for details.

**Consensus Calculation**:
```python
# Weighted voting with performance adjustment
weighted_sum = 0.0
total_weight = 0.0

for model in models:
    perf_weight = model.performance_score  # Based on Sharpe ratio
    confidence_weight = model.prediction.confidence
    
    weight = perf_weight * confidence_weight
    weighted_sum += model.prediction.value * weight
    total_weight += weight

consensus_value = weighted_sum / total_weight
agreement = 1.0 - std_deviation(predictions)
```

**Output**:
- Consensus signal (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL)
- Consensus strength (0.0 to 1.0)
- Agreement level (0.0 to 1.0)
- Individual model predictions
- Model explanations

**Example Output**:
```
MODEL PREDICTIONS:
Consensus Signal: BUY
Consensus Strength: 0.72
Agreement Level: 85.0%

Individual Models:
  - xgboost: BULLISH (strength: 0.80, confidence: 0.85)
    Reasoning: Strong uptrend with volume confirmation
  - lstm: BULLISH (strength: 0.70, confidence: 0.75)
    Reasoning: Sequence pattern indicates continuation
  - transformer: BULLISH (strength: 0.65, confidence: 0.70)
    Reasoning: Attention mechanism shows bullish momentum

Consensus Analysis:
High agreement among models with consistent bullish signals
```

**Confidence**: Based on agreement level and consensus strength

---

### Step 4: Risk Assessment

**Purpose**: Identify and quantify risks before making a decision.

**Risk Factors Evaluated**:

1. **Portfolio Heat**
   - % of capital currently at risk
   - Threshold: >50% triggers warning
   - Impact: Reduces position size

2. **Consecutive Losses**
   - Number of recent consecutive losses
   - Threshold: >=3 triggers caution
   - Impact: Reduces position size or skips trade

3. **High Volatility**
   - Volatility percentile
   - Threshold: >80th percentile
   - Impact: Tighter stop losses

4. **Low Model Agreement**
   - Consensus confidence
   - Threshold: <60%
   - Impact: Reduces confidence and position size

5. **Drawdown Near Limit**
   - Current drawdown percentage
   - Threshold: >8%
   - Impact: Reduces risk exposure

**Risk Score Calculation**:
```python
risk_score = 0.0

if portfolio_heat > 0.5:
    risk_score += 0.3
if consecutive_losses >= 3:
    risk_score += 0.25
if volatility_percentile > 80:
    risk_score += 0.2
if model_confidence < 0.6:
    risk_score += 0.15
if drawdown > 0.08:
    risk_score += 0.1

# Regime-adaptive risk adjustment
regime_risk_multiplier = get_regime_risk_multiplier(market_regime)
risk_score *= regime_risk_multiplier

risk_score = min(1.0, risk_score)
```

**Regime-Adaptive Risk Limits**:
The agent adjusts risk limits based on market regime:
- **Bull Trending**: Standard risk limits, normal position sizing
- **Bear Trending**: Reduced risk limits, tighter stop losses, smaller positions
- **Ranging**: Moderate risk limits, shorter holding periods
- **High Volatility**: Significantly reduced risk limits, very tight stop losses, minimal position sizes

**Regime Risk Multipliers**:
```python
REGIME_RISK_MULTIPLIERS = {
    "bull_trending": 1.0,      # Standard risk
    "bear_trending": 1.3,      # 30% higher risk score
    "ranging": 1.1,            # 10% higher risk score
    "high_volatility": 1.5     # 50% higher risk score
}
```

**Output**:
- Overall risk level (0.0 to 1.0)
- Identified risks list
- Risk mitigation recommendations
- Position size adjustment multiplier
- Stop loss recommendations

**Example Output**:
```
RISK ASSESSMENT:
Overall Risk Level: 0.25 (LOW)

Identified Risks:
  ✓ No significant risks detected

Risk Mitigation:
- Recommended position size multiplier: 1.0x
- Stop loss tighter by: 0%
- Maximum holding period: 120 minutes

Risk/Reward Assessment:
Favorable risk/reward ratio with low risk factors
```

**Confidence**: Inverse of risk score (high risk = low confidence)

---

### Step 5: Decision Synthesis

**Purpose**: Synthesize all information into a final decision.

**Process**:
1. Extract key factors from previous steps
2. Weigh all factors together
3. Consider current portfolio state
4. Generate final recommendation
5. Determine optimal position size

**Decision Factors**:
- Model signal and confidence
- Historical success rate
- Risk level
- Situation clarity
- Portfolio state

**Decision Logic**:

**If already in position**:
- Position is actively monitored via MarketTickEvent
- Risk manager checks stop loss and take profit levels on each price update
- Exit decision is automatically emitted when exit conditions are met
- Execution module closes position and emits PositionClosedEvent
- State machine transitions back to OBSERVING state

**If not in position**:
- Evaluate entry conditions
- Check signal strength threshold (consensus value > 0.3 for BUY, < -0.3 for SELL; see Decision Synthesis thresholds)
- Verify risk limits
- Calculate position size

**Position Sizing**:
```python
# Base position size from signal strength
base_size = signal_strength * max_position_size  # max 10%

# Adjust for risk
risk_adjusted_size = base_size * risk_multiplier

# Adjust for confidence
confidence_adjusted_size = risk_adjusted_size * confidence

# Apply Kelly Criterion
kelly_size = calculate_kelly_criterion(expected_return, win_rate)
final_size = min(confidence_adjusted_size, kelly_size)
```

**Output**:
- Final recommendation (BUY, SELL, HOLD)
- Position size (% of portfolio)
- Rationale explanation
- Decision confidence

**Example Output**:
```
DECISION SYNTHESIS:

Weighing All Factors:
• Model Consensus: BUY (confidence: 0.72)
• Historical Success: 80.0% in similar situations
• Risk Level: 0.25
• Situation Clarity: 0.85

Decision Matrix:
[Matrix showing factor weights]

RECOMMENDATION: BUY
Position Size: 5.0% of portfolio
Rationale: Strong bullish consensus with high historical success rate 
and low risk factors. Market regime supports continuation of uptrend.
```

**Confidence**: Calculated from weighted factors

---

### Step 6: Confidence Calibration

**Purpose**: Produce a final confidence value for the decision.

**Current implementation (learning disabled):** Calibration uses a weighted average of step confidences (steps 3 and 5 weighted higher) and a consistency adjustment (max 10% penalty when step confidences disagree). A model-confidence floor is applied so unanimous HOLD does not show 0%. Historical accuracy is not used when learning is disabled.

**Process** (when learning is enabled in future):
1. Get raw confidence from synthesis step
2. Look up historical accuracy for this confidence level
3. Adjust confidence based on historical performance
4. Account for market regime
5. Generate calibrated confidence

**Calibration Data**:
- Tracks actual success rate for each confidence bucket (0.0-0.1, 0.1-0.2, etc.)
- Separate calibration by market regime
- Rolling window of recent trades (last 100)

**Calibration Formula**:
```python
# Get historical accuracy for this confidence level
historical_accuracy = get_historical_accuracy(
    confidence_bucket=raw_confidence // 0.1,
    market_regime=current_regime
)

# Calibrate confidence
if historical_accuracy:
    calibrated_confidence = (raw_confidence + historical_accuracy) / 2
else:
    # Conservative adjustment if no data
    calibrated_confidence = raw_confidence * 0.8
```

**Output**:
- Raw confidence
- Historical accuracy
- Calibrated confidence
- Adjustment explanation

**Example Output**:
```
CONFIDENCE CALIBRATION:

Raw Confidence: 0.80
Historical Accuracy at this confidence level: 0.65
Calibrated Confidence: 0.725

Adjustment: -0.075
Reason: Agent has historically been overconfident at 80% level, 
succeeding only 65% of the time. Calibration adjusts for this.

Final Assessment:
This decision has a 72.5% probability of success based on:
- Current analysis
- Agent's historical performance at this confidence level
- Market regime (bull_trending)
```

**Final Confidence**: Calibrated confidence value

**End-to-End Example**:

| Step | Highlight                                                                                           |
|------|-----------------------------------------------------------------------------------------------------|
| 1. Situational Assessment | Detected `bull_trending` regime, volatility percentile 38, no anomalies.                       |
| 2. Historical Context     | Retrieved 7 matching scenarios with 71% win rate and median holding period of 95 minutes.      |
| 3. Model Consensus        | XGBoost +0.78, LightGBM +0.62, LSTM +0.55 → consensus +0.69 (agreement 0.82).                  |
| 4. Risk Assessment        | Portfolio heat 0.24 → risk score 0.27 after regime multiplier; no circuit breakers triggered. |
| 5. Decision Synthesis     | Final action `BUY`, base size 6%, Kelly limit 4.8%, final size 4.5% of equity.                |
| 6. Confidence Calibration | Raw confidence 0.78 adjusted to 0.71 using bull-trending historical bucket (0.64 accuracy).   |

This table provides a quick health check when auditing individual decisions—if any column looks inconsistent, debug that stage before moving on.

---

## Decision Framework

### Signal Classification (implementation thresholds)

The reasoning engine maps consensus value (normalized [-1, 1]) to decisions as follows:

- **STRONG_BUY**: consensus > 0.7
- **BUY**: consensus > 0.3
- **HOLD**: -0.3 ≤ consensus ≤ 0.3 (mixed or neutral)
- **SELL**: consensus < -0.3
- **STRONG_SELL**: consensus < -0.7

A separate confidence gate (min_confidence_threshold) is applied by the trading handler before execution.

### Risk-Adjusted Execution

- Position size scales with signal strength
- Maximum position: 10% of portfolio per trade
- Kelly Criterion for optimal sizing
- Volatility-adjusted stop losses
- Risk multiplier applied to position size

---

## Learning Algorithms

> **Status**: The learning pipeline is currently disabled in production builds to keep the agent lightweight. This section remains for future reference when adaptive behavior is re-enabled.

### Model Weight Adjustment

**Purpose**: Dynamically adjust model weights based on performance.

**Process**:
1. Track performance for each model
2. Calculate contribution to successful trades
3. Update weights using exponential moving average
4. Maintain minimum weight to keep models active

**Weight Update Formula**:
```python
def update_model_weights(performance_window=100):
    for model in ensemble:
        # Get recent trades involving this model
        recent_trades = get_trades_involving_model(model, window=performance_window)
        
        # Calculate performance metrics
        accuracy = calculate_accuracy(recent_trades)
        sharpe = calculate_sharpe(recent_trades)
        
        # Combine metrics
        performance_score = accuracy * sharpe
        
        # Exponential moving average
        model.weight = 0.7 * model.weight + 0.3 * performance_score
        
        # Minimum weight to keep model active
        model.weight = max(model.weight, 0.05)
```

**Update Frequency**: After each trade outcome

---

### Confidence Calibration Learning

**Purpose**: Learn agent's actual accuracy at different confidence levels.

**Process**:
1. Record predicted confidence and actual outcome
2. Group by confidence buckets (0.0-0.1, 0.1-0.2, etc.)
3. Calculate actual success rate per bucket
4. Update calibration data
5. Use for future confidence adjustments

**Calibration Data Structure**:
```python
{
    "confidence_bucket": "0.7-0.8",
    "market_regime": "bull_trending",
    "predicted_count": 50,
    "successful_count": 35,
    "success_rate": 0.70,
    "last_updated": "2025-01-12T10:30:00Z"
}
```

---

### Strategy Adaptation

**Purpose**: Adapt trading strategy based on performance.

**Adaptation Triggers**:

1. **Consecutive Losses**
   - After 3 consecutive losses: Reduce position size by 25%
   - After 5 consecutive losses: Increase signal threshold

2. **Low Win Rate**
   - Win rate < 45%: Increase signal threshold
   - Win rate < 40%: Reduce position sizes

3. **High Drawdown**
   - Drawdown > 8%: Reduce risk exposure
   - Drawdown > 10%: Emergency stop

4. **Model Performance**
   - Poor performing models: Reduce weight
   - Excellent performing models: Increase weight

**Adaptation Process**:
```python
def adapt_strategy(performance_metrics):
    if performance_metrics.consecutive_losses >= 3:
        reduce_position_size_multiplier(0.75)
    
    if performance_metrics.win_rate < 0.45:
        increase_signal_threshold(0.05)
    
    if performance_metrics.drawdown > 0.08:
        reduce_max_position_size(0.02)  # Reduce from 10% to 8%
```

---

## Vector Memory System

### Purpose

Store decision contexts as embeddings to enable similarity search and learning from past situations.

### Storage Process

1. **Create Embedding**:
   - Combine market context, features, and decision
   - Generate embedding using sentence transformer
   - Store in vector database

2. **Store Decision**:
   - Decision ID
   - Timestamp
   - Context (market regime, features, portfolio state)
   - Reasoning chain
   - Decision made
   - Outcome (filled after trade completes)

### Retrieval Process

1. **Create Query Embedding**:
   - Embed current situation
   - Use same embedding model

2. **Similarity Search**:
   - Search vector database
   - Cosine similarity threshold: 0.7
   - Return top 5 similar situations

3. **Analyze Outcomes**:
   - Extract outcomes from similar situations
   - Calculate success rate
   - Identify patterns

### Embedding Model

- Uses sentence-transformers
- Model: `all-MiniLM-L6-v2` or similar
- Dimension: 384
- Normalized embeddings for cosine similarity

---

## Model Consensus Mechanism

### Weighted Voting

Each model's prediction is weighted by:
1. **Performance Weight**: Based on Sharpe ratio
2. **Confidence Weight**: Model's own confidence
3. **Final Weight**: `performance_weight * confidence_weight`

### Consensus Calculation

```python
def calculate_consensus(predictions):
    weighted_sum = 0.0
    total_weight = 0.0
    
    for pred in predictions:
        # Get model performance
        perf = get_model_performance(pred.model_name)
        perf_weight = max(0.1, min(2.0, perf.sharpe_ratio))
        
        # Combine with confidence
        weight = perf_weight * pred.confidence
        
        # Add to weighted sum
        weighted_sum += pred.prediction * weight
        total_weight += weight
    
    # Calculate consensus
    consensus_value = weighted_sum / total_weight if total_weight > 0 else 0.0
    
    # Calculate agreement (lower variance = higher agreement)
    predictions_array = [p.prediction for p in predictions]
    agreement = 1.0 - np.std(predictions_array)
    agreement = max(0.0, min(1.0, agreement))
    
    return {
        "value": consensus_value,
        "agreement": agreement,
        "confidence": agreement * abs(consensus_value)
    }
```

### Consensus Thresholds (code reference: reasoning_engine Step 5)

- **BUY**: consensus value > 0.3
- **STRONG_BUY**: consensus value > 0.7
- **HOLD**: -0.3 ≤ consensus ≤ 0.3
- **SELL**: consensus value < -0.3
- **STRONG_SELL**: consensus value < -0.7

Execution also requires confidence ≥ min_confidence_threshold (separate from consensus value).

---

## Model Intelligence and Interaction

### Understanding Model Capabilities

The agent intelligently interacts with ML models to understand their capabilities:

**Model Capability Analysis**:
- Identifies model strengths and limitations
- Understands best use cases for each model type
- Selects appropriate models based on market context
- Adjusts model weights dynamically

**Model Reasoning**:
- Reasons about which models to use for current market conditions
- Calculates contextual weights for model ensemble
- Generates explanations for model selection
- Adapts model usage based on performance

For detailed documentation on model intelligence, see [ML Models Documentation - Model Intelligence](03-ml-models.md#ai-agent-model-intelligence).

### MCP Model Protocol Integration

All model interactions use the **MCP Model Protocol**:

1. **Model Discovery**: Models are automatically discovered from `agent/model_storage/`
2. **Model Registration**: Discovered models are registered with MCP Model Registry
3. **Model Invocation**: Predictions requested via standardized MCP Model Protocol
4. **Model Response**: Models respond with `MCPModelPrediction` format
5. **Consensus Calculation**: Registry calculates weighted consensus from all models

For detailed MCP Model Protocol documentation, see [MCP Layer Documentation - Model Protocol](02-mcp-layer.md#mcp-model-protocol).

---

## Position Monitoring and Exit Logic

### Overview

When the agent enters the `MONITORING_POSITION` state, it monitors open positions for exit conditions. Exits are performed by the **Execution Engine**; there are two paths: a **timer-based** loop and an optional **WebSocket-driven** path when `websocket_sl_tp_enabled` is true.

### Monitoring Process

1. **Position monitor loop** (`IntelligentAgent._position_monitor_loop`): Uses `min_monitor_interval_seconds` (e.g. 2s) when positions are open, and `position_monitor_interval_seconds` (e.g. 15s) when none. Per open position it checks **time-based exit** first (force-close after `max_position_hold_hours`), then fetches current price, updates position, and calls `ExecutionEngine.manage_position(symbol)`.

2. **WebSocket-driven path** (when `websocket_sl_tp_enabled`): MarketDataService WebSocket ticker, after processing the tick, calls `ExecutionEngine.update_position_price_and_check(symbol, price)` with a 200ms per-symbol throttle when a position exists. This allows faster SL/TP reaction on price moves.

3. **Trailing stop**: In `manage_position()`, before SL/TP checks, the stop loss is ratcheted on favorable price moves (longs: stop moves up when price rises; shorts: stop moves down when price falls) using `trailing_stop_percentage`.

4. **Exit condition check** (`ExecutionEngine.manage_position()`): Compares current price to (possibly updated) stop loss and take profit; if breached, calls `close_position()` with `exit_reason` (`stop_loss_hit`, `take_profit_hit`, `time_limit`, `signal_reversal`, or `market_close`).

5. **Signal-reversal exit**: At the start of `TradingHandler.handle_decision_ready_for_trading`, if there is an open position and the new signal contradicts it (e.g. long + SELL/STRONG_SELL), the handler closes the position with `exit_reason='signal_reversal'` and returns without entering a new trade.

6. **State transition**: On `PositionClosedEvent`, state machine transitions to OBSERVING; learning system records outcome and updates model weights when `model_predictions` are present.

### Exit Conditions

**Stop Loss**: Long: price ≤ stop; Short: price ≥ stop. Configurable via `STOP_LOSS_PERCENTAGE` or ATR-based at entry.

**Take Profit**: Long: price ≥ target; Short: price ≤ target. Configurable via `TAKE_PROFIT_PERCENTAGE` or ATR-based at entry.

**Time limit**: Positions held longer than `max_position_hold_hours` are force-closed with `exit_reason='time_limit'`.

**Signal Reversal**: When the new decision signal is opposite to the open position, the position is closed with `exit_reason='signal_reversal'`.

### Position Context Storage

When a position is opened, the following information is stored in context:
- Symbol and side (BUY/SELL)
- Entry price and quantity
- Stop loss price (calculated or ATR-based)
- Take profit price (calculated or ATR-based)
- Entry timestamp
- model_predictions, reasoning_chain_id, predicted_signal (for learning on close)

This information is used throughout the monitoring process to evaluate exit conditions and for the trade-outcome feedback loop.

### Kelly Criterion and Risk

Position sizing is computed in **TradingHandler** using **RiskManager.calculate_position_size()**. The reasoning engine emits the signal; the trading handler maps signal to strength, reads **volatility** from `market_context.features` (required—if missing, the trade is skipped), derives a volatility regime, and calls the risk manager. Resulting size is clamped to `max_position_size`.

### Adaptive Consensus and Confidence

- **Adaptive consensus thresholds** (`_step5_decision_synthesis`): When volatility is present in market context features, strong/mild thresholds vary (e.g. high vol: 0.75/0.40; low vol: 0.60/0.25; else 0.70/0.30). When volatility is missing, fixed 0.70/0.30 are used.
- **Confidence calibration** (`_step6_confidence_calibration`): The model-average floor is applied only when `reasoning_only_confidence > 0.1`, using `max(final_confidence, model_avg * 0.8)`.

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - MCP architecture and protocols
- [ML Models Documentation](03-ml-models.md) - Model management and intelligence
- [Architecture Documentation](01-architecture.md) - System design
- [Features Documentation](04-features.md) - Feature specifications
- [Backend Documentation](06-backend.md) - API implementation
- [Frontend Documentation](07-frontend.md) - UI implementation

