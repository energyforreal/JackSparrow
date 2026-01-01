'use client'

import { useState, useEffect } from 'react'
import { AgentStatus } from './AgentStatus'
import { PortfolioSummary } from './PortfolioSummary'
import { Header } from './Header'
import { SignalIndicator } from './SignalIndicator'
import { HealthMonitor } from './HealthMonitor'
import { ActivePositions } from './ActivePositions'
import { RecentTrades } from './RecentTrades'
import { PerformanceChart } from './PerformanceChart'
import { ReasoningChainView } from './ReasoningChainView'
import { ModelReasoningView } from './ModelReasoningView'
import { TradingDecision } from './TradingDecision'
import { RealTimePrice } from './RealTimePrice'
import { ErrorBoundary } from './ErrorBoundary'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAgent } from '@/hooks/useAgent'
import { apiClient } from '@/services/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { Signal, HealthStatus, ReasoningStep } from '@/types'
import { normalizeConfidenceToPercent } from '@/utils/formatters'

// Get WebSocket URL from environment variable
// In production, NEXT_PUBLIC_WS_URL must be set
// Fallback to localhost only in development
const WS_URL = 
  process.env.NEXT_PUBLIC_WS_URL || 
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

// Validate WebSocket URL in production
if (process.env.NODE_ENV === 'production' && !process.env.NEXT_PUBLIC_WS_URL) {
  console.error(
    'CRITICAL: NEXT_PUBLIC_WS_URL environment variable is required in production. ' +
    'WebSocket connection will fail.'
  )
}

