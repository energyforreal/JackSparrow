# Frontend Documentation

## Overview

The frontend is built using **Next.js 14+** with TypeScript and provides a real-time dashboard for monitoring and interacting with **JackSparrow**. This document covers the frontend architecture, components, and implementation details.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

The recommended way to launch the frontend alongside the backend and agent is via the `start` command documented in the [Build Guide](11-build-guide.md#project-commands). It ensures the Next.js app is started together with all supporting services and routes logs to `logs/start.log`.

---

## Table of Contents

- [Overview](#overview)
- [Next.js Application Structure](#nextjs-application-structure)
- [Core Components](#core-components)
- [WebSocket Integration](#websocket-integration)
- [API Service](#api-service)
- [State Management](#state-management)
- [Styling](#styling)
- [Error Handling](#error-handling)
- [Performance Optimization](#performance-optimization)
- [Accessibility](#accessibility)
- [Related Documentation](#related-documentation)

---

## Next.js Application Structure

### Directory Layout

```
frontend/
├── app/
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Main dashboard page
│   ├── components/
│   │   ├── Dashboard.tsx       # Main dashboard container
│   │   ├── AgentStatus.tsx      # Agent state indicator
│   │   ├── PortfolioSummary.tsx
│   │   ├── ActivePositions.tsx
│   │   ├── RecentTrades.tsx
│   │   ├── SignalIndicator.tsx
│   │   ├── PerformanceChart.tsx
│   │   ├── HealthMonitor.tsx
│   │   ├── ReasoningChainView.tsx
│   │   └── LearningReport.tsx
│   └── api/                    # API routes (if needed)
├── hooks/
│   ├── useWebSocket.ts         # WebSocket connection hook
│   ├── useAgent.ts             # Agent state management
│   ├── usePortfolio.ts         # Portfolio data hook
│   └── usePredictions.ts       # Prediction data hook
├── services/
│   ├── api.ts                  # API client
│   └── websocket.ts            # WebSocket client
├── types/
│   └── index.ts                # TypeScript types
├── utils/
│   ├── formatters.ts           # Data formatting
│   └── calculations.ts         # Client-side calculations
└── styles/
    └── globals.css              # Global styles
```

---

## Core Components

### Dashboard Component

**File**: `app/components/Dashboard.tsx`

**Purpose**: Main container component that orchestrates all dashboard sections.

**Features**:
- Layout management
- State coordination
- WebSocket connection management
- Error boundary handling

**Structure**:
```typescript
export function Dashboard() {
  const { isConnected, lastMessage } = useWebSocket('ws://localhost:8000/ws');
  const [agentState, setAgentState] = useState('MONITORING');
  const [portfolio, setPortfolio] = useState(null);
  const [recentTrades, setRecentTrades] = useState([]);
  
  // Handle WebSocket messages
  useEffect(() => {
    if (!lastMessage) return;
    
    switch (lastMessage.type) {
      case 'agent_state':
        setAgentState(lastMessage.data.state);
        break;
      case 'portfolio_update':
        setPortfolio(lastMessage.data);
        break;
      case 'trade_executed':
        setRecentTrades(prev => [lastMessage.data, ...prev].slice(0, 10));
        break;
    }
  }, [lastMessage]);
  
  return (
    <div className="dashboard">
      <AgentStatus state={agentState} />
      <PortfolioSummary portfolio={portfolio} />
      <RecentTrades trades={recentTrades} />
      {/* ... more components */}
    </div>
  );
}
```

---

### AgentStatus Component

**File**: `app/components/AgentStatus.tsx`

**Purpose**: Display current agent state with visual indicators.

**Props**:
```typescript
interface AgentStatusProps {
  state: 'INITIALIZING' | 'OBSERVING' | 'THINKING' | 'DELIBERATING' | 
         'ANALYZING' | 'EXECUTING' | 'MONITORING_POSITION' |
         'DEGRADED' | 'EMERGENCY_STOP';
  lastUpdate: Date;
  message?: string;
}
```

**Features**:
- Color-coded status indicators
- State-specific icons
- Last update timestamp
- Status messages
- State transition animations

**Visual States**:
- `INITIALIZING`: Gray - ⚙️ Initializing System
- `OBSERVING`: Cyan - 👁️ Observing Markets
- `THINKING`: Purple - 🧠 Thinking (Generating Reasoning)
- `DELIBERATING`: Indigo - 🤔 Deliberating Decision
- `ANALYZING`: Blue - 📊 Analyzing Signals
- `EXECUTING`: Orange - ⚡ Executing Trade
- `MONITORING_POSITION`: Amber - 📈 Monitoring Position
- *(Learning state removed while adaptive features are paused)*
- `DEGRADED`: Yellow - ⚠️ Degraded Performance
- `EMERGENCY_STOP`: Red - 🚨 Emergency Stop

---

### PortfolioSummary Component

**File**: `app/components/PortfolioSummary.tsx`

**Purpose**: Display portfolio overview with key metrics.

**Props**:
```typescript
interface PortfolioSummaryProps {
  portfolio: {
    total_value: number;
    cash: number;
    positions_value: number;
    unrealized_pnl: number;
    realized_pnl: number;
  };
}
```

**Features**:
- Total portfolio value
- Cash vs positions breakdown
- Unrealized PnL (color-coded)
- Realized PnL
- Percentage changes

---

### ActivePositions Component

**File**: `app/components/ActivePositions.tsx`

**Purpose**: Display list of currently open positions.

**Props**:
```typescript
interface ActivePositionsProps {
  positions: Array<{
    symbol: string;
    quantity: number;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
    entry_time: Date;
    duration_minutes: number;
  }>;
}
```

**Features**:
- Position details table
- Real-time PnL updates
- Entry price vs current price
- Position duration
- Color-coded PnL (green/red)

---

### RecentTrades Component

**File**: `app/components/RecentTrades.tsx`

**Purpose**: Display recent trade history.

**Props**:
```typescript
interface RecentTradesProps {
  trades: Array<{
    trade_id: string;
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    entry_price: number;
    exit_price?: number;
    pnl?: number;
    status: 'open' | 'closed';
    timestamp: Date;
  }>;
}
```

**Features**:
- Trade list with details
- PnL display
- Status indicators
- Timestamp formatting
- Link to reasoning chain

---

### SignalIndicator Component

**File**: `app/components/SignalIndicator.tsx`

**Purpose**: Display current AI prediction signal.

**Props**:
```typescript
interface SignalIndicatorProps {
  signal: {
    direction: 'BUY' | 'SELL' | 'HOLD' | 'STRONG_BUY' | 'STRONG_SELL';
    confidence: number;
    models: Array<{
      name: string;
      prediction: string;
      confidence: number;
    }>;
    reasoning: string;
  };
}
```

**Features**:
- Large signal badge (color-coded)
- Confidence bar visualization
- Model consensus breakdown
- Expandable reasoning display
- Confidence percentage

---

### PerformanceChart Component

**File**: `app/components/PerformanceChart.tsx`

**Purpose**: Visualize portfolio performance over time.

**Props**:
```typescript
interface PerformanceChartProps {
  data: Array<{
    timestamp: Date;
    value: number;
    pnl: number;
  }>;
  period: '1d' | '7d' | '30d' | 'all';
}
```

**Features**:
- Line chart of portfolio value
- PnL overlay
- Period selector
- Interactive tooltips
- Responsive design

---

### HealthMonitor Component

**File**: `app/components/HealthMonitor.tsx`

**Purpose**: Display system health status.

**Props**:
```typescript
interface HealthMonitorProps {
  health: {
    status: 'healthy' | 'degraded' | 'unhealthy';
    health_score: number;
    services: {
      [key: string]: {
        status: 'up' | 'down' | 'degraded';
        latency_ms?: number;
      };
    };
    degradation_reasons: string[];
  };
}
```

**Features**:
- Overall health score display
- Service status grid
- Latency indicators
- Degradation reasons
- Color-coded status indicators

---

### RealTimePrice Component

**File**: `app/components/RealTimePrice.tsx`

**Purpose**: Display real-time price data with change indicators and position impact analysis.

**Props**:
```typescript
interface RealTimePriceProps {
  symbol?: string
  className?: string
  positions?: Position[]
  showPositionImpact?: boolean
}
```

**Features**:
- Real-time price display with currency formatting
- Momentary price change indicators with trend icons
- 24-hour statistics (change, volume, high/low)
- WebSocket/WebSocket fallback for data updates
- Connection status indicators
- **Position Impact Preview** (New Feature):
  - Real-time P&L impact calculation for open positions
  - Risk level assessment (low/medium/high/critical)
  - Liquidation risk detection with warnings
  - Portfolio summary with aggregated impact
  - Visual indicators with color-coded risk levels

**Position Impact Risk Levels**:
- **Low**: <2% position impact (gray indicator)
- **Medium**: 2-5% position impact (yellow indicator)
- **High**: 5-10% position impact (orange indicator)
- **Critical**: >10% position impact (red indicator) ⚠️

**Visual Feedback**:
- Green badges for profitable impacts
- Red badges for losses
- Risk level badges with appropriate colors
- AlertTriangle icons for liquidation risk
- Tooltips showing detailed impact breakdown

**Integration**:
- Uses `usePositionImpact` hook for real-time calculations
- Integrates with `useWebSocket` for live price updates
- Displays alongside existing price change indicators
- Responsive design for mobile and desktop

**Example Usage**:
```typescript
// Basic usage
<RealTimePrice symbol="BTCUSD" />

// With position impact analysis
<RealTimePrice
  symbol="BTCUSD"
  positions={portfolio.positions}
  showPositionImpact={true}
/>
```

---

### ReasoningChainView Component

**File**: `app/components/ReasoningChainView.tsx`

**Purpose**: Display agent's reasoning chain for transparency.

**Props**:
```typescript
interface ReasoningChainViewProps {
  reasoningChain: {
    steps: Array<{
      step: number;
      thought: string;
      confidence: number;
      evidence: string[];
    }>;
    conclusion: string;
    final_confidence: number;
  };
}
```

**Features**:
- Expandable step-by-step reasoning
- Confidence indicators per step
- Evidence badges
- Conclusion highlight
- Copy-to-clipboard functionality

**UI Structure**:
- Collapsible steps
- Step numbers with icons
- Confidence bars
- Evidence tags
- Conclusion section

---

### LearningReport Component

**File**: `app/components/LearningReport.tsx`

**Purpose**: Display agent learning updates and adaptations.

**Props**:
```typescript
interface LearningReportProps {
  report: {
    key_lessons: string[];
    model_performance_changes: Array<{
      model_name: string;
      weight_change: number;
      new_weight: number;
    }>;
    strategy_adaptations: string[];
    timestamp: Date;
  };
}
```

**Features**:
- Key lessons list
- Model weight changes
- Strategy adaptations
- Timestamp display
- Visual indicators for changes

---

## WebSocket Integration

### useWebSocket Hook

**File**: `hooks/useWebSocket.ts`

**Purpose**: Custom hook for WebSocket connection management.

**Features**:
- Automatic connection
- Reconnection with exponential backoff
- Message queuing during disconnection
- Subscription management
- Connection status tracking

**Implementation**:
```typescript
export function useWebSocket(url: string) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const ws = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 10;
  const reconnectDelay = useRef(1000);
  const messageQueue = useRef<any[]>([]);
  const subscribedChannels = useRef<string[]>([]);
  
  useEffect(() => {
    connect();
    
    return () => {
      ws.current?.close();
    };
  }, [url]);
  
  const connect = () => {
    ws.current = new WebSocket(url);
    
    ws.current.onopen = () => {
      setIsConnected(true);
      reconnectAttempts.current = 0;
      reconnectDelay.current = 1000;
      
      // Resubscribe to channels
      resubscribe();
      
      // Flush message queue
      flushQueue();
    };
    
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      setLastMessage(message);
    };
    
    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };
    
    ws.current.onclose = () => {
      setIsConnected(false);
      attemptReconnect();
    };
  };
  
  const attemptReconnect = () => {
    if (reconnectAttempts.current < maxReconnectAttempts) {
      reconnectAttempts.current++;
      setTimeout(() => {
        connect();
      }, reconnectDelay.current);
      
      // Exponential backoff
      reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
    }
  };
  
  const resubscribe = () => {
    if (subscribedChannels.current.length > 0) {
      sendMessage({
        action: 'subscribe',
        channels: subscribedChannels.current
      });
    }
  };
  
  const flushQueue = () => {
    while (messageQueue.current.length > 0) {
      const message = messageQueue.current.shift();
      sendMessage(message);
    }
  };
  
  const sendMessage = (message: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message));
    } else {
      messageQueue.current.push(message);
    }
  };
  
  const subscribe = (channels: string[]) => {
    subscribedChannels.current = [...new Set([...subscribedChannels.current, ...channels])];
    sendMessage({ action: 'subscribe', channels });
  };
  
  return { 
    isConnected, 
    lastMessage, 
    sendMessage,
    subscribe
  };
}
```

---

### useAgent Hook

**File**: `hooks/useAgent.ts`

**Purpose**: Manage agent state and operations.

**Features**:
- Agent state tracking
- Prediction requests
- Trade execution
- State change notifications

**Usage Example**:

```typescript
import { useAgent } from '@/hooks/useAgent';

export function QuickSignalCard() {
  const { state, requestPrediction, latestPrediction } = useAgent();

  return (
    <section className="rounded-xl border p-4">
      <header className="flex items-center justify-between">
        <span className="font-semibold text-slate-200">Agent state</span>
        <span className="rounded-full bg-blue-500/20 px-3 py-1 text-sm uppercase">
          {state}
        </span>
      </header>

      <p className="mt-4 text-sm text-slate-400">
        Latest signal: {latestPrediction?.signal ?? '—'} (confidence{' '}
        {(latestPrediction?.confidence ?? 0).toFixed(2)})
      </p>

      <button
        className="mt-4 rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white"
        onClick={() => requestPrediction('BTCUSD')}
      >
        Request new prediction
      </button>
    </section>
  );
}
```

The hook abstracts away WebSocket coordination and REST fallbacks, so components can focus on rendering without duplicating subscription logic.

---

### usePortfolio Hook

**File**: `hooks/usePortfolio.ts`

**Purpose**: Manage portfolio data and updates.

**Features**:
- Portfolio status fetching
- Real-time updates via WebSocket
- Performance metrics calculation
- Trade history management

---

## API Service

### API Client

**File**: `services/api.ts`

**Purpose**: Centralized API client for backend communication.

**Features**:
- Type-safe API calls
- Error handling
- Request/response interceptors
- Retry logic
- Authentication handling

**Implementation**:
```typescript
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private baseURL: string;
  
  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }
  
  async get<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`);
    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }
    return response.json();
  }
  
  async post<T>(endpoint: string, data: any): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }
    return response.json();
  }
  
  // Specific API methods
  async getHealth() {
    return this.get('/api/v1/health');
  }
  
  async getPrediction(symbol: string = 'BTCUSD') {
    return this.post('/api/v1/predict', { symbol });
  }
  
  async executeTrade(trade: TradeRequest) {
    return this.post('/api/v1/trade/execute', trade);
  }
  
  async getPortfolioStatus() {
    return this.get('/api/v1/portfolio/status');
  }
  
  async getPortfolioPerformance(period: string = 'all') {
    return this.get(`/api/v1/portfolio/performance?period=${period}`);
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
```

---

## State Management

### Real-Time Updates

The frontend uses WebSocket for real-time updates with a simplified, unified message format:

### Simplified WebSocket Message Format

The WebSocket communication has been simplified from 10+ message types to 3 core types:

1. **`data_update`**: Unified data updates
   - **Resource: `signal`**: Trading decision updates (replaces `signal_update`, `reasoning_chain_update`)
     - Includes signal, confidence, reasoning chain, model consensus
     - Updates signal indicator and trading decision components
   - **Resource: `portfolio`**: Portfolio state changes (replaces `portfolio_update`)
     - Updates portfolio summary and positions
   - **Resource: `trade`**: Trade execution notifications (replaces `trade_executed`)
     - Updates recent trades list
     - Triggers portfolio refresh
   - **Resource: `market`**: Real-time price updates (replaces `market_tick`)
     - Includes symbol, price, volume, timestamp
     - Updates real-time price display
   - **Resource: `model`**: ML model prediction updates (replaces `model_prediction_update`)
     - Includes model consensus and individual model reasoning
     - Updates model reasoning view component

2. **`agent_update`**: Agent state transitions (replaces `agent_state`)
   - Updates agent status display
   - Includes state, reason, and timestamp

3. **`system_update`**: System updates
   - **Resource: `health`**: System health status (replaces `health_update`)
     - Updates health monitor component
   - **Resource: `time`**: Time synchronization (replaces `time_sync`)
     - Periodic server time sync

### Message Envelope Format

All messages use a unified envelope format:

```typescript
{
  type: "data_update" | "agent_update" | "system_update",
  resource?: "signal" | "portfolio" | "trade" | "market" | "model" | "agent" | "health" | "time",
  data: any,
  timestamp: string,
  source: string,
  sequence?: number
}
```

### Message Handling Flow

1. **Connection**: Establish WebSocket connection on mount
2. **Subscription**: Subscribe to 3 core channels (`data_update`, `agent_update`, `system_update`)
3. **Message Normalization**: Frontend automatically normalizes legacy message types
4. **Message Handling**: Update local state based on message type and resource
5. **Reconnection**: Automatic reconnection with exponential backoff
6. **Queue Management**: Queue messages during disconnection

### State Updates Flow

```
WebSocket Message → Normalize Format → Message Handler → State Update → Component Re-render
```

**Simplified Message Handling**:
- `data_update` with `resource: "signal"`: Update trading signal and decision
- `data_update` with `resource: "portfolio"`: Update portfolio data
- `data_update` with `resource: "trade"`: Add to recent trades
- `data_update` with `resource: "market"`: Update real-time price display
- `data_update` with `resource: "model"`: Update model predictions and consensus
- `agent_update`: Update agent state
- `system_update` with `resource: "health"`: Update health status
- `system_update` with `resource: "time"`: Time synchronization

### Backward Compatibility

The frontend automatically handles legacy message types (`signal_update`, `portfolio_update`, etc.) for backward compatibility during the transition period. Legacy types are normalized to the new format automatically.

---

## Data Freshness Display

The frontend implements visual indicators to show data freshness, helping users understand how current the displayed information is.

### DataFreshnessIndicator Component

**File**: `app/components/DataFreshnessIndicator.tsx`

**Purpose**: Display timestamp with color-coded freshness indicator.

**Props**:
```typescript
interface DataFreshnessIndicatorProps {
  timestamp: Date | string | null | undefined
  label?: string  // Default: "Last update"
  className?: string
}
```

**Features**:
- Color-coded freshness based on age
- Formatted time display (IST timezone)
- Visual dot indicator
- Handles missing timestamps gracefully

**Freshness Color Thresholds**:
- Green (< 1 minute): Data is fresh and current
- Amber (1-5 minutes): Data is somewhat stale but acceptable
- Red (> 5 minutes): Data is very stale and may need refresh

**Usage Example**:
```typescript
<DataFreshnessIndicator 
  timestamp={signal.timestamp} 
  label="Signal time"
/>
```

### Timestamp Normalization

**File**: `utils/formatters.ts`

The frontend normalizes timestamps to handle various formats and ensures consistent UTC → IST conversion:

1. **UTC Assumption**: If timestamp string lacks timezone, assumes UTC by appending 'Z'
2. **ISO 8601 Parsing**: Handles multiple timezone formats:
   - `YYYY-MM-DDTHH:mm:ss.sssZ` (with Z suffix)
   - `YYYY-MM-DDTHH:mm:ss.sss+00:00` (with timezone offset)
   - `YYYY-MM-DDTHH:mm:ss.sss+0000` (without colon)
   - `YYYY-MM-DDTHH:mm:ss.sss` (no timezone - treated as UTC)
3. **IST Display**: All times displayed in IST (Asia/Kolkata) timezone using `toLocaleTimeString`
4. **Format Functions**:
   - `normalizeDate()`: Normalizes timestamps to Date objects with UTC parsing
   - `formatTime()`: Formats time in IST (HH:mm:ss AM/PM)
   - `formatClockTime()`: Formats time matching system clock format (HH:mm:ss am/pm IST)
   - `formatDateTime()`: Formats date and time
   - `getDataFreshnessColor()`: Returns color class based on age with granular thresholds

**Normalization Logic** (Updated):
```typescript
export function normalizeDate(date: Date | string): Date {
  if (typeof date === 'string') {
    // Backend sends timestamps like "2025-12-02T10:11:11.976865" without timezone
    // These should be treated as UTC and displayed in IST on the frontend
    const trimmedDate = date.trim()
    const hasExplicitTimezone =
      trimmedDate.endsWith('Z') || 
      /[+-]\d{2}:\d{2}$/.test(trimmedDate) ||
      /[+-]\d{4}$/.test(trimmedDate) // Handle formats like +0000 (without colon)

    const isoString = hasExplicitTimezone ? trimmedDate : `${trimmedDate}Z`
    return new Date(isoString)
  }
  return date
}
```

**Key Improvements**:
- Trims whitespace from timestamp strings
- Handles multiple timezone formats (+00:00, +0000, Z)
- Appends 'Z' to timestamps without timezone to ensure UTC parsing
- Includes debug logging in development mode for troubleshooting

**Clock Time Formatting**:
```typescript
export function formatClockTime(date: Date | string | null | undefined): string {
  if (!date || !isValidDate(date)) {
    return '--:--:--'
  }
  const d = normalizeDate(date)
  return d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}
```

This ensures all timestamps are:
1. Parsed as UTC (via `normalizeDate`)
2. Converted to IST using `toLocaleTimeString` with `timeZone: 'Asia/Kolkata'`
3. Displayed in consistent format matching system clock (HH:mm:ss am/pm)

### Components Using Freshness Indicators

1. **AgentStatus** (`app/components/AgentStatus.tsx`):
   - Displays `lastUpdate` timestamp
   - Shows when agent state was last updated
   - Updates on `agent_state` WebSocket messages

2. **SignalIndicator** (`app/components/SignalIndicator.tsx`):
   - Displays `signal.timestamp`
   - Shows when trading signal was generated
   - Updates on `signal_update` WebSocket messages

3. **TradingDecision** (`app/components/TradingDecision.tsx`):
   - Displays `signal.timestamp`
   - Shows when trading decision was made
   - Updates on `signal_update` WebSocket messages

### Timestamp Sources

Frontend extracts timestamps from WebSocket messages in priority order:

1. **Primary**: `data.timestamp` - Event-specific timestamp
2. **Fallback**: `server_timestamp_ms` - Server broadcast time (available but not currently used)
3. **Default**: Current time if no timestamp available

**Example from useAgent hook** (Updated):
```typescript
case 'agent_state': {
  const data = lastMessage.data
  if (data?.last_update) {
    try {
      const ts = normalizeDate(data.last_update)
      if (!isNaN(ts.getTime())) {
        setLastUpdate(ts)
      } else {
        setLastUpdate(new Date()) // Fallback to current time
      }
    } catch (error) {
      setLastUpdate(new Date()) // Fallback to current time
    }
  } else if (data?.timestamp) {
    try {
      const ts = normalizeDate(data.timestamp)
      if (!isNaN(ts.getTime())) {
        setLastUpdate(ts)
      } else {
        setLastUpdate(new Date()) // Fallback to current time
      }
    } catch (error) {
      setLastUpdate(new Date()) // Fallback to current time
    }
  } else {
    setLastUpdate(new Date()) // Fallback to current time
  }
  break
}

case 'signal_update': {
  const signalData = lastMessage.data as Signal
  if (signalData?.timestamp) {
    try {
      const ts = normalizeDate(signalData.timestamp)
      if (!isNaN(ts.getTime())) {
        setLastUpdate(ts)
      }
    } catch (error) {
      setLastUpdate(new Date())
    }
  }
  setSignal(signalData)
  break
}
```

**Key Changes**:
- All timestamp parsing uses `normalizeDate()` to ensure UTC parsing
- Error handling for invalid timestamps
- Debug logging in development mode for troubleshooting

### Freshness Calculation

The frontend calculates data age using:

1. **Extract timestamp** from message data
2. **Normalize to Date object** using `normalizeDate()` (handles string/Date, UTC assumption)
3. **Calculate age**: `Date.now() - timestamp.getTime()`
4. **Apply granular thresholds** (Updated):
   - < 30 seconds: Green (very fresh)
   - 30-60 seconds: Light green (fresh)
   - 1-2 minutes: Yellow (recent)
   - 2-5 minutes: Amber (moderate)
   - 5-15 minutes: Orange (stale)
   - >= 15 minutes: Red (very stale)
5. **Display** formatted time with colored indicator and dot

**Color Coding Implementation**:
- Text color: `getDataFreshnessColor(timestamp)` - returns Tailwind color class
- Dot indicator: `getFreshnessDotColor(timestamp)` - matches text color thresholds
- Both use `normalizeDate()` for consistent age calculation

### Server Timestamp Availability

All WebSocket messages include `server_timestamp_ms` at the message root level:

```typescript
{
  type: "signal_update",
  data: { ... },
  server_timestamp_ms: 1706356800123  // Available for freshness calculation
}
```

While the frontend currently uses `data.timestamp` as primary source, `server_timestamp_ms` is available for:
- Fallback when `data.timestamp` is missing
- More precise latency calculation
- Server-side freshness validation

---

## Styling

### Tailwind CSS

The frontend uses Tailwind CSS for styling:

- Utility-first approach
- Responsive design utilities
- Dark mode support
- Custom color palette
- Component-based styling

### Design System

**Colors**:
- Primary: Blue (#3B82F6)
- Success: Green (#10B981)
- Warning: Yellow (#F59E0B)
- Error: Red (#EF4444)
- Neutral: Gray scale

**Typography**:
- Headings: Inter font
- Body: System font stack
- Monospace: For code/data

**Spacing**:
- Consistent spacing scale
- Responsive spacing utilities

---

## Error Handling

### Error Boundaries

React Error Boundaries catch component errors:

```typescript
class ErrorBoundary extends React.Component {
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error
    console.error('Component error:', error, errorInfo);
  }
  
  render() {
    if (this.state.hasError) {
      return <ErrorFallback />;
    }
    return this.props.children;
  }
}
```

### API Error Handling

- Network errors: Show connection error message
- API errors: Display error details from backend
- Timeout errors: Retry with exponential backoff
- Validation errors: Show field-specific errors

---

## Performance Optimization

### Code Splitting

- Route-based code splitting
- Component lazy loading
- Dynamic imports for heavy components

### Caching

- API response caching
- WebSocket message deduplication
- Memoized calculations

### Rendering Optimization

- React.memo for expensive components
- useMemo for calculated values
- useCallback for event handlers
- Virtual scrolling for long lists

---

## Accessibility

### ARIA Labels

- Proper ARIA labels for interactive elements
- Screen reader support
- Keyboard navigation

### Keyboard Navigation

- Tab order management
- Keyboard shortcuts
- Focus management

### Visual Accessibility

- High contrast mode support
- Color-blind friendly palette
- Text size scaling

---

## Environment Configuration

### Environment Variables

The frontend reads environment variables from the **root `.env` file** in the project root directory. The `frontend/next.config.js` file includes a `loadRootEnv()` function that automatically reads from `../.env` (project root).

**Required Frontend Variables:**

```bash
# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# WebSocket URL
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws

# Backend API key (inherited from API_KEY)
NEXT_PUBLIC_BACKEND_API_KEY=your_api_key
```

**How It Works:**

- **Local Development**: The `loadRootEnv()` function in `next.config.js` reads variables from the root `.env` file at build time and runtime
- **Docker Deployment**: Variables are passed through the `environment:` section in `docker-compose.yml`, which reads from root `.env`
- **No `frontend/.env.local` needed**: All frontend environment variables are configured in the root `.env` file

**Note**: See `.env.example` in the project root for the complete list of all available environment variables. All services (backend, agent, frontend) share the same root `.env` file.

---

## Testing

### Frontend Functionality Tests

The frontend includes comprehensive functionality tests that validate:
- Frontend accessibility and HTTP responses
- API integration with backend
- WebSocket connectivity and real-time data flow
- Health endpoint availability
- CORS headers configuration

**Running Frontend Tests**:

```bash
# Run all functionality tests (includes frontend)
python tools/commands/start_and_test.py

# Run only integration tests (includes frontend functionality)
python tools/commands/start_and_test.py --groups integration

# Run tests without starting services (assume services already running)
python tools/commands/start_and_test.py --no-startup
```

**Test Suite Location**: `tests/functionality/test_frontend_functionality.py`

**Test Coverage**:
- ✅ Frontend HTTP accessibility
- ✅ Backend API integration
- ✅ WebSocket connection and subscriptions
- ✅ Health endpoint checks
- ✅ CORS headers validation

**Test Configuration**:

Frontend tests use the `FRONTEND_URL` environment variable (defaults to `http://localhost:3000`). If the frontend starts on a different port, the test runner automatically configures the correct URL.

**CI/CD Integration**:

Frontend functionality tests are automatically run in the CI/CD pipeline as part of the functionality test suite. See `.github/workflows/cicd.yml` for details.

### Frontend Unit Tests

The frontend also includes React component unit tests using Jest and React Testing Library:

```bash
# Run frontend unit tests
cd frontend
npm test

# Run with coverage
npm test -- --coverage
```

**Test Location**: `frontend/__tests__/` and `frontend/**/*.test.tsx`

---

## Related Documentation

- [Backend Documentation](06-backend.md) - API specifications
- [UI/UX Documentation](09-ui-ux.md) - Design guidelines
- [Architecture Documentation](01-architecture.md) - System design
- [Deployment Documentation](10-deployment.md) - Setup instructions
- [Testing Guide](testing-guide.md) - Comprehensive testing documentation

