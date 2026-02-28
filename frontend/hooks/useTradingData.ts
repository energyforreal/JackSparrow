/**
 * Unified trading data hook - consolidates all trading-related data management.
 *
 * This hook replaces multiple specialized hooks (useAgent, useWebSocket, usePortfolio)
 * with a single, unified interface for all trading data.
 *
 * Simplifications:
 * - Single hook instead of 3+ separate hooks
 * - Unified state management with useReducer
 * - Simplified WebSocket message handling (4 types vs 10+)
 * - Consolidated data fetching and updates
 */

import { useState, useEffect, useReducer, useRef } from 'react'
import { useWebSocket } from './useWebSocket'
import { apiClient, setWebSocketConnection } from '@/services/api'
import type {
  Signal as SharedSignal,
  Portfolio as SharedPortfolio,
  Trade as SharedTrade,
  HealthStatus,
} from '@/types'

// Local types that extend shared domain models where needed
export type Signal = SharedSignal
export type Portfolio = SharedPortfolio
export type Trade = SharedTrade

export interface MarketData {
  symbol: string
  price: number
  volume?: number
  timestamp: string
  change_24h_pct?: number
  high_24h?: number
  low_24h?: number
}

export interface ModelData {
  symbol: string
  consensus_signal?: number
  consensus_confidence?: number
  individual_model_reasoning?: any[]
  model_consensus?: any[]
  model_predictions?: any[]
  timestamp?: string
}

export type HealthData = HealthStatus

export interface TimeData {
  server_time: string
  timestamp_ms: number
}

export interface TradingDataState {
  // Core data
  signal: Signal | null
  portfolio: Portfolio | null
  recentTrades: Trade[]
  marketData: Record<string, MarketData>
  modelData: ModelData | null
  health: HealthData | null

  // Status
  agentState: string
  isConnected: boolean
  lastUpdate: Date | null
  dataSource: 'websocket' | 'api' | 'none'

  // Loading states
  isLoading: boolean
  error: Error | null
}

// Actions for state management
type TradingDataAction =
  | { type: 'WEBSOCKET_MESSAGE'; payload: any }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: Error | null }
  | { type: 'UPDATE_SIGNAL'; payload: Signal }
  | { type: 'UPDATE_PORTFOLIO'; payload: Portfolio }
  | { type: 'ADD_TRADE'; payload: Trade }
  | { type: 'UPDATE_MARKET_DATA'; payload: { symbol: string; data: MarketData } }
  | { type: 'UPDATE_MODEL_DATA'; payload: ModelData }
  | { type: 'UPDATE_HEALTH'; payload: HealthData }
  | { type: 'UPDATE_AGENT_STATE'; payload: string }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LAST_UPDATE'; payload: Date }
  | { type: 'SET_DATA_SOURCE'; payload: 'websocket' | 'api' | 'none' }

// Initial state
const initialState: TradingDataState = {
  signal: null,
  portfolio: null,
  recentTrades: [],
  marketData: {},
  modelData: null,
  health: null,
  agentState: 'UNKNOWN',
  isConnected: false,
  lastUpdate: null,
  dataSource: 'none',
  isLoading: true,
  error: null,
}

