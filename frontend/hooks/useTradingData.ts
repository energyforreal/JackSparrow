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
import type { PerformanceDataPoint } from '@/app/components/PerformanceChart'
import toast from 'react-hot-toast'
import { useWebSocket } from './useWebSocket'
import {
  apiClient,
  setWebSocketConnection,
  type RecentTradesMeta,
} from '@/services/api'
import { performanceMetricsToChartData } from '@/utils/performanceMetrics'
import { resolveWebSocketUrl } from '@/lib/websocketUrl'
import { formatCurrency, formatUsdCurrency, parseUtcTimestamp } from '@/utils/formatters'
import { mergeHealthPreserveFields, normalizeHealthPayload } from '@/lib/healthNormalize'
import { resolveContractValueBtc, resolveUsdInrRate } from '@/utils/tradingDisplay'
import {
  ReflectionSnapshotSchema,
} from '@/schemas/api.validation'
import type {
  Signal as SharedSignal,
  Portfolio as SharedPortfolio,
  Trade as SharedTrade,
  HealthStatus,
  SignalType,
  ReflectionSnapshot,
} from '@/types'

// Local types that extend shared domain models where needed
export type Signal = SharedSignal
export type Portfolio = SharedPortfolio
export type Trade = SharedTrade

/** Max trades kept in UI state. */
export const RECENT_TRADES_MAX = 50

/** Terminal trade statuses accepted for the recent-closed-trades table. */
export const TERMINAL_TRADE_STATUSES = new Set([
  'CLOSED',
  'FILLED',
  'EXECUTED',
  'COMPLETED',
])

export interface MarketData {
  symbol: string
  price: number
  volume?: number
  timestamp: string
  change_24h_pct?: number
  high_24h?: number
  low_24h?: number
}

/** Live model-channel snapshot (does not overwrite decision signal). */
export interface ModelConsensusSnapshot {
  signal?: SignalType
  confidence: number
  timestamp?: string
}

/** @deprecated Use ModelConsensusSnapshot */
export type ModelEdgeSnapshot = ModelConsensusSnapshot

export interface ModelData {
  symbol: string
  consensus_signal?: SignalType
  consensus_confidence?: number
  /** Aggregate confidence; WebSocket model payload may expose this alongside consensus_confidence. */
  confidence?: number
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
  performanceData: PerformanceDataPoint[]
  lastReflection: ReflectionSnapshot | null
  modelEdge: ModelEdgeSnapshot | null

  // Status
  agentState: string
  isConnected: boolean
  lastUpdate: Date | null
  dataSource: 'websocket' | 'api' | 'none'

  // Loading states
  isLoading: boolean
  /** True until the portfolio REST request settles (success or failure). */
  isPortfolioLoading: boolean
  /** True until recent-closed-trades REST request settles (success or failure). */
  isTradesLoading: boolean
  isPortfolioRecovering: boolean
  tradesMeta: RecentTradesMeta | null
  tradesError: string | null
  error: Error | null
}

export type { RecentTradesMeta }

// Actions for state management
type TradingDataAction =
  | { type: 'WEBSOCKET_MESSAGE'; payload: any }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_PORTFOLIO_LOADING'; payload: boolean }
  | { type: 'SET_TRADES_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: Error | null }
  | { type: 'UPDATE_SIGNAL'; payload: Signal }
  | { type: 'UPDATE_PORTFOLIO'; payload: Portfolio }
  | { type: 'ADD_TRADE'; payload: Trade }
  | { type: 'UPDATE_MARKET_DATA'; payload: { symbol: string; data: MarketData } }
  | { type: 'UPDATE_MODEL_DATA'; payload: ModelData }
  | { type: 'UPDATE_HEALTH'; payload: HealthData }
  | { type: 'UPDATE_AGENT_STATE'; payload: string }
  | { type: 'SET_PERFORMANCE_DATA'; payload: PerformanceDataPoint[] }
  | { type: 'SET_CONNECTED'; payload: boolean }
  | { type: 'SET_LAST_UPDATE'; payload: Date }
  | { type: 'SET_DATA_SOURCE'; payload: 'websocket' | 'api' | 'none' }
  | {
      type: 'HYDRATE_TRADES'
      payload: { trades: Trade[]; merge?: boolean; meta?: RecentTradesMeta | null }
    }
  | { type: 'SET_TRADES_META'; payload: RecentTradesMeta | null }
  | { type: 'SET_TRADES_ERROR'; payload: string | null }
  | { type: 'SET_PORTFOLIO_RECOVERING'; payload: boolean }
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
  lastReflection: null,
  modelEdge: null,
  agentState: 'UNKNOWN',
  isConnected: false,
  lastUpdate: null,
  dataSource: 'none',
  isLoading: true,
  isPortfolioLoading: true,
  isTradesLoading: true,
  isPortfolioRecovering: false,
  tradesMeta: null,
  tradesError: null,
  error: null,
}

