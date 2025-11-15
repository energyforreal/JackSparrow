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
         'ANALYZING' | 'EXECUTING' | 'MONITORING_POSITION' | 'LEARNING' | 
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
- `LEARNING`: Teal - 📚 Learning from Outcome
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

The frontend uses WebSocket for real-time updates:

1. **Connection**: Establish WebSocket connection on mount
2. **Subscription**: Subscribe to relevant channels
3. **Message Handling**: Update local state based on message types
4. **Reconnection**: Automatic reconnection with exponential backoff
5. **Queue Management**: Queue messages during disconnection

### State Updates Flow

```
WebSocket Message → Message Handler → State Update → Component Re-render
```

**Message Types Handled**:
- `agent_state`: Update agent state
- `trade_executed`: Add to recent trades
- `portfolio_update`: Update portfolio data
- `health_status`: Update health status
- `prediction_generated`: Update signal indicator

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

## Related Documentation

- [Backend Documentation](06-backend.md) - API specifications
- [UI/UX Documentation](09-ui-ux.md) - Design guidelines
- [Architecture Documentation](01-architecture.md) - System design
- [Deployment Documentation](10-deployment.md) - Setup instructions

