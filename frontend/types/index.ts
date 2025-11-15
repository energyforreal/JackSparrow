export interface AgentState {
  state: string
  lastUpdate: Date
  message?: string
}

export interface Portfolio {
  total_value: number
  available_balance: number
  open_positions: number
  total_unrealized_pnl: number
  total_realized_pnl: number
}

export interface Position {
  position_id: string
  symbol: string
  side: string
  quantity: number
  entry_price: number
  current_price?: number
  unrealized_pnl?: number
  status: string
  opened_at: Date
}

export interface Trade {
  trade_id: string
  symbol: string
  side: string
  quantity: number
  price: number
  status: string
  executed_at: Date
}

export interface Prediction {
  signal: string
  confidence: number
  position_size?: number
  reasoning_chain: any
  model_predictions: any[]
  timestamp: Date
}

