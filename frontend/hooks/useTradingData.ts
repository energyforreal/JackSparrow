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

import { useCallback, useEffect, useReducer, useRef } from 'react'
import toast from 'react-hot-toast'
import { useWebSocket } from './useWebSocket'
import { apiClient, setWebSocketConnection } from '@/services/api'
import { getBackendProxyBase } from '@/lib/backendProxy'
import { formatCurrency, formatUsdCurrency, parseUtcTimestamp } from '@/utils/formatters'
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

/** Max trades kept in UI state (matches REST bootstrap limit). */
export const RECENT_TRADES_MAX = 50

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
  /** Model version or ensemble descriptor */
  model_version?: string
  /** Inference latency in ms */
  inference_latency_ms?: number
  /** Names of models in ensemble */
  ensemble_composition?: string[]
  /** When consensus was produced (ISO string) */
  consensus_source_timestamp?: string
  /** primary (model_service) | fallback (agent) | degraded */
  inference_mode?: 'primary' | 'fallback' | 'degraded'
  inference_source?: 'model_service' | 'agent'
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
  performanceData: Array<{ date: string; value: number }>

  // Status
  agentState: string
  isConnected: boolean
  lastUpdate: Date | null
  dataSource: 'websocket' | 'api' | 'none'

  // Loading states
  isLoading: boolean
  /** True until the portfolio REST request settles (success or failure). */
  isPortfolioLoading: boolean
  error: Error | null
}

// Actions for state management
type TradingDataAction =
  | { type: 'WEBSOCKET_MESSAGE'; payload: any }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_PORTFOLIO_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: Error | null }
  | { type: 'UPDATE_SIGNAL'; payload: Signal }
  | { type: 'UPDATE_PORTFOLIO'; payload: Portfolio }
  | { type: 'ADD_TRADE'; payload: Trade }
  | { type: 'UPDATE_MARKET_DATA'; payload: { symbol: string; data: MarketData } }
  | { type: 'UPDATE_MODEL_DATA'; payload: ModelData }
  | { type: 'UPDATE_HEALTH'; payload: HealthData }
  | { type: 'UPDATE_AGENT_STATE'; payload: string }
  | { type: 'SET_PERFORMANCE_DATA'; payload: Array<{ date: string; value: number }> }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LAST_UPDATE'; payload: Date }
  | { type: 'SET_DATA_SOURCE'; payload: 'websocket' | 'api' | 'none' }
  | { type: 'HYDRATE_TRADES'; payload: { trades: Trade[]; merge?: boolean } }
  | { type: 'RESET_LOCAL_TRADING_STATE' }

// Initial state
const initialState: TradingDataState = {
  signal: null,
  portfolio: null,
  recentTrades: [],
  marketData: {},
  modelData: null,
  health: null,
  performanceData: [],
  agentState: 'UNKNOWN',
  isConnected: false,
  lastUpdate: null,
  dataSource: 'none',
  isLoading: true,
  isPortfolioLoading: true,
  error: null,
}

function normalizeTradeRecord(raw: unknown): Trade | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const id = r.trade_id
  if (id == null || id === '') return null
  return {
    ...(raw as Trade),
    trade_id: String(id),
    executed_at: (r.executed_at ?? r.timestamp) as Trade['executed_at'],
    status: (r.status as string) ?? 'EXECUTED',
    price: (r.price ?? r.fill_price) as Trade['price'],
  }
}

