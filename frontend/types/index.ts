export interface AgentState {
  state: string
  lastUpdate: Date
  message?: string
}

export interface Portfolio {
  total_value: number | string
  /** USD account value (wallet balance + unrealized PnL) — matches Delta testnet "Account Value". */
  total_value_usd?: number | string
  /** USD wallet balance without unrealized PnL. */
  wallet_balance_usd?: number | string
  available_balance: number | string
  margin_used?: number | string
  usd_inr_rate?: number | string
  open_positions: number
  total_unrealized_pnl: number | string
  total_unrealized_pnl_usd?: number | string
  total_realized_pnl: number | string
  positions?: Position[]
  data_source?: 'delta_testnet'
  sync_status?: 'live' | 'stale' | 'error'
  exchange_synced_at?: string
  contract_value_btc?: number
  timestamp?: string
}

export interface Position {
  position_id: string
  symbol: string
  side: string
  quantity: number | string
  entry_price: number | string
  entry_price_usd?: number | string
  current_price?: number | string
  current_price_usd?: number | string
  unrealized_pnl?: number | string
  unrealized_pnl_usd?: number | string
  unrealized_pnl_inr?: number | string
  status: string
  opened_at: Date | string
  stop_loss?: number | string
  take_profit?: number | string
  exchange_position_id?: string
  product_id?: number
  lots?: number
  mark_price?: number | string
  liquidation_price?: number | string
  liquidation_price_usd?: number | string
  mark_price_usd?: number | string
  leverage?: number
}

export interface Trade {
  trade_id: string
  position_id?: string
  symbol: string
  side: string
  quantity: number | string
  price: number | string
  entry_price?: number | string
  exit_price?: number | string
  pnl?: number | string
  pnl_usd?: number | string
  entry_time?: Date | string
  exit_time?: Date | string
  duration_seconds?: number
  price_inr?: number | string
  trade_value_inr?: number | string
  status: string
  executed_at: Date | string
  /** Present on some WebSocket / API payloads */
  timestamp?: Date | string
  fill_price?: number | string
  usd_inr_rate?: number | string
  exchange_order_id?: string
  fill_id?: string
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
  /** v43 ensemble: simple forward-return scale (preferred over tanh MCP score) */
  expected_return?: number
  threshold?: number
  regime?: string
  /** v43 MCP legacy normalized score (-1..1); ancillary to expected_return */
  mcp_tanh_prediction?: number
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
  model_consensus?: ModelConsensus[]
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
  /** Reasoning chain id from agent (WebSocket). */
  chain_id?: string
  /** Reasoning engine final confidence, 0-1 (may differ from calibrated UI confidence). */
  final_confidence?: number
  /** v43 JackSparrow: regime label from model context when surfaced on signal. */
  regime?: string
  /** v43: expected return from model context. */
  expected_return?: number
  /** v43: decision threshold. */
  threshold?: number
  /** v43: orchestrator/post-threshold gate reason when HOLD. */
  v43_gate_reject?: string
  /** v43 MCP tanh-normalized prediction (avoid as primary economics signal). */
  mcp_tanh_prediction?: number
  /** v15: model edge p_buy − p_sell (optional); v43 WS may reuse for tanh ancillary */
  edge?: number
  p_buy?: number
  p_sell?: number
  p_hold?: number
  v15_timeframe?: string
  edge_threshold?: number
  v15_filters?: Record<string, unknown>
  policy_verdict?: Record<string, unknown>
  policy_reason_codes?: string[]
  strategy_origin?: boolean
  trade_score?: number
  thesis_signal?: string
  ml_evidence_snapshot?: Record<string, unknown>
  market_context_excerpt?: Record<string, unknown>
  agent_introspection?: AgentIntrospectionSnapshot
  memory_context_id?: string
  decision_event_id?: string
  reflection_snapshot?: ReflectionSnapshot
}

export interface AgentIntrospectionSnapshot {
  version: string
  timestamp: string
  symbol: string
  agent_state: string
  policy_mode: string
  policy_signal: string
  policy_confidence: number
  policy_reason_codes: string[]
  ml_candidate_signal?: string
  thesis_signal?: string
  trade_score?: number
  trade_score_pass?: boolean
  v43_regime?: string
  v43_gate_reject?: string
  portfolio_guard_action?: string
  portfolio_guard_reason_codes?: string[]
  memory_enabled: boolean
  memory_context_count: number
  limits?: Record<string, unknown>
}

export interface ReflectionSnapshot {
  version: string
  timestamp: string
  symbol: string
  position_id: string
  advisory_only: boolean
  predicted_signal: string
  exit_reason: string
  pnl: number
  was_profitable: boolean
  direction_correct?: boolean
  confidence_at_entry?: number
  calibration_bucket: string
  quality_score: number
  diagnostics: string[]
  reason_codes: string[]
}

export interface HealthStatus {
  score?: number
  health_score?: number
  services: Record<string, ServiceStatus>
  degradation_reasons?: string[]
  /** Overall rollup: healthy | degraded | unhealthy (from backend). */
  status?: string
  agent_state?: string
  /** When false, automated trading per health rules may be unavailable. */
  trading_ready?: boolean
  /** Backend trading_mode setting (testnet). */
  trading_mode?: string
  /** Delta cluster label from backend health. */
  delta_environment?: string
  /** Optional model inventory summary from backend health (v15/v43 bundles). */
  ml_models?: Record<string, unknown>
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
