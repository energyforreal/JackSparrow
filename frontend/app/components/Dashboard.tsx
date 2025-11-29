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
import { ErrorBoundary } from './ErrorBoundary'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAgent } from '@/hooks/useAgent'
import { apiClient } from '@/services/api'
import { Card, CardContent } from '@/components/ui/card'
import { Signal, HealthStatus, ReasoningStep } from '@/types'

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
  const { agentState, portfolio, recentTrades, lastUpdate } = useAgent()

  // Extract positions from portfolio
  const positions = portfolio?.positions || []

  // State for data that needs to be fetched separately
  const [signal, setSignal] = useState<Signal | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [reasoningChain, setReasoningChain] = useState<ReasoningStep[]>([])
  const [performanceData, setPerformanceData] = useState<Array<{ date: string; value: number }>>([])
  const [isLoading, setIsLoading] = useState(true)

  // Fetch initial data on mount (independent of WebSocket)
  useEffect(() => {
    const fetchInitialData = async () => {
      setIsLoading(true)
      try {
        // Fetch health status
        const healthData = await apiClient.getHealth()
        setHealth(healthData)

        // Fetch performance metrics for chart
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

        // Fetch latest prediction for signal
        try {
          const prediction = await apiClient.getPrediction()
          if (prediction) {
            setSignal({
              signal: prediction.signal,
              confidence: prediction.confidence,
              timestamp: prediction.timestamp
            })
            if (prediction.reasoning_chain) {
              setReasoningChain(
                Array.isArray(prediction.reasoning_chain)
                  ? prediction.reasoning_chain
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
      } catch (error) {
        console.error('Error fetching initial dashboard data:', error)
      } finally {
        setIsLoading(false)
      }
    }

    fetchInitialData()
  }, [])

  // Update data from WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      switch (lastMessage.type) {
        case 'health_update':
          setHealth(lastMessage.data)
          break
        case 'signal_update':
          const signalData = lastMessage.data as Signal
          setSignal(signalData)
          if (signalData?.reasoning_chain) {
            setReasoningChain(
              Array.isArray(signalData.reasoning_chain)
                ? signalData.reasoning_chain
                : []
            )
          }
          break
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
          <Card className="border-destructive">
            <CardContent className="pt-6">
              <div className="text-destructive font-medium">
                WebSocket Error: {wsError.message}
              </div>
              <div className="text-sm text-muted-foreground mt-2">
                Real-time updates unavailable. Ensure backend is running on port 8000 and WebSocket endpoint is accessible.
              </div>
            </CardContent>
          </Card>
        )}
        
        {/* Top Row: Agent Status, Signal Indicator, Health Monitor */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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

        {/* Reasoning Chain Viewer - Full Width */}
        <ErrorBoundary>
          <ReasoningChainView 
            reasoningChain={reasoningChain}
            overallConfidence={signal?.confidence}
          />
        </ErrorBoundary>
      </div>
    </div>
  )
}