function normalizeHealthFromRest(raw: unknown): HealthData | null {
  if (!raw || typeof raw !== 'object') return null
  const h = raw as HealthData & { overall_status?: string }
  const next: HealthData = { ...h }
  if (next.status === undefined && h.overall_status !== undefined) {
    next.status = String(h.overall_status)
  }
  return next
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
      const data = message.data ?? message.payload ?? {}
      
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

              // Prefer model consensus when decision confidence is 0 so main card shows
              // real-time values, but only when the model data is recent. This prevents
              // old consensus data from resurrecting as a pseudo-live signal.
              const effectiveConf = mergedSignal.confidence ?? 0
              const modelData = state.modelData
              if ((effectiveConf === 0 || effectiveConf === undefined) && modelData) {
                let modelTimestamp: Date | null = null
                const rawTs = modelData.timestamp as Date | string | null | undefined
                modelTimestamp = parseUtcTimestamp(rawTs)

                let isFresh = false
                if (modelTimestamp) {
                  const ageMs = Date.now() - modelTimestamp.getTime()
                  // Treat model consensus older than 30 seconds as stale for fallback purposes.
                  isFresh = ageMs <= 30_000
                }

                if (isFresh) {
                  const modelConf = (modelData as any).consensus_confidence ?? (modelData as any).confidence
                  if (modelConf != null && modelConf > 0) {
                    mergedSignal.confidence = modelConf
                    const consensusSignal = (modelData as any).consensus_signal
                    if (consensusSignal != null) {
                      mergedSignal.signal = consensusSignal
                    }
                  }
                }
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
              const newTrades = [normalizedTrade, ...state.recentTrades].slice(0, RECENT_TRADES_MAX)
              return {
                ...state,
                recentTrades: newTrades,
                lastUpdate: now,
                dataSource: 'websocket'
              }
            }
            return state
          case 'market':
            {
              // Keep active positions visually real-time even if portfolio snapshots
              // are slightly delayed by backend cache/update cadence.
              const marketPriceRaw = data?.price
              const marketPrice =
                typeof marketPriceRaw === 'number'
                  ? marketPriceRaw
                  : typeof marketPriceRaw === 'string'
                    ? parseFloat(marketPriceRaw)
                    : NaN

              let nextPortfolio = state.portfolio
              if (
                nextPortfolio &&
                Number.isFinite(marketPrice) &&
                Array.isArray(nextPortfolio.positions)
              ) {
                const usdInrRateRaw =
                  typeof (nextPortfolio as any).usd_inr_rate === 'number'
                    ? (nextPortfolio as any).usd_inr_rate
                    : parseFloat(String((nextPortfolio as any).usd_inr_rate ?? 0))
                const usdInrRate = Number.isFinite(usdInrRateRaw) && usdInrRateRaw > 0 ? usdInrRateRaw : 83
                const contractValueBtc = 0.001
                const symbol = data?.symbol
                const updatedPositions = nextPortfolio.positions.map((pos: any) => {
                  if (!symbol || pos?.symbol !== symbol) return pos
                  const qty =
                    typeof pos.quantity === 'number'
                      ? pos.quantity
                      : parseFloat(String(pos.quantity ?? 0))
                  const entry =
                    typeof pos.entry_price_usd === 'number'
                      ? pos.entry_price_usd
                      : typeof pos.entry_price === 'number'
                        ? pos.entry_price
                        : parseFloat(String(pos.entry_price_usd ?? pos.entry_price ?? 0))
                  const side = String(pos.side ?? '').toUpperCase()
                  const isLong = side === 'BUY' || side === 'LONG'
                  const pnl =
                    isLong
                      ? (marketPrice - entry) * qty * contractValueBtc * usdInrRate
                      : (entry - marketPrice) * qty * contractValueBtc * usdInrRate
                  return {
                    ...pos,
                    current_price: marketPrice,
                    current_price_usd: marketPrice,
                    unrealized_pnl: Number.isFinite(pnl) ? pnl : pos.unrealized_pnl,
                    unrealized_pnl_inr: Number.isFinite(pnl) ? pnl : pos.unrealized_pnl_inr,
                  }
                })

                const totalUnrealized = updatedPositions.reduce((acc: number, pos: any) => {
                  const v =
                    typeof pos.unrealized_pnl === 'number'
                      ? pos.unrealized_pnl
                      : parseFloat(String(pos.unrealized_pnl ?? 0))
                  return acc + (Number.isFinite(v) ? v : 0)
                }, 0)

                const totalRealized =
                  typeof nextPortfolio.total_realized_pnl === 'number'
                    ? nextPortfolio.total_realized_pnl
                    : parseFloat(String(nextPortfolio.total_realized_pnl ?? 0))
                const previousUnrealized =
                  typeof nextPortfolio.total_unrealized_pnl === 'number'
                    ? nextPortfolio.total_unrealized_pnl
                    : parseFloat(String(nextPortfolio.total_unrealized_pnl ?? 0))
                const previousTotalValue =
                  typeof nextPortfolio.total_value === 'number'
                    ? nextPortfolio.total_value
                    : parseFloat(String(nextPortfolio.total_value ?? 0))
                const unrealizedDelta = totalUnrealized - (Number.isFinite(previousUnrealized) ? previousUnrealized : 0)
                const totalValue = (Number.isFinite(previousTotalValue) ? previousTotalValue : 0) + unrealizedDelta

                nextPortfolio = {
                  ...nextPortfolio,
                  positions: updatedPositions,
                  total_unrealized_pnl: totalUnrealized,
                  total_realized_pnl: Number.isFinite(totalRealized) ? totalRealized : nextPortfolio.total_realized_pnl,
                  total_value: Number.isFinite(totalValue) ? totalValue : nextPortfolio.total_value,
                }
              }

            return {
              ...state,
              portfolio: nextPortfolio,
              marketData: {
                ...state.marketData,
                [data.symbol]: data
              },
              lastUpdate: now,
              dataSource: 'websocket'
            }
            }
          case 'model': {
            // Update model data; set or merge main signal so first meaningful update is from consensus
            const hasConsensus = (data.consensus_confidence != null && data.consensus_confidence > 0) ||
              (data.confidence != null && data.confidence > 0)
            const currentConf = state.signal?.confidence ?? 0
            const modelMeta = {
              inference_latency_ms: data.inference_latency_ms,
              inference_source: data.inference_source,
              inference_mode: data.inference_mode,
              model_version: data.model_version,
            }
            const signalFromModel =
              hasConsensus && (!state.signal || currentConf === 0)
                ? {
                    ...data,
                    signal: data.consensus_signal ?? data.signal ?? state.signal?.signal ?? 'HOLD',
                    confidence: data.consensus_confidence ?? data.confidence ?? 0,
                    ...modelMeta,
                  }
                : state.signal
                  ? { ...state.signal, ...data, ...modelMeta }
                  : null
            return {
              ...state,
              modelData: data,
              signal: signalFromModel,
              lastUpdate: now,
              dataSource: 'websocket'
            }
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
          case 'health': {
            const healthPayload = data && typeof data === 'object' ? data : state.health
            if (healthPayload && typeof healthPayload === 'object') {
              const normalized = { ...healthPayload }
              if (normalized.status === undefined && (normalized as any).overall_status !== undefined) {
                normalized.status = (normalized as any).overall_status
              }
              return {
                ...state,
                health: normalized,
                lastUpdate: now,
                dataSource: 'websocket'
              }
            }
            return { ...state, lastUpdate: now, dataSource: 'websocket' }
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
          const newTrades = [data, ...state.recentTrades].slice(0, RECENT_TRADES_MAX)
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
      const newTrades = [normalizedTrade, ...state.recentTrades].slice(0, RECENT_TRADES_MAX)
      return {
        ...state,
        recentTrades: newTrades,
        lastUpdate: new Date(),
        dataSource: 'api'
      }
    }

    case 'HYDRATE_TRADES': {
      const { trades: rawList, merge } = action.payload
      const normalized: Trade[] = []
      const seen = new Set<string>()
      for (const t of rawList) {
        const n = normalizeTradeRecord(t)
        if (!n) continue
        const id = String(n.trade_id)
        if (seen.has(id)) continue
        seen.add(id)
        normalized.push(n)
      }

      let combined: Trade[]
      if (merge) {
        const byId = new Map<string, Trade>()
        for (const t of state.recentTrades) {
          byId.set(String(t.trade_id), t)
        }
        for (const t of normalized) {
          byId.set(String(t.trade_id), t)
        }
        combined = Array.from(byId.values()).sort((a, b) => {
          const ta = new Date(a.executed_at ?? (a as { timestamp?: string }).timestamp ?? 0).getTime()
          const tb = new Date(b.executed_at ?? (b as { timestamp?: string }).timestamp ?? 0).getTime()
          return tb - ta
        })
      } else {
        combined = normalized
      }

      return {
        ...state,
        recentTrades: combined.slice(0, RECENT_TRADES_MAX),
        lastUpdate: new Date(),
        dataSource: 'api',
      }
    }

    case 'RESET_LOCAL_TRADING_STATE':
      return {
        ...state,
        portfolio: null,
        recentTrades: [],
        performanceData: [],
        lastUpdate: new Date(),
        dataSource: 'api',
      }

    case 'UPDATE_AGENT_STATE':
      return {
        ...state,
        agentState: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api'
      }

    case 'UPDATE_HEALTH':
      return {
        ...state,
        health: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api',
      }

    case 'SET_PERFORMANCE_DATA':
      return {
        ...state,
        performanceData: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api'
      }

    case 'SET_LOADING':
      return { ...state, isLoading: action.payload }

    case 'SET_PORTFOLIO_LOADING':
      return { ...state, isPortfolioLoading: action.payload }

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

async function fetchPortfolioSummaryViaRestProxy(): Promise<Portfolio | null> {
  try {
    const base = getBackendProxyBase()
    const res = await fetch(`${base}/api/v1/portfolio/summary`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    })
    if (!res.ok) return null
    const data = (await res.json()) as Portfolio
    if (!data || typeof data !== 'object') return null
    return data
  } catch {
    return null
  }
}

/**
 * Unified hook for all trading data management.
 *
 * This replaces useAgent, useWebSocket, usePortfolio, and other specialized hooks.
 */
function isTradeExecutedMessage(message: unknown): boolean {
  if (!message || typeof message !== 'object') return false
  const m = message as { type?: string; resource?: string }
  return (
    m.type === 'trade_executed' ||
    (m.type === 'data_update' && m.resource === 'trade')
  )
}

function showTradeExecutedToast(data: Record<string, unknown>) {
  const tradeId = data.trade_id
  if (tradeId == null || tradeId === '') return

  const sideRaw = data.side
  const side =
    typeof sideRaw === 'string' ? sideRaw.toUpperCase() : String(sideRaw ?? '').toUpperCase()

  const symbol = typeof data.symbol === 'string' ? data.symbol : '—'

  const rawPrice = data.price ?? data.fill_price ?? data.entry_price
  let priceNum: number | null = null
  if (typeof rawPrice === 'number' && !Number.isNaN(rawPrice)) {
    priceNum = rawPrice
  } else if (typeof rawPrice === 'string') {
    const p = parseFloat(rawPrice)
    if (!Number.isNaN(p)) priceNum = p
  }

  const priceLabel =
    priceNum != null
      ? formatUsdCurrency(priceNum)
      : '—'

  const isBuy = side === 'BUY' || side === 'LONG'

  toast(`${side} ${symbol} @ ${priceLabel}`, {
    icon: isBuy ? '↑' : '↓',
    duration: 4000,
  })
}

export function useTradingData() {
  const [state, dispatch] = useReducer(tradingDataReducer, initialState)
  const { isConnected, lastMessage, sendMessage, error: wsError } = useWebSocket(WS_URL)
  const lastMessageRef = useRef(lastMessage)
  const lastToastedTradeIdRef = useRef<string | null>(null)
  /** True after first mount REST bootstrap completes (success or failure). */
  const portfolioLoadSettledRef = useRef(false)

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

  // Trade executed: toast (deduped; does not change reducer / WS contract)
  useEffect(() => {
    if (!lastMessage || !isTradeExecutedMessage(lastMessage)) return
    const msg = lastMessage as { data?: unknown; payload?: unknown }
    const data = (msg.data ?? msg.payload ?? {}) as Record<string, unknown>
    if (!data || typeof data !== 'object') return
    const id = data.trade_id
    if (id == null || id === '') return
    const idStr = String(id)
    if (lastToastedTradeIdRef.current === idStr) return
    lastToastedTradeIdRef.current = idStr
    showTradeExecutedToast(data as Record<string, unknown>)
  }, [lastMessage])

  // Handle WebSocket errors
  useEffect(() => {
    dispatch({ type: 'SET_ERROR', payload: wsError })
  }, [wsError])

  // REST bootstrap (health, portfolio, trades) without waiting for WebSocket
  useEffect(() => {
    let cancelled = false
    const base = getBackendProxyBase()
    const run = async () => {
      try {
        const [hRes, pRes, tRes] = await Promise.all([
          fetch(`${base}/api/v1/health`, { headers: { Accept: 'application/json' } }),
          fetch(`${base}/api/v1/portfolio/summary`, { headers: { Accept: 'application/json' } }),
          fetch(`${base}/api/v1/portfolio/trades?limit=${RECENT_TRADES_MAX}`, {
            headers: { Accept: 'application/json' },
          }),
        ])
        if (cancelled) return
        if (hRes.ok) {
          const j = await hRes.json()
          const h = normalizeHealthFromRest(j)
          if (h) dispatch({ type: 'UPDATE_HEALTH', payload: h })
        }
        if (pRes.ok) {
          const data = (await pRes.json()) as Portfolio
          if (data && typeof data === 'object') {
            dispatch({ type: 'UPDATE_PORTFOLIO', payload: data })
          }
        }
        if (tRes.ok) {
          const arr = (await tRes.json()) as unknown
          if (Array.isArray(arr)) {
            dispatch({
              type: 'HYDRATE_TRADES',
              payload: { trades: arr as Trade[], merge: false },
            })
          }
        }
      } catch {
        // Non-fatal: backend may be unreachable until later
      } finally {
        if (!cancelled) {
          portfolioLoadSettledRef.current = true
          dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: false })
          dispatch({ type: 'SET_LOADING', payload: false })
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch initial data only when WebSocket is connected (sendCommand requires connection)
  useEffect(() => {
    if (!isConnected) return

    const fetchInitialData = async () => {
      const showPortfolioSpinner = !portfolioLoadSettledRef.current
      dispatch({ type: 'SET_LOADING', payload: true })
      if (showPortfolioSpinner) {
        dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: true })
      }

      try {
        const [
          healthResult,
          portfolioResult,
          tradesResult,
          performanceResult,
          agentStatusResult,
        ] = await Promise.allSettled([
          apiClient.getHealth(),
          apiClient.getPortfolioSummary(),
          apiClient.getTrades(),
          apiClient.getPerformance(),
          apiClient.getAgentStatus(),
        ])

        if (healthResult.status === 'fulfilled') {
          const healthData = healthResult.value
          if (healthData && typeof healthData === 'object') {
            dispatch({ type: 'UPDATE_HEALTH', payload: healthData as HealthData })
          }
        }

        if (portfolioResult.status === 'fulfilled') {
          dispatch({
            type: 'UPDATE_PORTFOLIO',
            payload: portfolioResult.value as Portfolio,
          })
        } else {
          console.warn('Portfolio summary fetch failed:', portfolioResult.reason)
          // Robust fallback path: retry WS command, then fallback to REST proxy.
          let portfolioRecovered: Portfolio | null = null
          for (let attempt = 1; attempt <= 2; attempt++) {
            try {
              await new Promise((r) => setTimeout(r, attempt * 600))
              const retry = (await apiClient.getPortfolioSummary()) as Portfolio
              if (retry && typeof retry === 'object') {
                portfolioRecovered = retry
                break
              }
            } catch {
              // Continue to next retry/fallback
            }
          }
          if (!portfolioRecovered) {
            portfolioRecovered = await fetchPortfolioSummaryViaRestProxy()
          }
          if (portfolioRecovered) {
            dispatch({
              type: 'UPDATE_PORTFOLIO',
              payload: portfolioRecovered,
            })
          }
        }
        dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: false })
        portfolioLoadSettledRef.current = true

        if (tradesResult.status === 'fulfilled') {
          const trades = tradesResult.value
          if (Array.isArray(trades)) {
            dispatch({
              type: 'HYDRATE_TRADES',
              payload: {
                trades: trades as Trade[],
                merge: true,
              },
            })
          }
        }

        if (performanceResult.status === 'fulfilled') {
          const performanceMetrics = performanceResult.value
          if (performanceMetrics && typeof performanceMetrics === 'object') {
            const totalReturn =
              typeof (performanceMetrics as any).total_return === 'number'
                ? (performanceMetrics as any).total_return
                : typeof (performanceMetrics as any).total_return_pct === 'number'
                  ? (performanceMetrics as any).total_return_pct
                  : 0

            dispatch({
              type: 'SET_PERFORMANCE_DATA',
              payload: [{ date: new Date().toISOString(), value: totalReturn }],
            })
          }
        }

        if (agentStatusResult.status === 'fulfilled') {
          const agentStatus = agentStatusResult.value
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
        }

        dispatch({ type: 'SET_LOADING', payload: false })
        dispatch({ type: 'SET_DATA_SOURCE', payload: 'api' })
      } catch (error) {
        console.error('Error fetching initial trading data:', error)
        dispatch({
          type: 'SET_ERROR',
          payload: error instanceof Error ? error : new Error('Unknown error'),
        })
        dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: false })
        portfolioLoadSettledRef.current = true
        dispatch({ type: 'SET_LOADING', payload: false })
      }
    }

    fetchInitialData()
  }, [isConnected])

  const resetLocalTradingState = useCallback(() => {
    dispatch({ type: 'RESET_LOCAL_TRADING_STATE' })
  }, [])

  // Return unified interface
  return {
    // Core data
    signal: state.signal,
    portfolio: state.portfolio,
    recentTrades: state.recentTrades,
    marketData: state.marketData,
    modelData: state.modelData,
    health: state.health,
    performanceData: state.performanceData,

    // Status
    agentState: state.agentState,
    isConnected: state.isConnected,
    lastUpdate: state.lastUpdate,
    dataSource: state.dataSource,

    // State
    isLoading: state.isLoading,
    isPortfolioLoading: state.isPortfolioLoading,
    error: state.error,
    resetLocalTradingState,
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