// Reducer for state management
function tradingDataReducer(state: TradingDataState, action: TradingDataAction): TradingDataState {
  switch (action.type) {
    case 'WEBSOCKET_MESSAGE': {
      const message = action.payload
      const now = new Date()

      // Handle simplified message format (with backward compatibility for legacy types)
      const messageType = message.type
      const resource = message.resource
      const data = message.data || message.data  // Handle both formats
      
      // Handle new simplified format
      if (messageType === 'data_update') {
        switch (resource) {
          case 'signal':
            // Merge signal data - may include reasoning chain, model data, etc.
            {
              const mergedSignal = {
                ...state.signal,
                ...data
              }

              // If the signal doesn't yet have model consensus data but we've
              // already received it via the model channel, merge it in so the
              // AI Signal card can display per-model decisions consistently.
              if (
                (!mergedSignal.model_consensus || mergedSignal.model_consensus.length === 0) &&
                state.modelData &&
                Array.isArray(state.modelData.model_consensus) &&
                state.modelData.model_consensus.length > 0
              ) {
                mergedSignal.model_consensus = state.modelData.model_consensus
                mergedSignal.individual_model_reasoning = state.modelData.individual_model_reasoning
              }

              return {
                ...state,
                signal: mergedSignal,
                lastUpdate: now,
                dataSource: 'websocket'
              }
            }
          case 'portfolio':
            return {
              ...state,
              portfolio: data,
              lastUpdate: now,
              dataSource: 'websocket'
            }
          case 'trade':
            // Add new trade to list, avoid duplicates, keep only recent 10
            const existingTradeIds = new Set(state.recentTrades.map(t => t.trade_id))
            if (!existingTradeIds.has(data.trade_id)) {
              const normalizedTrade = {
                ...data,
                executed_at: data.executed_at ?? data.timestamp,
                status: data.status ?? 'EXECUTED',
                price: data.price ?? data.fill_price,
              }
              const newTrades = [normalizedTrade, ...state.recentTrades].slice(0, 10)
              return {
                ...state,
                recentTrades: newTrades,
                lastUpdate: now,
                dataSource: 'websocket'
              }
            }
            return state
          case 'market':
            return {
              ...state,
              marketData: {
                ...state.marketData,
                [data.symbol]: data
              },
              lastUpdate: now,
              dataSource: 'websocket'
            }
          case 'model':
            // Merge model data with signal if signal exists
            return {
              ...state,
              modelData: data,
              signal: state.signal ? { ...state.signal, ...data } : null,
              lastUpdate: now,
              dataSource: 'websocket'
            }
          default:
            return state
        }
      }
      
      if (messageType === 'agent_update') {
        return {
          ...state,
          agentState: data?.state || state.agentState,
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'system_update') {
        switch (resource) {
          case 'health':
            return {
              ...state,
              health: data,
              lastUpdate: now,
              dataSource: 'websocket'
            }
          case 'time':
            // Time sync doesn't change data, just update timestamp
            return {
              ...state,
              lastUpdate: now
            }
          default:
            return state
        }
      }
      
      // Backward compatibility: Handle legacy message types
      // These should be rare as backend now uses simplified format
      if (messageType === 'signal_update' || messageType === 'reasoning_chain_update' || messageType === 'model_prediction_update') {
        return {
          ...state,
          signal: { ...state.signal, ...data },
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'portfolio_update') {
        return {
          ...state,
          portfolio: data,
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'trade_executed') {
        const existingTradeIds = new Set(state.recentTrades.map(t => t.trade_id))
        if (!existingTradeIds.has(data.trade_id)) {
          const newTrades = [data, ...state.recentTrades].slice(0, 10)
          return {
            ...state,
            recentTrades: newTrades,
            lastUpdate: now,
            dataSource: 'websocket'
          }
        }
        return state
      }
      
      if (messageType === 'market_tick') {
        return {
          ...state,
          marketData: {
            ...state.marketData,
            [data.symbol]: data
          },
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'agent_state') {
        return {
          ...state,
          agentState: data?.state || state.agentState,
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'health_update') {
        return {
          ...state,
          health: data,
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      // Unknown message type - return state unchanged
      return state
    }

    case 'UPDATE_PORTFOLIO':
      return {
        ...state,
        portfolio: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api'
      }

    case 'ADD_TRADE': {
      const existingTradeIds = new Set(state.recentTrades.map(t => t.trade_id))
      if (existingTradeIds.has(action.payload.trade_id)) return state
      const normalizedTrade = {
        ...action.payload,
        executed_at: action.payload.executed_at ?? action.payload.timestamp,
        status: action.payload.status ?? 'EXECUTED',
        price: action.payload.price ?? action.payload.fill_price,
      }
      const newTrades = [normalizedTrade, ...state.recentTrades].slice(0, 10)
      return {
        ...state,
        recentTrades: newTrades,
        lastUpdate: new Date(),
        dataSource: 'api'
      }
    }

    case 'UPDATE_AGENT_STATE':
      return {
        ...state,
        agentState: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api'
      }

    case 'SET_LOADING':
      return { ...state, isLoading: action.payload }

    case 'SET_ERROR':
      return { ...state, error: action.payload }

    case 'SET_CONNECTED':
      return { ...state, isConnected: action.payload }

    case 'SET_LAST_UPDATE':
      return { ...state, lastUpdate: action.payload }

    case 'SET_DATA_SOURCE':
      return { ...state, dataSource: action.payload }

    default:
      return state
  }
}

// Get WebSocket URL with robust defaults for Docker/remote deployments
const resolveWebSocketUrl = (): string => {
  // 1) Explicit env always wins if set and non-empty
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL
  }

  // 2) In development, fall back to localhost backend
  if (process.env.NODE_ENV === 'development') {
    return 'ws://localhost:8000/ws'
  }

  // 3) In production (Docker, remote clients), derive from API URL or window origin
  try {
    // Prefer API URL if configured so WS follows same host
    if (process.env.NEXT_PUBLIC_API_URL) {
      const api = new URL(process.env.NEXT_PUBLIC_API_URL)
      const wsProtocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${wsProtocol}//${api.host}/ws`
    }

    // Fallback: derive from current browser location
    if (typeof window !== 'undefined') {
      const { protocol, host } = window.location
      const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
      // Assume backend is exposed on same host/port 8000 in Docker compose
      const hostOnly = host.split(':')[0]
      const port = '8000'
      return `${wsProtocol}//${hostOnly}:${port}/ws`
    }
  } catch {
    // Ignore and fall through to empty string
  }

  // 4) Final fallback – empty string will be caught by useWebSocket validation
  return ''
}

const WS_URL = resolveWebSocketUrl()

/**
 * Unified hook for all trading data management.
 *
 * This replaces useAgent, useWebSocket, usePortfolio, and other specialized hooks.
 */
export function useTradingData() {
  const [state, dispatch] = useReducer(tradingDataReducer, initialState)
  const { isConnected, lastMessage, sendMessage, error: wsError } = useWebSocket(WS_URL)
  const lastMessageRef = useRef(lastMessage)

  // Keep lastMessageRef in sync with lastMessage (required for apiClient response polling)
  useEffect(() => {
    lastMessageRef.current = lastMessage
  }, [lastMessage])

  // Provide WebSocket connection to API client so sendCommand works
  useEffect(() => {
    if (sendMessage) {
      setWebSocketConnection(sendMessage, lastMessageRef)
    }
  }, [sendMessage])

  // Update connection status
  useEffect(() => {
    dispatch({ type: 'SET_CONNECTED', payload: isConnected })
  }, [isConnected])

  // Handle WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      // #region agent log
      if (
        process.env.NODE_ENV === 'development' &&
        process.env.NEXT_PUBLIC_DEBUG_AGENT_LOGS === 'true'
      ) {
        try {
          if (
            (lastMessage.type === 'data_update' && (lastMessage as any).resource === 'signal') ||
            lastMessage.type === 'agent_update'
          ) {
            fetch('http://127.0.0.1:7242/ingest/7dea5b1b-57ff-4463-be90-44a6ac830f12', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Debug-Session-Id': 'c0204f',
              },
              body: JSON.stringify({
                sessionId: 'c0204f',
                runId: 'pre-fix',
                hypothesisId: lastMessage.type === 'agent_update' ? 'H4' : 'H2_H5',
                location: 'frontend/hooks/useTradingData.ts:useEffect[lastMessage]',
                message: 'ws_message_dispatch',
                data: {
                  type: lastMessage.type,
                  resource: (lastMessage as any).resource,
                },
                timestamp: Date.now(),
              }),
            }).catch(() => {})
          }
        } catch {
          // Logging must not interfere with state updates
        }
      }
      // #endregion

      dispatch({ type: 'WEBSOCKET_MESSAGE', payload: lastMessage })
    }
  }, [lastMessage])

  // Handle WebSocket errors
  useEffect(() => {
    dispatch({ type: 'SET_ERROR', payload: wsError })
  }, [wsError])

  // Fetch initial data only when WebSocket is connected (sendCommand requires connection)
  useEffect(() => {
    if (!isConnected) return

    const fetchInitialData = async () => {
      dispatch({ type: 'SET_LOADING', payload: true })

      try {
        // Fetch portfolio data
        const portfolioData = await apiClient.getPortfolioSummary()
        dispatch({ type: 'UPDATE_PORTFOLIO', payload: portfolioData as Portfolio })

        // Fetch recent trades
        const trades = await apiClient.getTrades()
        if (Array.isArray(trades)) {
          // Update recent trades (we'll get individual trade updates via WebSocket)
          trades.slice(0, 10).forEach(trade => {
            dispatch({ type: 'ADD_TRADE', payload: trade as Trade })
          })
        }

        // Fetch agent status
        const agentStatus = await apiClient.getAgentStatus()
        if (agentStatus?.state) {
          dispatch({ type: 'UPDATE_AGENT_STATE', payload: agentStatus.state })

          if (
            process.env.NODE_ENV === 'development' &&
            process.env.NEXT_PUBLIC_DEBUG_AGENT_LOGS === 'true'
          ) {
            try {
              fetch('http://127.0.0.1:7242/ingest/7dea5b1b-57ff-4463-be90-44a6ac830f12', {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'X-Debug-Session-Id': 'c0204f',
                },
                body: JSON.stringify({
                  sessionId: 'c0204f',
                  runId: 'pre-fix',
                  hypothesisId: 'H5',
                  location: 'frontend/hooks/useTradingData.ts:fetchInitialData',
                  message: 'agent_status_api_fallback',
                  data: {
                    state: agentStatus.state,
                    available: agentStatus.available,
                  },
                  timestamp: Date.now(),
                }),
              }).catch(() => {})
            } catch {
              // Ignore logging errors entirely
            }
          }
        }

        dispatch({ type: 'SET_LOADING', payload: false })
        dispatch({ type: 'SET_DATA_SOURCE', payload: 'api' })

      } catch (error) {
        console.error('Error fetching initial trading data:', error)
        dispatch({ type: 'SET_ERROR', payload: error instanceof Error ? error : new Error('Unknown error') })
        dispatch({ type: 'SET_LOADING', payload: false })
      }
    }

    fetchInitialData()
  }, [isConnected])

  // Return unified interface
  return {
    // Core data
    signal: state.signal,
    portfolio: state.portfolio,
    recentTrades: state.recentTrades,
    marketData: state.marketData,
    modelData: state.modelData,
    health: state.health,

    // Status
    agentState: state.agentState,
    isConnected: state.isConnected,
    lastUpdate: state.lastUpdate,
    dataSource: state.dataSource,

    // State
    isLoading: state.isLoading,
    error: state.error,
  }
}

// Convenience selectors for specific data types
export function useSignal() {
  const { signal } = useTradingData()
  return signal
}

export function usePortfolio() {
  const { portfolio } = useTradingData()
  return portfolio
}

export function useTrades() {
  const { recentTrades } = useTradingData()
  return recentTrades
}

export function useMarketData(symbol?: string) {
  const { marketData } = useTradingData()
  return symbol ? marketData[symbol] || null : marketData
}

export function useAgentStatus() {
  const { agentState, isConnected } = useTradingData()
  return { agentState, isConnected }
}

export function useSystemHealth() {
  const { health } = useTradingData()
  return health
}