function upsertRecentTrade(trades: Trade[], incoming: Trade): Trade[] {
  const byId = new Map<string, Trade>()
  for (const t of trades) {
    byId.set(String(t.trade_id), t)
  }
  byId.set(String(incoming.trade_id), incoming)
  const combined = Array.from(byId.values()).sort((a, b) => {
    const ta = new Date(a.executed_at ?? (a as { timestamp?: string }).timestamp ?? 0).getTime()
    const tb = new Date(b.executed_at ?? (b as { timestamp?: string }).timestamp ?? 0).getTime()
    return tb - ta
  })
  return combined.slice(0, RECENT_TRADES_MAX)
}

/** Normalize API/WS trade payloads for the Agent trades table. Exported for tests. */
export function normalizeTradeRecord(raw: unknown): Trade | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const id = r.trade_id
  if (id == null || id === '') return null
  const status = String(r.status ?? 'CLOSED').toUpperCase()
  if (!TERMINAL_TRADE_STATUSES.has(status)) return null
  const isFill =
    r.record_kind === 'fill' ||
    r.data_source === 'exchange_fill' ||
    String(id).startsWith('fill_')
  const recordKind = String(r.record_kind ?? (isFill ? 'fill' : ''))
  // Entry-only order fills (WS order_fill) are not closed round-trips.
  if (status === 'EXECUTED' && !isFill && recordKind !== 'round_trip') {
    return null
  }
  const exitTime = (r.exit_time ?? r.closed_at ?? r.executed_at ?? r.timestamp) as Trade['executed_at']
  if (!exitTime) return null
  const entryTimeRaw = r.entry_time ?? r.opened_at
  return {
    ...(raw as Trade),
    trade_id: String(id),
    executed_at: exitTime,
    exit_time: (r.exit_time ?? r.closed_at ?? exitTime) as Trade['exit_time'],
    entry_time: isFill
      ? undefined
      : (entryTimeRaw as Trade['entry_time']),
    status,
    record_kind: (r.record_kind as Trade['record_kind']) ?? (isFill ? 'fill' : 'round_trip'),
    price: (r.price ?? r.exit_price ?? r.fill_price) as Trade['price'],
    exit_price: (r.exit_price ?? r.price ?? r.fill_price) as Trade['exit_price'],
    entry_price: isFill
      ? undefined
      : ((r.entry_price ?? r.price) as Trade['entry_price']),
    duration_seconds:
      typeof r.duration_seconds === 'number'
        ? r.duration_seconds
        : Number.parseInt(String(r.duration_seconds ?? 0), 10) || 0,
  }
}

/** True when a WS trade payload should toast (matches Agent trades table rules). */
export function shouldShowTradeExecutedToast(data: unknown): boolean {
  return normalizeTradeRecord(data) !== null
}

function parseReflectionSnapshot(raw: unknown): ReflectionSnapshot | null {
  if (!raw || typeof raw !== 'object') return null
  const parsed = ReflectionSnapshotSchema.safeParse(raw)
  return parsed.success ? parsed.data : (raw as ReflectionSnapshot)
}

import { mergeSignalPayload } from '@/utils/mergeSignalPayload'

function backendProxyBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_PROXY_BASE || '/api/backend'
}

