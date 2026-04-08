export interface AgentState {
  state: string
  lastUpdate: Date
  message?: string
}

export interface Portfolio {
  total_value: number | string
  available_balance: number | string
  margin_used?: number | string
  usd_inr_rate?: number | string
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
  /** Present on some WebSocket / API payloads */
  timestamp?: Date | string
  fill_price?: number | string
}

export interface ModelPrediction {
  model_name: string
  prediction: number
  confidence: number
  reasoning?: string
}

export interface ReasoningStep {
  step_number: number
  step_name: string
  description: string
  confidence: number
  evidence?: string[]
  // Optional metadata fields
  data_freshness_seconds?: number
  similarity_score?: number
  feature_quality_score?: number
}

export interface ReasoningChain {
  chain_id: string
  timestamp: string | Date
  steps: ReasoningStep[]
  conclusion: string
  final_confidence: number
}

export interface Prediction {
  signal: string
  confidence: number
  position_size?: number
  reasoning_chain: ReasoningChain
  model_predictions: ModelPrediction[]
  timestamp: Date
}

export type SignalType = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

export interface ModelConsensus {
  model_name: string
  signal: SignalType
  confidence: number
  prediction?: number
  /** v15 pipeline (optional) */
  p_buy?: number
  p_sell?: number
  p_hold?: number
  edge?: number
  timeframe?: string
}

export interface ModelReasoning {
  model_name: string
  reasoning: string
  confidence: number
}

/** Inference path: model_service (primary) or agent (fallback); degraded when model service unreachable but agent used. */
export type InferenceSource = 'model_service' | 'agent'
export type InferenceMode = 'primary' | 'fallback' | 'degraded'

export interface Signal {
  signal: SignalType
  // Confidence is stored as percentage (0-100) for display,
  // but normalization helpers accept both 0-1 and 0-100.
  confidence: number
  model_consensus: ModelConsensus[]
  // WebSocket currently sends an array of reasoning steps only,
  // while HTTP predictions can provide full ReasoningChain metadata.
  reasoning_chain?: ReasoningStep[]
  reasoning_chain_full?: ReasoningChain
  individual_model_reasoning?: ModelReasoning[]
  model_predictions?: ModelPrediction[]
  agent_decision_reasoning?: string
  symbol?: string
  timestamp?: string | Date
  // Model-serving metadata (when available from API/WS)
  inference_latency_ms?: number
  inference_source?: InferenceSource
  inference_mode?: InferenceMode
  model_version?: string
  /** v15: model edge p_buy − p_sell (optional) */
  edge?: number
  p_buy?: number
  p_sell?: number
  p_hold?: number
  v15_timeframe?: string
  edge_threshold?: number
  v15_filters?: Record<string, unknown>
}

export interface HealthStatus {
  score?: number
  health_score?: number
  services: Record<string, ServiceStatus>
  degradation_reasons?: string[]
  status?: string
  agent_state?: string
  /** When false, paper trading is disabled (e.g. models unhealthy). */
  trading_ready?: boolean
  timestamp?: string | Date
}

export interface ServiceDetails {
  note?: string
  healthy_models?: number
  total_models?: number
  [key: string]: unknown
}

export interface ServiceStatus {
  status: 'up' | 'degraded' | 'down' | 'unknown'
  latency_ms?: number
  error?: string
  details?: ServiceDetails
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

// Position Impact Analysis
export interface PositionImpact {
  positionId: string
  symbol: string
  pnlChange: number
  pnlPercent: number
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  liquidationRisk: boolean
  currentValue: number
  entryValue: number
}

// Enhanced Ticker Data with Position Impact
export interface EnhancedTickerData {
  symbol: string
  price: number
  volume: number
  timestamp: string | Date
  change_24h?: number
  change_24h_pct?: number
  high_24h?: number
  low_24h?: number
  open_24h?: number
  close_24h?: number
  turnover_usd?: number
  oi?: number
  spot_price?: number
  mark_price?: number
  bid_price?: number
  ask_price?: number
  bid_size?: number
  ask_size?: number
  // Enhanced fields for position impact
  positionImpacts?: PositionImpact[]
}
