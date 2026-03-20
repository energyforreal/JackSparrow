// WebSocket-based API service
// Commands are sent via WebSocket instead of REST API calls
// This eliminates the need for HTTP requests and provides real-time communication

import { logCommandRequest, logCommandResponse, generateCorrelationId } from '../utils/communicationLogger'

// Type definitions for WebSocket commands
interface WebSocketCommandMessage {
  action: 'command'
  command: string
  request_id: string
  parameters?: Record<string, unknown>
}

interface WebSocketResponseMessage {
  type: 'response'
  request_id: string
  command: string
  success: boolean
  data?: unknown
  error?: string
  timestamp: string
}

interface WebSocketSender {
  (message: WebSocketCommandMessage | Record<string, unknown>): void
}

interface WebSocketLastMessage {
  type?: string
  request_id?: string
  command?: string
  success?: boolean
  data?: unknown
  error?: string
  timestamp?: string
}

// Global WebSocket connection reference
// This will be set by the component using the API service
let websocketSender: WebSocketSender | null = null

interface PendingCommandRequest {
  command: string
  requestId: string
  resolve: (data: unknown) => void
  reject: (error: Error) => void
  timeoutId: ReturnType<typeof setTimeout>
}

const pendingCommandRequests: Map<string, PendingCommandRequest> = new Map()

/**
 * Set the WebSocket sender function and message reference
 * This must be called before using any API methods
 */
export function setWebSocketConnection(
  sender: WebSocketSender,
  _messageRef: { current: WebSocketLastMessage | null }
): void {
  websocketSender = sender
}

/**
 * Resolve/reject any in-flight WebSocket command promise.
 * Called by the WebSocket hook whenever a `type: "response"` message arrives.
 */
export function handleWebSocketResponse(message: any): void {
  if (!message || message.type !== 'response') return

  const requestId: string | undefined = message.request_id || message.correlation_id
  if (!requestId) return

  const pending = pendingCommandRequests.get(requestId)
  if (!pending) return

  // Clear timer + remove from registry first to avoid double resolution.
  clearTimeout(pending.timeoutId)
  pendingCommandRequests.delete(requestId)

  logCommandResponse(
    pending.command,
    message.data,
    requestId,
    undefined,
    message.success ? undefined : message.error
  )

  if (message.success) {
    pending.resolve(message.data)
  } else {
    pending.reject(new Error(message.error || 'Command failed'))
  }
}

/**
 * Send a WebSocket command and wait for response
 */
async function sendCommand(
  command: string,
  parameters: Record<string, unknown> = {},
  timeout: number = 10000
): Promise<unknown> {
  if (!websocketSender) {
    throw new Error('WebSocket connection not initialized. Call setWebSocketConnection() first.')
  }

  const requestId = generateCorrelationId()

  // Log command request
  logCommandRequest(command, parameters, requestId)

  // Send command via WebSocket
  const commandMessage: WebSocketCommandMessage = {
    action: 'command',
    command,
    request_id: requestId,
    parameters
  }

  websocketSender(commandMessage)

  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      pendingCommandRequests.delete(requestId)
      logCommandResponse(command, null, requestId, undefined, `Timeout after ${timeout}ms`)
      reject(new Error(`Command '${command}' timed out after ${timeout}ms`))
    }, timeout)

    pendingCommandRequests.set(requestId, {
      command,
      requestId,
      resolve,
      reject,
      timeoutId,
    })
  })
}

interface ApiError {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
  message?: string
}

class ApiClient {
  async getHealth(): Promise<{
    status: string
    health_score: number
    services: Record<string, {
      status: string
      latency_ms?: number
      error?: string
      details?: Record<string, unknown>
    }>
    degradation_reasons?: string[]
    agent_state?: string
    timestamp?: string
  }> {
    return sendCommand('get_health') as Promise<{
      status: string
      health_score: number
      services: Record<string, {
        status: string
        latency_ms?: number
        error?: string
        details?: Record<string, unknown>
      }>
      degradation_reasons?: string[]
      agent_state?: string
      timestamp?: string
    }>
  }

  async getPrediction(symbol: string = 'BTCUSD'): Promise<{
    signal: string
    confidence: number
    position_size?: number
    reasoning_chain: {
      chain_id: string
      timestamp: string
      steps: Array<{
        step_number: number
        step_name: string
        description: string
        confidence: number
        evidence?: string[]
      }>
      conclusion: string
      final_confidence: number
    }
    model_predictions: Array<{
      model_name: string
      prediction: number
      confidence: number
      reasoning: string
    }>
    model_consensus: Array<{
      model_name: string
      signal: string
      confidence: number
    }>
    individual_model_reasoning: Array<{
      model_name: string
      reasoning: string
      confidence: number
    }>
    market_context?: Record<string, unknown>
    timestamp: string
  }> {
    return sendCommand('predict', { symbol }) as Promise<{
      signal: string
      confidence: number
      position_size?: number
      reasoning_chain: {
        chain_id: string
        timestamp: string
        steps: Array<{
          step_number: number
          step_name: string
          description: string
          confidence: number
          evidence?: string[]
        }>
        conclusion: string
        final_confidence: number
      }
      model_predictions: Array<{
        model_name: string
        prediction: number
        confidence: number
        reasoning: string
      }>
      model_consensus: Array<{
        model_name: string
        signal: string
        confidence: number
      }>
      individual_model_reasoning: Array<{
        model_name: string
        reasoning: string
        confidence: number
      }>
      market_context?: Record<string, unknown>
      timestamp: string
    }>
  }