async function fetchLatestSignalSnapshot(
  symbol: string = 'BTCUSD'
): Promise<Signal | null> {
  try {
    const res = await fetch(
      `${backendProxyBase()}/api/v1/signal/latest?symbol=${encodeURIComponent(symbol)}`
    )
    if (!res.ok) return null
    const body = (await res.json()) as {
      available?: boolean
      signal?: Record<string, unknown> | null
    }
    if (!body?.available || !body.signal || typeof body.signal !== 'object') {
      return null
    }
    return mergeSignalPayload(null, body.signal)
  } catch {
    return null
  }
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
              const mergedSignal = mergeSignalPayload(
                state.signal,
                data as Record<string, unknown>
              )

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
            {
              const normalizedTrade = normalizeTradeRecord(data)
              if (!normalizedTrade) return state
              return {
                ...state,
                recentTrades: upsertRecentTrade(state.recentTrades, normalizedTrade),
                lastUpdate: now,
                dataSource: 'websocket',
              }
            }
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
                const usdInrRate = resolveUsdInrRate((nextPortfolio as Portfolio).usd_inr_rate)
                const contractValueBtc =
                  resolveContractValueBtc((nextPortfolio as Portfolio).contract_value_btc) ?? 0.001
                const symbol = data?.symbol
                if (usdInrRate !== null) {
                  const updatedPositions = nextPortfolio.positions.map((pos: any) => {
                    if (!symbol || pos?.symbol !== symbol) return pos
                    const qty =
                      typeof pos.quantity === 'number'
                        ? pos.quantity
                        : parseFloat(String(pos.quantity ?? 0))
                    const entryUsdRaw = pos.entry_price_usd
                    const entry =
                      typeof entryUsdRaw === 'number'
                        ? entryUsdRaw
                        : parseFloat(String(entryUsdRaw ?? ''))
                    if (!Number.isFinite(entry)) {
                      return {
                        ...pos,
                        current_price: marketPrice,
                        current_price_usd: marketPrice,
                      }
                    }
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
                  const unrealizedDelta =
                    totalUnrealized - (Number.isFinite(previousUnrealized) ? previousUnrealized : 0)
                  const totalValue =
                    (Number.isFinite(previousTotalValue) ? previousTotalValue : 0) + unrealizedDelta

                  nextPortfolio = {
                    ...nextPortfolio,
                    positions: updatedPositions,
                    total_unrealized_pnl: totalUnrealized,
                    total_realized_pnl: Number.isFinite(totalRealized)
                      ? totalRealized
                      : nextPortfolio.total_realized_pnl,
                    total_value: Number.isFinite(totalValue) ? totalValue : nextPortfolio.total_value,
                  }
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
            const rawConf = data.consensus_confidence ?? data.confidence
            const confNum =
              rawConf != null && Number.isFinite(Number(rawConf)) ? Number(rawConf) : 0
            const modelEdge: ModelEdgeSnapshot | null =
              confNum > 0
                ? {
                    signal: (data.consensus_signal ?? data.signal) as SignalType | undefined,
                    confidence: confNum,
                    timestamp:
                      typeof data.timestamp === 'string' ? data.timestamp : undefined,
                  }
                : state.modelEdge
            return {
              ...state,
              modelData: data,
              modelEdge,
              lastUpdate: now,
              dataSource: 'websocket',
            }
          }
          default:
            return state
        }
      }
      
      if (messageType === 'agent_update') {
        const reflection = parseReflectionSnapshot(data?.reflection_snapshot)
        const nextReflection = reflection ?? state.lastReflection
        return {
          ...state,
          agentState: data?.state || state.agentState,
          lastReflection: nextReflection,
          lastUpdate: now,
          dataSource: 'websocket'
        }
      }
      
      if (messageType === 'system_update') {
        switch (resource) {
          case 'health': {
            const healthPayload = data && typeof data === 'object' ? data : state.health
            if (healthPayload && typeof healthPayload === 'object') {
              const n = normalizeHealthPayload(healthPayload)
              const merged =
                n && mergeHealthPreserveFields(state.health, n)
              if (merged) {
                return {
                  ...state,
                  health: merged,
                  lastUpdate: now,
                  dataSource: 'websocket'
                }
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
          case 'performance': {
            const metrics =
              data && typeof data === 'object'
                ? (data as Record<string, unknown>)
                : {}
            const chartData = performanceMetricsToChartData(metrics)
            return {
              ...state,
              performanceData: chartData,
              lastUpdate: now,
              dataSource: 'websocket',
            }
          }
          default:
            return state
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
      const normalizedTrade = normalizeTradeRecord(action.payload)
      if (!normalizedTrade) return state
      return {
        ...state,
        recentTrades: upsertRecentTrade(state.recentTrades, normalizedTrade),
        lastUpdate: new Date(),
        dataSource: 'api',
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
        tradesMeta: action.payload.meta ?? state.tradesMeta,
        tradesError: null,
        lastUpdate: new Date(),
        dataSource: 'api',
      }
    }

    case 'SET_TRADES_META':
      return { ...state, tradesMeta: action.payload }

    case 'SET_TRADES_ERROR':
      return { ...state, tradesError: action.payload }

    case 'SET_PORTFOLIO_RECOVERING':
      return { ...state, isPortfolioRecovering: action.payload }

    case 'RESET_LOCAL_TRADING_STATE':
      return {
        ...state,
        portfolio: null,
        recentTrades: [],
        performanceData: [],
        isTradesLoading: true,
        tradesMeta: null,
        tradesError: null,
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

    case 'UPDATE_SIGNAL':
      return {
        ...state,
        signal: action.payload,
        lastUpdate: new Date(),
        dataSource: 'api',
      }

    case 'UPDATE_HEALTH': {
      const n = normalizeHealthPayload(action.payload)
      const merged =
        n && mergeHealthPreserveFields(state.health, n)
      if (!merged) return state
      return {
        ...state,
        health: merged,
        lastUpdate: new Date(),
        dataSource: 'api',
      }
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

    case 'SET_TRADES_LOADING':
      return { ...state, isTradesLoading: action.payload }

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

const WS_URL = resolveWebSocketUrl()

export class TestnetConnectionError extends Error {
  constructor(message = 'Delta testnet connection is down. Trading is halted.') {
    super(message)
    this.name = 'TestnetConnectionError'
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
  /** True after first WebSocket bootstrap completes (success or failure). */
  const portfolioLoadSettledRef = useRef(false)
  /** Tracks whether WebSocket has connected at least once (for reconnect-only refresh). */
  const hasConnectedOnceRef = useRef(false)

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
      dispatch({ type: 'WEBSOCKET_MESSAGE', payload: lastMessage })
    }
  }, [lastMessage])

  // Trade executed: toast only when row would appear in Agent trades table
  useEffect(() => {
    if (!lastMessage || !isTradeExecutedMessage(lastMessage)) return
    const msg = lastMessage as { data?: unknown; payload?: unknown }
    const data = (msg.data ?? msg.payload ?? {}) as Record<string, unknown>
    if (!data || typeof data !== 'object') return
    if (!shouldShowTradeExecutedToast(data)) return
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

  // Fetch initial data when WebSocket is connected (sendCommand requires connection)
  useEffect(() => {
    if (!isConnected) return

    const isReconnect = hasConnectedOnceRef.current
    hasConnectedOnceRef.current = true

    const fetchInitialData = async () => {
      const isLightReconnect = isReconnect && portfolioLoadSettledRef.current
      const showPortfolioSpinner = !portfolioLoadSettledRef.current && !isLightReconnect

      if (!isLightReconnect) {
        dispatch({ type: 'SET_LOADING', payload: true })
      }
      if (showPortfolioSpinner) {
        dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: true })
      }
      dispatch({ type: 'SET_TRADES_LOADING', payload: true })

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
          apiClient.getRecentClosedTrades(RECENT_TRADES_MAX),
          isLightReconnect ? Promise.resolve(null) : apiClient.getPerformance(),
          isLightReconnect ? Promise.resolve(null) : apiClient.getAgentStatus(),
        ])

        if (healthResult.status === 'fulfilled') {
          const healthData = healthResult.value
          if (healthData && typeof healthData === 'object') {
            dispatch({ type: 'UPDATE_HEALTH', payload: healthData as HealthData })
          }
        }

        if (!isLightReconnect) {
          const latest = await fetchLatestSignalSnapshot('BTCUSD')
          if (latest) {
            dispatch({ type: 'UPDATE_SIGNAL', payload: latest })
          }
        }

        if (portfolioResult.status === 'fulfilled') {
          const portfolioPayload = portfolioResult.value as Portfolio
          dispatch({
            type: 'UPDATE_PORTFOLIO',
            payload: portfolioPayload,
          })
          if (portfolioPayload?.sync_status === 'error') {
            dispatch({
              type: 'SET_ERROR',
              payload: new TestnetConnectionError(
                'Delta testnet connection is down. Trading is halted until the exchange is reachable.'
              ),
            })
          }
        } else {
          console.warn('Portfolio summary fetch failed:', portfolioResult.reason)
          dispatch({ type: 'SET_PORTFOLIO_RECOVERING', payload: true })
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
              // Continue to next retry
            }
          }
          dispatch({ type: 'SET_PORTFOLIO_RECOVERING', payload: false })
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
          const { trades, meta } = tradesResult.value
          dispatch({
            type: 'HYDRATE_TRADES',
            payload: {
              trades: trades as Trade[],
              merge: true,
              meta,
            },
          })
        } else {
          console.warn('Recent closed trades fetch failed:', tradesResult.reason)
          const reason = tradesResult.reason
          const message =
            reason instanceof Error
              ? reason.message
              : 'Failed to load recent trades'
          dispatch({ type: 'SET_TRADES_ERROR', payload: message })
        }
        dispatch({ type: 'SET_TRADES_LOADING', payload: false })

        if (!isLightReconnect && performanceResult.status === 'fulfilled') {
          const performanceMetrics = performanceResult.value
          if (performanceMetrics && typeof performanceMetrics === 'object') {
            dispatch({
              type: 'SET_PERFORMANCE_DATA',
              payload: performanceMetricsToChartData(
                performanceMetrics as Record<string, unknown>
              ),
            })
          }
        }

        if (!isLightReconnect && agentStatusResult.status === 'fulfilled') {
          const agentStatus = agentStatusResult.value
          if (agentStatus?.state) {
            dispatch({ type: 'UPDATE_AGENT_STATE', payload: agentStatus.state })
          }
        }

        if (!isLightReconnect) {
          dispatch({ type: 'SET_LOADING', payload: false })
        }
        dispatch({ type: 'SET_DATA_SOURCE', payload: 'api' })
      } catch (error) {
        console.error('Error fetching initial trading data:', error)
        const err =
          error instanceof TestnetConnectionError
            ? error
            : error instanceof Error
              ? error
              : new Error('Unknown error')
        if (error instanceof TestnetConnectionError) {
          toast.error(err.message)
        }
        dispatch({
          type: 'SET_ERROR',
          payload: err,
        })
        dispatch({ type: 'SET_PORTFOLIO_LOADING', payload: false })
        dispatch({ type: 'SET_TRADES_LOADING', payload: false })
        portfolioLoadSettledRef.current = true
        if (!isLightReconnect) {
          dispatch({ type: 'SET_LOADING', payload: false })
        }
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
    lastReflection: state.lastReflection,
    modelEdge: state.modelEdge,

    // Status
    agentState: state.agentState,
    isConnected: state.isConnected,
    lastUpdate: state.lastUpdate,
    dataSource: state.dataSource,
    syncStatus: state.portfolio?.sync_status ?? null,

    // State
    isLoading: state.isLoading,
    isPortfolioLoading: state.isPortfolioLoading,
    isPortfolioRecovering: state.isPortfolioRecovering,
    isTradesLoading: state.isTradesLoading,
    tradesMeta: state.tradesMeta,
    tradesError: state.tradesError,
    error: state.error,
    resetLocalTradingState,
  }
}

// Convenience selectors for specific data types
export function useSignal() {
  const { signal } = useTradingData()
  return signal
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