export function Dashboard() {
  const { isConnected, lastMessage, error: wsError } = useWebSocket(WS_URL)
  const { agentState, portfolio, recentTrades, signal: signalFromHook, lastUpdate } = useAgent()

  // Extract positions from portfolio
  const positions = portfolio?.positions || []

  // State for data that needs to be fetched separately
  // Use signal from hook as primary source, only override with WebSocket updates
  const [signal, setSignal] = useState<Signal | null>(signalFromHook || null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [reasoningChain, setReasoningChain] = useState<ReasoningStep[]>([])
  const [performanceData, setPerformanceData] = useState<Array<{ date: string; value: number }>>([])
  const [isLoading, setIsLoading] = useState(true)
  // Track if we've received a WebSocket signal update to prioritize it over initial fetch
  const [hasWebSocketSignal, setHasWebSocketSignal] = useState(false)
  const [retryCount, setRetryCount] = useState(0)
  // Track data source for debugging
  const [signalDataSource, setSignalDataSource] = useState<string>('none')

  // Fetch initial data on mount (independent of WebSocket)
  // Use shared hooks (useAgent) for portfolio, trades, signal - avoid duplicate fetching
  // Only fetch data not available from hooks (health, performance)
  useEffect(() => {
    const fetchInitialData = async () => {
      setIsLoading(true)
      try {
        // Fetch health status (not available from useAgent hook)
        const healthData = await apiClient.getHealth()
        setHealth(healthData)

        // Fetch performance metrics for chart (not available from useAgent hook)
        try {
          const performance = await apiClient.request<{
            total_return?: number
            total_return_pct?: number
            total_trades?: number
          }>('/api/v1/portfolio/performance?days=30')
          
          // Transform performance data for chart
          // For now, create a simple time series from total_return if available
          if (performance && typeof performance.total_return === 'number') {
            // Create sample data points (in real implementation, this would come from historical data)
            const now = new Date()
            const dataPoints: Array<{ date: string; value: number }> = []
            const baseValue = portfolio?.total_value ? parseFloat(String(portfolio.total_value)) : 10000
            const totalReturnPct = performance.total_return_pct || 0
            
            for (let i = 29; i >= 0; i--) {
              const date = new Date(now)
              date.setDate(date.getDate() - i)
              // Simulate portfolio value progression (in real implementation, use actual historical data)
              const dailyReturn = totalReturnPct / 30
              const value = baseValue * (1 + (dailyReturn * (30 - i)) / 100)
              dataPoints.push({
                date: date.toISOString(),
                value: Math.max(0, value)
              })
            }
            setPerformanceData(dataPoints)
          }
        } catch (perfError) {
          // Performance fetch is optional - log for debugging
          console.debug('Could not fetch performance metrics:', perfError)
        }

        // Signal, portfolio, and trades come from useAgent hook - don't fetch here
        // Only fetch signal if we haven't received one via WebSocket yet
        // This prevents stale initial data from overriding real-time updates
        // Also check if WebSocket is connected - if connected, wait for WebSocket update instead
        if (!hasWebSocketSignal && !isConnected) {
          try {
            const prediction = await apiClient.getPrediction()
            if (prediction) {
              // Only set if we still haven't received WebSocket update
              setSignal((currentSignal) => {
                // Don't override if we've already received a WebSocket signal
                // Also check if WebSocket connected in meantime
                if (hasWebSocketSignal || isConnected || (currentSignal && currentSignal.timestamp)) {
                  if (process.env.NODE_ENV === 'development') {
                    console.log('[Dashboard] Skipping API signal fetch - WebSocket signal already received, WebSocket connected, or current signal exists')
                  }
                  return currentSignal
                }

                const normalizedConfidence = normalizeConfidenceToPercent(
                  prediction.confidence
                )

                const apiSignal: Signal = {
                  signal: prediction.signal as Signal['signal'],
                  confidence: normalizedConfidence,
                  model_consensus: prediction.model_consensus ?? [],
                  individual_model_reasoning:
                    prediction.individual_model_reasoning ?? [],
                  model_predictions: prediction.model_predictions ?? [],
                  reasoning_chain:
                    prediction.reasoning_chain?.steps ?? [],
                  reasoning_chain_full: prediction.reasoning_chain,
                  agent_decision_reasoning:
                    prediction.reasoning_chain?.conclusion,
                  symbol:
                    (prediction.market_context?.symbol as string | undefined) ??
                    'BTCUSD',
                  timestamp: prediction.timestamp,
                }

                setSignalDataSource('api_fetch')

                if (process.env.NODE_ENV === 'development') {
                  console.log('[Dashboard] Signal fetched from API (initial load):', {
                    signal: apiSignal.signal,
                    raw_confidence: prediction.confidence,
                    normalized_confidence: normalizedConfidence,
                    timestamp: apiSignal.timestamp,
                    data_source: 'api_fetch',
                    note: 'This will be overridden by WebSocket updates'
                  })
                }

                return apiSignal
              })
              if (prediction.reasoning_chain && !hasWebSocketSignal) {
                setReasoningChain(
                  Array.isArray(prediction.reasoning_chain.steps)
                    ? prediction.reasoning_chain.steps
                    : []
                )
              }
            }
          } catch (err) {
            // Prediction fetch is optional - log for debugging
            const errorMessage = err instanceof Error ? err.message : String(err)
            console.warn('Could not fetch prediction:', errorMessage)
            // Don't set signal state - leave it null to show "No signal available"
          }
        }
      } catch (error) {
        console.error('Error fetching initial dashboard data:', error)
      } finally {
        setIsLoading(false)
      }
    }

    fetchInitialData()
  }, [hasWebSocketSignal, isConnected, portfolio?.total_value])

  // Sync signal from hook (which also receives WebSocket updates)
  // Only use hook signal if we haven't received a direct WebSocket update
  // This is a fallback - Dashboard's direct WebSocket handler should take priority
  useEffect(() => {
    // Skip if we've already received a direct WebSocket signal update
    if (hasWebSocketSignal) {
      return
    }
    
    if (signalFromHook) {
      // Check if this signal is newer than current signal
      const shouldUpdate = !signal || !signal.timestamp || 
        (signalFromHook.timestamp && new Date(signalFromHook.timestamp) > new Date(signal.timestamp))
      
      if (shouldUpdate) {
        // Normalize confidence to ensure consistent 0-100 range
        const normalizedConfidence = normalizeConfidenceToPercent(signalFromHook.confidence)
        const normalizedSignal: Signal = {
          ...signalFromHook,
          confidence: normalizedConfidence
        }
        
        setSignalDataSource('useAgent_hook')
        setSignal(normalizedSignal)
        
        if (signalFromHook.reasoning_chain) {
          setReasoningChain(
            Array.isArray(signalFromHook.reasoning_chain)
              ? signalFromHook.reasoning_chain
              : []
          )
        }
        
        if (process.env.NODE_ENV === 'development') {
          console.log('[Dashboard] Signal synced from useAgent hook (fallback):', {
            signal: signalFromHook.signal,
            raw_confidence: signalFromHook.confidence,
            normalized_confidence: normalizedConfidence,
            timestamp: signalFromHook.timestamp,
            data_source: 'useAgent_hook',
            note: 'Fallback only - direct WebSocket updates take priority'
          })
        }
      }
    }
  }, [signalFromHook, hasWebSocketSignal, signal])

  // Update data from WebSocket messages - PRIORITIZE these updates
  useEffect(() => {
    if (lastMessage) {
      switch (lastMessage.type) {
        case 'health_update':
          setHealth(lastMessage.data)
          break
        case 'signal_update':
          const signalData = lastMessage.data as Signal
          // Always replace signal on WebSocket update - these are real-time
          if (signalData) {
            setHasWebSocketSignal(true)
            setSignalDataSource('websocket')
            
            // Normalize confidence to ensure consistent 0-100 range
            const normalizedConfidence = normalizeConfidenceToPercent(signalData.confidence)
            
            // Create normalized signal object
            const normalizedSignal: Signal = {
              ...signalData,
              confidence: normalizedConfidence
            }
            
            setSignal(normalizedSignal)
            
            if (signalData?.reasoning_chain) {
              setReasoningChain(
                Array.isArray(signalData.reasoning_chain)
                  ? signalData.reasoning_chain
                  : []
              )
            }
            
            // Enhanced logging for debugging
            if (process.env.NODE_ENV === 'development') {
              console.log('[Dashboard] Signal update received via WebSocket (DIRECT):', {
                signal: signalData.signal,
                raw_confidence: signalData.confidence,
                normalized_confidence: normalizedConfidence,
                timestamp: signalData.timestamp,
                data_source: 'websocket_direct',
                message_type: 'signal_update',
                will_override_api_data: true
              })
            }
          }
          break
        case 'reasoning_chain_update': {
          const reasoningData = lastMessage.data as {
            reasoning_chain?: ReasoningStep[]
            conclusion?: string
            final_confidence?: number
            timestamp?: string | Date
          }
          // Update reasoning chain separately from signal
          if (reasoningData.reasoning_chain) {
            setReasoningChain(
              Array.isArray(reasoningData.reasoning_chain)
                ? reasoningData.reasoning_chain
                : []
            )
          }
          // Also update signal if it exists to include conclusion
          if (reasoningData.conclusion) {
            setSignal((prev) => {
              if (prev) {
                return {
                  ...prev,
                  agent_decision_reasoning: reasoningData.conclusion || prev.agent_decision_reasoning,
                  confidence: reasoningData.final_confidence !== undefined 
                    ? reasoningData.final_confidence 
                    : prev.confidence
                }
              }
              return prev
            })
          }
          console.log('Reasoning chain update received via WebSocket:', {
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
                model_predictions: modelData.model_predictions || prev.model_predictions
              }
            }
            return prev
          })
          console.log('Model prediction update received via WebSocket:', {
            consensusSignal: modelData.consensus_signal,
            consensusConfidence: modelData.consensus_confidence,
            modelCount: modelData.model_consensus?.length || 0
          })
          break
        }
        case 'performance_update':
          const perfData = lastMessage.data
          if (Array.isArray(perfData)) {
            // Ensure data has correct structure
            const formattedData = perfData.map((item: any) => ({
              date: item.date || item.timestamp || new Date().toISOString(),
              value: typeof item.value === 'number' ? item.value : 0
            }))
            setPerformanceData(formattedData)
          }
          break
      }
    }
  }, [lastMessage])

  return (
    <div className="min-h-screen bg-background">
      <Header isConnected={isConnected} />
      <div className="container mx-auto px-4 py-6 space-y-6">
        {wsError && (
          <Card className="border-destructive bg-destructive/5">
            <CardContent className="pt-6">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-destructive font-semibold mb-1">
                    WebSocket Connection Error
                  </div>
                  <div className="text-sm text-muted-foreground mb-4">
                    {wsError.message || 'Unable to connect to real-time updates.'}
                    <br />
                    <span className="text-xs mt-1 block">
                      Ensure backend is running on port 8000 and WebSocket endpoint is accessible.
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setRetryCount((prev) => prev + 1)
                        window.location.reload()
                      }}
                      className="flex items-center gap-2"
                    >
                      <RefreshCw className="h-4 w-4" />
                      Retry Connection
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        // Clear error state - user acknowledges
                        console.log('User dismissed WebSocket error')
                      }}
                    >
                      Dismiss
                    </Button>
                  </div>
                  {retryCount > 0 && (
                    <div className="text-xs text-muted-foreground mt-3">
                      Retry attempts: {retryCount}
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
        
        {/* Top Row: Real-Time Price, Agent Status, Signal Indicator, Health Monitor */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <ErrorBoundary>
            <RealTimePrice symbol="BTCUSD" />
          </ErrorBoundary>
          <ErrorBoundary>
            <AgentStatus 
              state={agentState} 
              lastUpdate={lastUpdate}
              isConnected={isConnected}
            />
          </ErrorBoundary>
          <ErrorBoundary>
            <SignalIndicator signal={signal} />
          </ErrorBoundary>
          <ErrorBoundary>
            <HealthMonitor health={health} />
          </ErrorBoundary>
        </div>

        {/* Portfolio Summary - Full Width */}
        <ErrorBoundary>
          <PortfolioSummary portfolio={portfolio || undefined} isLoading={isLoading && !portfolio} />
        </ErrorBoundary>

        {/* Active Positions and Recent Trades - Side by Side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ErrorBoundary>
            <ActivePositions positions={positions} isLoading={isLoading && !positions} />
          </ErrorBoundary>
          <ErrorBoundary>
            <RecentTrades trades={recentTrades} />
          </ErrorBoundary>
        </div>

        {/* Performance Chart - Full Width */}
        <ErrorBoundary>
          <PerformanceChart data={performanceData} />
        </ErrorBoundary>

        {/* Trading Decision Flow - Full Width */}
        <ErrorBoundary>
          <TradingDecision 
            signal={signal}
            recentTrade={recentTrades?.[0] || null}
            paperTradingMode={true}
          />
        </ErrorBoundary>

        {/* Model Reasoning View - Full Width */}
        <ErrorBoundary>
          <ModelReasoningView 
            modelConsensus={signal?.model_consensus}
            individualModelReasoning={signal?.individual_model_reasoning}
          />
        </ErrorBoundary>

        {/* Reasoning Chain Viewer - Full Width */}
        <ErrorBoundary>
          <ReasoningChainView 
            reasoningChain={reasoningChain}
            chainMeta={signal?.reasoning_chain_full}
            overallConfidence={signal?.confidence}
          />
        </ErrorBoundary>
      </div>
    </div>
  )
}