  async predictWithContext(symbol: string, marketContext: Record<string, unknown>): Promise<{
    success: boolean
    data: {
      decision: 'BUY' | 'SELL' | 'HOLD'
      confidence: number
      reasoning: string
      model_predictions: Array<{
        model_name: string
        prediction: number
        confidence: number
        reasoning: string
      }>
      model_consensus: Array<{
        model_name: string
        signal: string
        confidence: number
      }>
      individual_model_reasoning: Array<{
        model_name: string
        reasoning: string
        confidence: number
      }>
      market_context?: Record<string, unknown>
      timestamp: string
    }
  }> {
    return sendCommand('predict', {
      symbol,
      context: marketContext
    }) as Promise<{
      success: boolean
      data: {
        decision: 'BUY' | 'SELL' | 'HOLD'
        confidence: number
        reasoning: string
        model_predictions: Array<{
          model_name: string
          prediction: number
          confidence: number
          reasoning: string
        }>
        model_consensus: Array<{
          model_name: string
          signal: string
          confidence: number
        }>
        individual_model_reasoning: Array<{
          model_name: string
          reasoning: string
          confidence: number
        }>
        market_context?: Record<string, unknown>
        timestamp: string
      }
    }>
  }

  async getPortfolioSummary(): Promise<{
    total_value: number
    available_balance: number
    open_positions: number
    total_unrealized_pnl: number
    total_realized_pnl: number
    positions: unknown[]
  }> {
    return sendCommand('get_portfolio') as Promise<{
      total_value: number
      available_balance: number
      open_positions: number
      total_unrealized_pnl: number
      total_realized_pnl: number
      positions: unknown[]
    }>
  }

  async getPositions(): Promise<unknown[]> {
    const result = await sendCommand('get_positions')
    return Array.isArray(result) ? result : (result as { positions?: unknown[] })?.positions ?? []
  }

  async getTrades(): Promise<unknown[]> {
    const result = await sendCommand('get_trades')
    return Array.isArray(result) ? result : (result as { trades?: unknown[] })?.trades ?? []
  }

  async getAgentStatus(): Promise<{
    available: boolean
    state: string
    health?: unknown
    latency_ms?: number
  }> {
    return sendCommand('get_agent_status') as Promise<{
      available: boolean
      state: string
      health?: unknown
      latency_ms?: number
    }>
  }

  async getSystemTime(): Promise<{
    server_time: string
    timestamp_ms: number
    timezone: string
  }> {
    // System time is sent via WebSocket broadcasts, not commands
    // Return current time as fallback
    return {
      server_time: new Date().toISOString(),
      timestamp_ms: Date.now(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
    }
  }
}

// WebSocket-based API client
class WebSocketApiClient {
  async getHealth(): Promise<{
    status: string
    health_score: number
    services: Record<string, {
      status: string
      latency_ms?: number
      error?: string
      details?: Record<string, unknown>
    }>
    degradation_reasons?: string[]
    agent_state?: string
    timestamp?: string
  }> {
    if (!websocketSender) {
      throw new Error('WebSocket connection not initialized. Call setWebSocketConnection() first.')
    }

    return sendCommand('get_health') as Promise<{
      status: string
      health_score: number
      services: Record<string, {
        status: string
        latency_ms?: number
        error?: string
        details?: Record<string, unknown>
      }>
      degradation_reasons?: string[]
      agent_state?: string
      timestamp?: string
    }>
  }

  async getPrediction(symbol: string = 'BTCUSD'): Promise<{
    signal: string
    confidence: number
    position_size?: number
    reasoning_chain: {
      chain_id: string
      timestamp: string
      steps: Array<{
        step_number: number
        step_name: string
        description: string
        confidence: number
        evidence?: string[]
      }>
      conclusion: string
      final_confidence: number
    }
    model_predictions: Array<{
      model_name: string
      prediction: number
      confidence: number
      reasoning: string
    }>
    model_consensus: Array<{
      model_name: string
      signal: string
      confidence: number
    }>
    individual_model_reasoning: Array<{
      model_name: string
      reasoning: string
      confidence: number
    }>
    market_context?: Record<string, unknown>
    timestamp: string
  }> {
    return sendCommand('predict', { symbol }) as Promise<{
      signal: string
      confidence: number
      position_size?: number
      reasoning_chain: {
        chain_id: string
        timestamp: string
        steps: Array<{
          step_number: number
          step_name: string
          description: string
          confidence: number
          evidence?: string[]
        }>
        conclusion: string
        final_confidence: number
      }
      model_predictions: Array<{
        model_name: string
        prediction: number
        confidence: number
        reasoning: string
      }>
      model_consensus: Array<{
        model_name: string
        signal: string
        confidence: number
      }>
      individual_model_reasoning: Array<{
        model_name: string
        reasoning: string
        confidence: number
      }>
      market_context?: Record<string, unknown>
      timestamp: string
    }>
  }

