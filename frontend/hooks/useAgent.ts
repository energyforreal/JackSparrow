import { useState, useEffect } from 'react'
import { useWebSocket } from './useWebSocket'
import { apiClient } from '@/services/api'
import { Portfolio, Trade, Signal } from '@/types'
import { normalizeDate, normalizeConfidenceToPercent } from '@/utils/formatters'

// Get WebSocket URL from environment variable
// In production, NEXT_PUBLIC_WS_URL must be set
// Fallback to localhost only in development
const WS_URL = 
  process.env.NEXT_PUBLIC_WS_URL || 
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

export function useAgent() {
  const { isConnected, lastMessage } = useWebSocket(WS_URL)
  const [agentState, setAgentState] = useState<string>('UNKNOWN')
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [recentTrades, setRecentTrades] = useState<Trade[]>([])
  const [signal, setSignal] = useState<Signal | null>(null)
  // Initialize with null to prevent hydration mismatch - will be set on client mount
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  // Track data source for debugging
  const [dataSource, setDataSource] = useState<'websocket' | 'api' | 'none'>('none')

  useEffect(() => {
    if (lastMessage) {
      switch (lastMessage.type) {
        case 'agent_state': {
          const data = lastMessage.data as { state?: string; last_update?: string | Date; timestamp?: string | Date }
          if (data?.state) {
            setAgentState(data.state)
          }
          // Always update timestamp - use message timestamp or current time
          // Use normalizeDate to ensure UTC timestamps are parsed correctly before IST conversion
          if (data?.last_update) {
            try {
              const ts = normalizeDate(data.last_update)
              if (!isNaN(ts.getTime())) {
                setLastUpdate(ts)
                // Debug logging in development mode
                if (process.env.NODE_ENV === 'development') {
                  console.log('Agent state update:', {
                    state: data?.state,
                    last_update: data?.last_update,
                    parsed_timestamp: ts,
                    parsed_utc: ts.toISOString(),
                    is_valid: true
                  })
                }
              } else {
                setLastUpdate(new Date()) // Fallback to current time
                if (process.env.NODE_ENV === 'development') {
                  console.warn('Agent state: Invalid last_update timestamp, using current time', {
                    last_update: data?.last_update
                  })
                }
              }
            } catch (error) {
              setLastUpdate(new Date()) // Fallback to current time
              if (process.env.NODE_ENV === 'development') {
                console.warn('Agent state: Error parsing last_update timestamp, using current time', {
                  last_update: data?.last_update,
                  error
                })
              }
            }
          } else if (data?.timestamp) {
            try {
              const ts = normalizeDate(data.timestamp)
              if (!isNaN(ts.getTime())) {
                setLastUpdate(ts)
                if (process.env.NODE_ENV === 'development') {
                  console.log('Agent state update:', {
                    state: data?.state,
                    timestamp: data?.timestamp,
                    parsed_timestamp: ts,
                    parsed_utc: ts.toISOString(),
                    is_valid: true
                  })
                }
              } else {
                setLastUpdate(new Date()) // Fallback to current time
                if (process.env.NODE_ENV === 'development') {
                  console.warn('Agent state: Invalid timestamp, using current time', {
                    timestamp: data?.timestamp
                  })
                }
              }
            } catch (error) {
              setLastUpdate(new Date()) // Fallback to current time
              if (process.env.NODE_ENV === 'development') {
                console.warn('Agent state: Error parsing timestamp, using current time', {
                  timestamp: data?.timestamp,
                  error
                })
              }
            }
          } else {
            // Always update to current time if no timestamp in message
            setLastUpdate(new Date())
            if (process.env.NODE_ENV === 'development') {
              console.log('Agent state update: No timestamp in message, using current time', {
                state: data?.state
              })
            }
          }
          break
        }
        case 'portfolio_update':
          // Prioritize WebSocket updates - immediately replace API data
          const portfolioData = lastMessage.data as Portfolio
          if (portfolioData) {
            // Clear any cached/old portfolio data and set new data immediately
            setPortfolio(portfolioData)
            setDataSource('websocket')
            
            // Update lastUpdate timestamp if available
            if (portfolioData.timestamp) {
              try {
                const ts = normalizeDate(portfolioData.timestamp)
                if (!isNaN(ts.getTime())) {
                  setLastUpdate(ts)
                }
              } catch {
                // Ignore timestamp parsing errors
              }
            }
            
            if (process.env.NODE_ENV === 'development') {
              console.log('[useAgent] Portfolio update received via WebSocket:', {
                total_value: portfolioData.total_value,
                open_positions: portfolioData.open_positions,
                positions_count: portfolioData.positions?.length || 0,
                timestamp: portfolioData.timestamp,
                data_source: 'websocket',
                will_replace_api_data: true
              })
            }
          }
          break
        case 'trade_executed':
          // Add new trade to recent trades list - prioritize WebSocket updates
          const tradeData = lastMessage.data as Trade
          if (tradeData) {
            setRecentTrades((prev) => {
              // Avoid duplicates - check if trade_id already exists
              const exists = prev.some(t => t.trade_id === tradeData.trade_id)
              if (exists) {
                return prev // Don't add duplicate
              }
              return [tradeData, ...prev].slice(0, 10)
            })
            setDataSource('websocket')
            
            if (process.env.NODE_ENV === 'development') {
              console.log('[useAgent] Trade executed received via WebSocket:', {
                trade_id: tradeData.trade_id,
                symbol: tradeData.symbol,
                side: tradeData.side,
                price: tradeData.price,
                timestamp: tradeData.timestamp,
                data_source: 'websocket',
                position_id: (tradeData as any).position_id // Include position_id if available
              })
            }
          }
          break
        case 'signal_update':
          const signalData = lastMessage.data as Signal
          if (signalData) {
            // Normalize confidence to ensure consistent 0-100 range
            // Backend sends confidence in 0-100 range, but normalize to be safe
            const normalizedConfidence = normalizeConfidenceToPercent(signalData.confidence)
            
            // Create normalized signal object
            const normalizedSignal: Signal = {
              ...signalData,
              confidence: normalizedConfidence
            }
            
            // Always replace signal completely on WebSocket update
            setSignal(normalizedSignal)
            setDataSource('websocket')
            
            // Update lastUpdate based on signal timestamp so UI shows fresh time
            // Use normalizeDate to ensure UTC timestamps are parsed correctly
            if (signalData.timestamp) {
              try {
                const ts = normalizeDate(signalData.timestamp as any)
                if (!isNaN(ts.getTime())) {
                  setLastUpdate(ts)
                  // Enhanced debug logging in development mode
                  if (process.env.NODE_ENV === 'development') {
                    console.log('[useAgent] Signal update - timestamp parsed:', {
                      raw_timestamp: signalData.timestamp,
                      timestamp_type: typeof signalData.timestamp,
                      parsed_date: ts,
                      parsed_utc_iso: ts.toISOString(),
                      parsed_local_string: ts.toString(),
                      current_time_utc: new Date().toISOString(),
                      current_time_local: new Date().toString(),
                      time_difference_ms: new Date().getTime() - ts.getTime(),
                      signal: signalData.signal,
                      raw_confidence: signalData.confidence,
                      normalized_confidence: normalizedConfidence,
                      data_source: 'websocket'
                    })
                  }
                } else {
                  setLastUpdate(new Date())
                  if (process.env.NODE_ENV === 'development') {
                    console.warn('[useAgent] Signal update - invalid timestamp, using current time:', {
                      raw_timestamp: signalData.timestamp,
                      timestamp_type: typeof signalData.timestamp
                    })
                  }
                }
              } catch (error) {
                setLastUpdate(new Date())
                if (process.env.NODE_ENV === 'development') {
                  console.error('[useAgent] Signal update - error parsing timestamp:', {
                    raw_timestamp: signalData.timestamp,
                    error: error instanceof Error ? error.message : String(error),
                    stack: error instanceof Error ? error.stack : undefined
                  })
                }
              }
            } else {
              setLastUpdate(new Date())
              if (process.env.NODE_ENV === 'development') {
                console.log('[useAgent] Signal update - no timestamp, using current time:', {
                  signal: signalData.signal,
                  confidence: signalData.confidence
                })
              }
            }
            // Log for debugging
            if (process.env.NODE_ENV === 'development') {
              console.log('[useAgent] Signal update received:', {
                signal: signalData.signal,
                confidence: signalData.confidence,
                timestamp: signalData.timestamp,
                has_timestamp: !!signalData.timestamp
              })
            }
          }
          break
        case 'position_closed':
          // When position is closed, refresh portfolio to update positions list
          // Portfolio update will be broadcast separately, but we can trigger a refresh here
          // The portfolio_update message will handle the actual update
          break
        case 'reasoning_chain_update': {
          const reasoningData = lastMessage.data as {
            reasoning_chain?: any[]
            conclusion?: string
            final_confidence?: number
            timestamp?: string | Date
          }
          // Update signal with reasoning chain if signal exists
          setSignal((prev) => {
            if (prev) {
              return {
                ...prev,
                reasoning_chain: reasoningData.reasoning_chain || prev.reasoning_chain,
                agent_decision_reasoning: reasoningData.conclusion || prev.agent_decision_reasoning,
                confidence: reasoningData.final_confidence !== undefined 
                  ? reasoningData.final_confidence 
                  : prev.confidence,
                timestamp: reasoningData.timestamp || prev.timestamp
              }
            }
            return prev
          })
          // Update lastUpdate if timestamp provided
          // Use normalizeDate to ensure UTC timestamps are parsed correctly
          if (reasoningData.timestamp) {
            try {
              const ts = normalizeDate(reasoningData.timestamp)
              if (!isNaN(ts.getTime())) {
                setLastUpdate(ts)
              }
            } catch (error) {
              // Silently ignore parsing errors
            }
          }
          console.log('Agent hook: Reasoning chain update received', {
            stepCount: reasoningData.reasoning_chain?.length || 0,
            conclusion: reasoningData.conclusion
          })
          break
        }
        case 'model_prediction_update': {
          const modelData = lastMessage.data as {
            consensus_signal?: number
            consensus_confidence?: number
            individual_model_reasoning?: any[]
            model_consensus?: any[]
            model_predictions?: any[]
            timestamp?: string | Date
          }
          // Update signal with model predictions
          setSignal((prev) => {
            if (prev) {
              return {
                ...prev,
                model_consensus: modelData.model_consensus || prev.model_consensus,
                individual_model_reasoning: modelData.individual_model_reasoning || prev.individual_model_reasoning,
                model_predictions: modelData.model_predictions || prev.model_predictions,
                timestamp: modelData.timestamp || prev.timestamp
              }
            }
            return prev
          })
          // Update lastUpdate if timestamp provided
          // Use normalizeDate to ensure UTC timestamps are parsed correctly
          if (modelData.timestamp) {
            try {
              const ts = normalizeDate(modelData.timestamp)
              if (!isNaN(ts.getTime())) {
                setLastUpdate(ts)
              }
            } catch (error) {
              // Silently ignore parsing errors
            }
          }
          console.log('Agent hook: Model prediction update received', {
            consensusSignal: modelData.consensus_signal,
            consensusConfidence: modelData.consensus_confidence,
            modelCount: modelData.model_consensus?.length || 0
          })
          break
        }
      }
    }
  }, [lastMessage])

  // Initialize lastUpdate on client mount to prevent hydration mismatch
  useEffect(() => {
    // Only set initial timestamp on client side after mount (runs once)
    setLastUpdate(new Date())
  }, []) // Empty dependency array - only run once on mount

  // Fetch initial data on mount, independent of WebSocket state
  // WebSocket updates will replace this data immediately when received
  useEffect(() => {
    let retryCount = 0
    const maxRetries = 3
    const retryDelay = 1000 // 1 second

    const fetchInitialData = async (): Promise<void> => {
      try {
        // Fetch portfolio data (will be replaced by WebSocket update if available)
        const portfolioData = await apiClient.getPortfolioSummary()
        setPortfolio(portfolioData)
        
        // Fetch recent trades (will be replaced by WebSocket updates)
        try {
          const trades = await apiClient.getTrades()
          if (Array.isArray(trades)) {
            setRecentTrades(trades.slice(0, 10)) // Keep only most recent 10
          }
        } catch (tradesError) {
          // Trades fetch is optional, continue with other data
          console.debug('Could not fetch trades:', tradesError)
        }
        
        // Fetch agent status to get initial state and lastUpdate
        try {
          const agentStatus = await apiClient.getAgentStatus()
          if (agentStatus?.state) {
            setAgentState(agentStatus.state)
          }
        } catch (statusError) {
          // Agent status fetch is optional, continue with portfolio data
          console.debug('Could not fetch agent status:', statusError)
        }
        
        retryCount = 0 // Reset retry count on success
        setDataSource('api')
        
        if (process.env.NODE_ENV === 'development') {
          console.log('[useAgent] Initial data fetched from API:', {
            has_portfolio: !!portfolioData,
            portfolio_total_value: portfolioData?.total_value,
            data_source: 'api_initial',
            note: 'This will be replaced by WebSocket updates when received'
          })
        }
      } catch (error) {
        console.error('Error fetching initial data:', error)
        
        // Retry with exponential backoff
        if (retryCount < maxRetries) {
          retryCount++
          const delay = retryDelay * Math.pow(2, retryCount - 1)
          setTimeout(() => {
            fetchInitialData()
          }, delay)
        }
      }
    }

    // Fetch immediately on mount
    // Note: WebSocket updates will replace this data when received
    fetchInitialData()
  }, []) // Empty dependency array - only run on mount

  return { 
    agentState, 
    portfolio, 
    recentTrades, 
    signal, 
    isConnected, 
    lastUpdate,
    dataSource // Expose data source for debugging
  }
}

