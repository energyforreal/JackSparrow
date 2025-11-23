export interface AgentState {
  state: string
  lastUpdate: Date
  message?: string
}

export interface Portfolio {
  total_value: number | string
  available_balance: number | string
  open_positions: number
  total_unrealized_pnl: number | string
  total_realized_pnl: number | string
  positions?: Position[]
}

export interface Position {
  position_id: string
  symbol: string
  side: string
  quantity: number | string
  entry_price: number | string
  current_price?: number | string
  unrealized_pnl?: number | string
  status: string
  opened_at: Date | string
  stop_loss?: number | string
  take_profit?: number | string
}

export interface Trade {
  trade_id: string
  symbol: string
  side: string
  quantity: number | string
  price: number | string
  status: string
  executed_at: Date | string
}

export interface Prediction {
  signal: string
  confidence: number
  position_size?: number
  reasoning_chain: ReasoningStep[]
  model_predictions: ModelPrediction[]
  timestamp: Date
}

export interface ModelPrediction {
  model_name: string
  prediction: number
  confidence: number
  reasoning?: string
}

export type SignalType = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

export interface ModelConsensus {
  model_name: string
  signal: SignalType
  confidence: number
}

export interface Signal {
  signal: SignalType
  confidence: number
  model_consensus: ModelConsensus[]
  reasoning_chain?: ReasoningStep[]
}

export interface ReasoningStep {
  step_number: number
  title: string
  content: string
  confidence: number
  evidence?: string[]
}

export interface HealthStatus {
  score?: number
  health_score?: number
  services: Record<string, ServiceStatus>
  degradation_reasons?: string[]
  status?: string
  agent_state?: string
  timestamp?: string | Date
}

export interface ServiceStatus {
  status: 'up' | 'degraded' | 'down' | 'unknown'
  latency_ms?: number
  error?: string
  details?: Record<string, unknown>
}

export interface LearningUpdate {
  key_lessons: string[]
  model_weight_changes: ModelWeightChange[]
  strategy_adaptations: string[]
  updated_at: Date
}

export interface ModelWeightChange {
  model_name: string
  change: number
  old_weight: number
  new_weight: number
}