  async predictWithContext(symbol: string, marketContext: Record<string, unknown>): Promise<{
    success: boolean
    data: {
      decision: 'BUY' | 'SELL' | 'HOLD'
      confidence: number
      reasoning: string
      model_predictions: Array<{
        model_name: string
        prediction: number
        confidence: number
        reasoning: string
      }>
      model_consensus: Array<{
        model_name: string
        signal: string
        confidence: number
      }>
      individual_model_reasoning: Array<{
        model_name: string
        reasoning: string
        confidence: number
      }>
      market_context?: Record<string, unknown>
      timestamp: string
    }
  }> {
    return sendCommand('predict', {
      symbol,
      context: marketContext
    }) as Promise<{
      success: boolean
      data: {
        decision: 'BUY' | 'SELL' | 'HOLD'
        confidence: number
        reasoning: string
        model_predictions: Array<{
          model_name: string
          prediction: number
          confidence: number
          reasoning: string
        }>
        model_consensus: Array<{
          model_name: string
          signal: string
          confidence: number
        }>
        individual_model_reasoning: Array<{
          model_name: string
          reasoning: string
          confidence: number
        }>
        market_context?: Record<string, unknown>
        timestamp: string
      }
    }>
  }

  async executeTrade(tradeRequest: {
    symbol: string
    side: 'buy' | 'sell'
    quantity: number
    order_type?: 'MARKET' | 'LIMIT'
    price?: number
    stop_loss?: number
    take_profit?: number
  }): Promise<{
    success: boolean
    data?: {
      order_id: string
      status: string
      executed_price?: number
      executed_quantity?: number
      timestamp: string
    }
    error?: string
  }> {
    return sendCommand('execute_trade', tradeRequest) as Promise<{
      success: boolean
      data?: {
        order_id: string
        status: string
        executed_price?: number
        executed_quantity?: number
        timestamp: string
      }
      error?: string
    }>
  }

  async getTicker(symbol: string = 'BTCUSD'): Promise<{
    symbol: string
    price: number
    volume: number
    timestamp: string | Date
    change_24h?: number
    change_24h_pct?: number
    high_24h?: number
    low_24h?: number
  }> {
    return sendCommand('get_ticker', { symbol }) as Promise<{
      symbol: string
      price: number
      volume: number
      timestamp: string | Date
      change_24h?: number
      change_24h_pct?: number
      high_24h?: number
      low_24h?: number
    }>
  }

  async getPerformance(days: number = 30): Promise<{
    total_return?: number
    total_return_pct?: number
    win_rate?: number
    total_trades?: number
    winning_trades?: number
    losing_trades?: number
    average_win?: number
    average_loss?: number
    profit_factor?: number
    sharpe_ratio?: number
    [key: string]: unknown
  }> {
    return sendCommand('get_performance', { days }) as Promise<{
      total_return?: number
      total_return_pct?: number
      win_rate?: number
      total_trades?: number
      winning_trades?: number
      losing_trades?: number
      average_win?: number
      average_loss?: number
      profit_factor?: number
      sharpe_ratio?: number
      [key: string]: unknown
    }>
  }

  async getPortfolioSummary(): Promise<{
    total_value: number
    available_balance: number
    open_positions: number
    total_unrealized_pnl: number
    total_realized_pnl: number
    positions: unknown[]
  }> {
    return sendCommand('get_portfolio') as Promise<{
      total_value: number
      available_balance: number
      open_positions: number
      total_unrealized_pnl: number
      total_realized_pnl: number
      positions: unknown[]
    }>
  }

  async getPositions(): Promise<unknown[]> {
    const result = await sendCommand('get_positions')
    return Array.isArray(result) ? result : (result as { positions?: unknown[] })?.positions ?? []
  }

  async getTrades(): Promise<unknown[]> {
    const result = await sendCommand('get_trades')
    return Array.isArray(result) ? result : (result as { trades?: unknown[] })?.trades ?? []
  }

  async getAgentStatus(): Promise<{
    available: boolean
    state: string
    health?: unknown
    latency_ms?: number
  }> {
    return sendCommand('get_agent_status') as Promise<{
      available: boolean
      state: string
      health?: unknown
      latency_ms?: number
    }>
  }

  async getSystemTime(): Promise<{
    server_time: string
    timestamp_ms: number
    timezone: string
  }> {
    return sendCommand('get_system_time') as Promise<{
      server_time: string
      timestamp_ms: number
      timezone: string
    }>
  }
}

export const apiClient = new WebSocketApiClient()

